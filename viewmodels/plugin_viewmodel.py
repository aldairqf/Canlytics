from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from collections import defaultdict, deque
from concurrent.futures import Future, InvalidStateError
from pathlib import Path
from typing import Any, Callable

import polars as pl
from PySide6.QtCore import QCoreApplication, QObject, QThread, QTimer, Qt, Signal as QtSignal, Slot

from canlytics_sdk import DbcMessageInfo, DbcSignalInfo, J1939Response
from models.analysis_context import AnalysisContext
from models.plugin import PluginRecord
from services.analyze_data import build_summary
from services.can_data_parser import FRAME_SCHEMA
from services.log_export import export_dataframe
from services.plugin_manager import PluginManager
from services.j1939_transmit import (
    J1939AbortError,
    J1939TransmitSession,
    J1939TransmitTimeouts,
    build_single_frame,
)
from services.j1939_transport import J1939CommandedReceiver, J1939TransportReceiver
from utils.j1939 import J1939
from services.range_diff import TimeRange, build_range_diff_report
from services.candidate_interpretations import build_candidate_items

logger = logging.getLogger(__name__)
class _GuiCall:
    def __init__(self, callback: Callable[[], Any]):
        self.callback = callback
        self.event = threading.Event()
        self.result: list[Any] = []


class _PluginOperation:
    def __init__(self, future: Future, owner: str, kind: str):
        self.future = future
        self.owner = owner
        self.kind = kind
        self.session: J1939TransmitSession | None = None
        self.timer: QTimer | None = None
        self.receiver_timer: QTimer | None = None
        self.entry_ids: list[str] = []
        self.entry_frame_kinds: dict[str, str] = {}
        self.control_entry_ids: set[str] = set()
        self.pending_response: J1939Response | None = None
        self.cancel_requested = False
        self.wait_pgn = 0
        self.wait_sa: int | None = None
        self.deadline = 0.0
        self.transport_key: tuple[int, int] | None = None
        self.queued_payload: tuple[int, bytes, int, int] | None = None
        self.commanded_receiver: J1939CommandedReceiver | None = None


class _GuiFuture(Future):
    def __init__(self, dispatch: Callable[[Callable[[], None], bool], None], gui_thread: QThread) -> None:
        super().__init__()
        self._dispatch = dispatch
        self._gui_thread = gui_thread

    def add_done_callback(self, fn: Callable[[Future], None]) -> None:
        def deliver(future: Future) -> None:
            wait = QThread.currentThread() != self._gui_thread
            self._dispatch(lambda: fn(future), wait)
        super().add_done_callback(deliver)


class _PluginChunkBridge(QObject):
    chunk_received = QtSignal(object)

    def __init__(self, callback: Callable[[pl.DataFrame], None], plugin_id: str, parent: QObject) -> None:
        super().__init__(parent)
        self._callback = callback
        self._plugin_id = plugin_id
        self.chunk_received.connect(self._deliver)

    @Slot(object)
    def receive(self, chunk: pl.DataFrame) -> None:
        self.chunk_received.emit(chunk)

    @Slot(object)
    def _deliver(self, chunk: pl.DataFrame) -> None:
        try:
            self._callback(chunk.clone())
        except Exception:
            logger.exception("Plugin %s live chunk listener failed", self._plugin_id)


class _PluginAnalysis:
    def summarize(self, dataframe: pl.DataFrame, can_id: str | None = None) -> dict[str, Any]:
        selected = dataframe
        if can_id is not None:
            if "ID" not in dataframe.columns:
                raise ValueError("The frame table does not contain an ID column")
            selected = dataframe.filter(pl.col("ID") == str(can_id))
        return build_summary(selected, can_id, (), "")

    def candidates(
        self,
        dataframe: pl.DataFrame,
        can_ids: set[str],
        *,
        min_length: int = 8,
        max_length: int = 8,
        granularity: int = 8,
        endianness: str = "Little Endian",
        value_type: str = "Unsigned",
        include_constant: bool = False,
        mux_configs: list | None = None,
        byte_indices: set[int] | None = None,
    ) -> list[Any]:
        return build_candidate_items(
            dataframe,
            checked_ids=set(can_ids),
            mux_configs=list(mux_configs or []),
            min_length=min_length,
            max_length=max_length,
            granularity=granularity,
            endianness=endianness,
            value_type=value_type,
            include_constant=include_constant,
            byte_indices=byte_indices,
        )

    def compare_ranges(
        self,
        dataframe: pl.DataFrame,
        start_a: float,
        end_a: float,
        start_b: float,
        end_b: float,
    ) -> Any:
        return build_range_diff_report(dataframe, TimeRange(start_a, end_a), TimeRange(start_b, end_b))


class _PluginContext(QObject):
    _gui_call_requested = QtSignal(object)
    _cancel_requested = QtSignal(str)
    _callback_requested = QtSignal(object)

    def __init__(self, host: Any) -> None:
        super().__init__()
        self._host = host
        self._analysis = _PluginAnalysis()
        self._subscriptions: dict[str, list[Any]] = {}
        self._operations: dict[str, _PluginOperation] = {}
        self._entry_to_operation: dict[str, str] = {}
        self._transport_queues: dict[tuple[int, int], deque[str]] = defaultdict(deque)
        self._active_transports: dict[tuple[int, int], str] = {}
        self._transport_receiver = J1939TransportReceiver()
        self._chunk_listener_connected = False
        self._closed = False
        self._gui_call_requested.connect(self._run_gui_call, Qt.ConnectionType.QueuedConnection)
        self._cancel_requested.connect(self._cancel_operation)
        self._callback_requested.connect(self._run_callback, Qt.ConnectionType.QueuedConnection)
        can_send_vm = getattr(self._host, "can_send_vm", None)
        finished_signal = getattr(can_send_vm, "plugin_send_finished", None)
        if finished_signal is not None:
            finished_signal.connect(self._on_plugin_send_finished)

    @Slot(object)
    def _run_gui_call(self, call: _GuiCall) -> None:
        try:
            if self._closed:
                raise RuntimeError("Plugin context is shut down")
            call.result.append(call.callback())
        except Exception as exc:
            call.result.append(exc)
        finally:
            call.event.set()

    @Slot(object)
    def _run_callback(self, call: _GuiCall) -> None:
        if call.event.is_set() or self._closed:
            return
        try:
            call.result.append(call.callback())
        except Exception as exc:
            call.result.append(exc)
        finally:
            call.event.set()

    def _dispatch_callback(self, callback: Callable[[], None], wait: bool = False) -> None:
        if self._closed or QCoreApplication.instance() is None:
            return
        call = _GuiCall(callback)
        self._callback_requested.emit(call)

    def _call_gui(self, callback: Callable[[], Any]) -> Any:
        if self._closed:
            raise RuntimeError("Plugin context is shut down")
        if QThread.currentThread() == self.thread():
            return callback()
        if QCoreApplication.instance() is None:
            raise RuntimeError("GUI event loop is unavailable")
        call = _GuiCall(callback)
        self._gui_call_requested.emit(call)
        deadline = time.monotonic() + 5.0
        while not call.event.wait(0.05):
            if self._closed:
                raise RuntimeError("Plugin context is shut down")
            if time.monotonic() >= deadline:
                raise RuntimeError("GUI event loop did not process the plugin operation")
        result = call.result[0]
        if isinstance(result, Exception):
            raise result
        return result

    def _listen_for_operations(self) -> None:
        if self._chunk_listener_connected:
            return
        connection_vm = getattr(self._host, "connection_vm", None)
        if connection_vm is None:
            return
        connection_vm.chunk_ready.connect(self._record_transport_frames)
        self._chunk_listener_connected = True
        self._transport_receiver.reset()

    def _stop_listening_if_idle(self) -> None:
        if self._operations or not self._chunk_listener_connected:
            return
        connection_vm = getattr(self._host, "connection_vm", None)
        if connection_vm is not None:
            try:
                connection_vm.chunk_ready.disconnect(self._record_transport_frames)
            except (RuntimeError, TypeError):
                pass
        self._chunk_listener_connected = False
        self._transport_receiver.reset()

    @property
    def frame_schema(self) -> dict[str, str]:
        return {name: str(dtype) for name, dtype in FRAME_SCHEMA.items()}

    def get_frames(self) -> pl.DataFrame:
        return self._host.data_vm.df.clone()

    def list_dbc_names(self) -> tuple[str, ...]:
        return tuple(entry.name for entry in self._host.dbc_manager.list_entries())

    def decode_frame(self, can_id: str, data_hex: str) -> tuple[dict[str, Any], ...]:
        return tuple(self._host.dbc_manager.decode_frame(can_id, data_hex))

    def get_working_dbc_messages(self) -> tuple[DbcMessageInfo, ...]:
        messages = []
        for message in self._host.working_dbc.list_messages():
            signals = tuple(
                DbcSignalInfo(
                    name=signal.name,
                    start=signal.start,
                    length=signal.length,
                    scale=signal.scale,
                    offset=signal.offset,
                    unit=signal.unit or "",
                )
                for signal in message.signals
            )
            messages.append(DbcMessageInfo(message.frame_id, message.name, message.length, signals))
        return tuple(messages)

    @property
    def analysis(self) -> _PluginAnalysis:
        return self._analysis

    def export_log(self, dataframe: pl.DataFrame, path: str) -> str:
        protected = [*self._host.data_vm.source_paths, self._host.session_state.working_dbc_path]
        protected.extend(entry.path for entry in self._host.dbc_manager.list_entries())
        return str(export_dataframe(dataframe, path, protected_paths=protected))

    def list_session_markers(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._host.mcp_session_vm.snapshot.list_session_markers())

    def send_frame(self, can_id: int | str, data: bytes | str, *, extended: bool = False) -> str:
        return self._call_gui(lambda: self._host.can_send_vm.send_plugin_frame(
            can_id, data, extended=extended
        ))

    def send_pgn(self, pgn: int, data: bytes, *, source_address: int,
                 destination_address: int = 255, _owner: str = "") -> Future[tuple[str, ...]]:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            return self._failed_future(TypeError("J1939 payload must be bytes-like"))
        if QCoreApplication.instance() is None:
            return self._failed_future(RuntimeError("GUI event loop is unavailable"))
        future: Future[tuple[str, ...]] = _GuiFuture(self._dispatch_callback, self.thread())
        operation_id = uuid.uuid4().hex
        future.add_done_callback(
            lambda done, op_id=operation_id: self._cancel_requested.emit(op_id) if done.cancelled() else None
        )
        try:
            self._call_gui(lambda: self._begin_send_pgn(
                operation_id, future, int(pgn), bytes(data), source_address, destination_address, _owner
            ))
        except Exception as exc:
            self._complete_future(future, error=exc)
        return future

    def _failed_future(self, error: Exception) -> Future:
        future = _GuiFuture(self._dispatch_callback, self.thread())
        self._complete_future(future, error=error)
        return future

    @staticmethod
    def _complete_future(future: Future, *, result: Any = None,
                         error: Exception | None = None) -> None:
        try:
            if future.cancelled() or future.done():
                return
            if error is not None:
                future.set_exception(error)
            else:
                future.set_result(result)
        except InvalidStateError:
            return

    def _begin_send_pgn(self, operation_id: str, future: Future, pgn: int, data: bytes,
                        source: int, destination: int, owner: str) -> None:
        if future.cancelled():
            return
        operation = _PluginOperation(future, owner, "send")
        self._operations[operation_id] = operation
        self._listen_for_operations()
        try:
            can_send_vm = getattr(self._host, "can_send_vm", None)
            if can_send_vm is None:
                raise RuntimeError("CAN Send is unavailable")
            if len(data) <= 8:
                self._dispatch_plugin_frame(operation_id, build_single_frame(pgn, data, source, destination))
            else:
                operation.transport_key = (source, destination if destination != 0xFF else 0xFF)
                operation.queued_payload = (pgn, data, source, destination)
                self._transport_queues[operation.transport_key].append(operation_id)
                self._start_next_transport(operation.transport_key)
        except Exception as exc:
            self._finish_operation(operation_id, error=exc)

    def _start_next_transport(self, key: tuple[int, int]) -> None:
        if key in self._active_transports:
            return
        queue = self._transport_queues.get(key)
        if not queue:
            return
        operation_id = queue[0]
        operation = self._operations.get(operation_id)
        if operation is None:
            queue.popleft()
            self._start_next_transport(key)
            return
        if operation.session is None:
            # The payload is attached before queueing in _begin_send_pgn.
            pgn, data, source, destination = operation.queued_payload
            operation.session = J1939TransmitSession(pgn, data, source, destination,
                                                       now=time.monotonic(),
                                                       timeouts=J1939TransmitTimeouts())
            self._active_transports[key] = operation_id
            frame = operation.session.start()
            self._dispatch_plugin_frame(operation_id, frame,
                                        frame_kind=operation.session.frame_kind(frame))

    def _dispatch_session_result(self, operation_id: str, frames: list[Any]) -> None:
        operation = self._operations.get(operation_id)
        if operation is None or operation.session is None:
            return
        if frames:
            frame = frames[0]
            self._dispatch_plugin_frame(operation_id, frame,
                                        frame_kind=operation.session.frame_kind(frame))
        elif operation.session.state == "complete":
            self._finish_operation(operation_id, result=tuple(operation.entry_ids))
        elif operation.session.state == "failed":
            self._finish_operation(operation_id, error=operation.session.error or RuntimeError("J1939 transmit failed"))
        else:
            self._arm_session_timer(operation_id)

    def _dispatch_plugin_frame(self, operation_id: str, frame: Any,
                                *, frame_kind: str | None = None) -> None:
        operation = self._operations.get(operation_id)
        can_send_vm = getattr(self._host, "can_send_vm", None)
        if operation is None or can_send_vm is None:
            self._finish_operation(operation_id, error=RuntimeError("CAN Send is unavailable"))
            return
        entry_id = f"plugin:{uuid.uuid4().hex}"
        operation.entry_ids.append(entry_id)
        if frame_kind is not None:
            operation.entry_frame_kinds[entry_id] = frame_kind
        self._entry_to_operation[entry_id] = operation_id
        try:
            can_send_vm.send_plugin_frame(frame.can_id, frame.data, extended=True, entry_id=entry_id)
        except TypeError:
            self._entry_to_operation.pop(entry_id, None)
            returned_id = can_send_vm.send_plugin_frame(frame.can_id, frame.data, extended=True)
            operation.entry_ids[-1] = returned_id
            if frame_kind is not None:
                operation.entry_frame_kinds.pop(entry_id, None)
                operation.entry_frame_kinds[returned_id] = frame_kind
            self._entry_to_operation[returned_id] = operation_id
            if hasattr(can_send_vm, "tx_log"):
                record = next((item for item in reversed(can_send_vm.tx_log()) if item.entry_id == returned_id), None)
                if record is not None:
                    self._on_plugin_send_finished(returned_id, record.success, record.message)

    @Slot(str, bool, str)
    def _on_plugin_send_finished(self, entry_id: str, success: bool, message: str) -> None:
        operation_id = self._entry_to_operation.pop(entry_id, None)
        operation = self._operations.get(operation_id or "")
        if operation is None:
            return
        if operation.kind == "wait":
            if entry_id not in operation.control_entry_ids:
                return
            operation.control_entry_ids.discard(entry_id)
            if not success:
                self._finish_operation(operation_id, error=RuntimeError(message or "CAN send failed"))
            elif operation.pending_response is not None and not operation.control_entry_ids:
                self._finish_operation(operation_id, result=operation.pending_response)
            return
        if operation.session is None:
            if success:
                self._finish_operation(operation_id, result=tuple(operation.entry_ids))
            else:
                self._finish_operation(operation_id, error=RuntimeError(message or "CAN send failed"))
            return
        frame_kind = operation.entry_frame_kinds.pop(entry_id, None)
        frames = operation.session.on_send_result(success, now=time.monotonic(), error=message,
                                                  frame_kind=frame_kind)
        if operation.cancel_requested and success:
            if operation.session.state == "complete":
                self._finish_operation(operation_id, error=RuntimeError("Plugin operation canceled"))
                return
            if operation.session.state == "failed":
                self._finish_operation(operation_id, error=RuntimeError("Plugin operation canceled"))
                return
            if operation.session.destination != 0xFF:
                operation.session.error = RuntimeError("Plugin operation canceled")
                frames = operation.session._begin_abort(reason=2)
            else:
                operation.session.state = "failed"
                operation.session._deadline = None
                operation.session._next_due = None
                self._finish_operation(operation_id, error=RuntimeError("Plugin operation canceled"))
                return
        self._dispatch_session_result(operation_id, frames)

    def _arm_session_timer(self, operation_id: str) -> None:
        operation = self._operations.get(operation_id)
        if operation is None or operation.session is None:
            return
        deadlines = [d for d in (operation.session._deadline, operation.session._next_due) if d is not None]
        if not deadlines:
            return
        if operation.timer is None:
            operation.timer = QTimer(self)
            operation.timer.setSingleShot(True)
            operation.timer.timeout.connect(lambda op_id=operation_id: self._advance_session(op_id))
        operation.timer.start(max(1, int((min(deadlines) - time.monotonic()) * 1000)))

    def _advance_session(self, operation_id: str) -> None:
        operation = self._operations.get(operation_id)
        if operation is None or operation.session is None:
            return
        frame_list = operation.session.tick(now=time.monotonic())
        self._dispatch_session_result(operation_id, frame_list or [])

    def _finish_operation(self, operation_id: str, *, result: Any = None,
                          error: Exception | None = None) -> None:
        operation = self._operations.pop(operation_id, None)
        if operation is None:
            return
        if operation.timer is not None:
            operation.timer.stop()
            operation.timer.deleteLater()
        if operation.receiver_timer is not None:
            operation.receiver_timer.stop()
            operation.receiver_timer.deleteLater()
        for entry_id, op_id in tuple(self._entry_to_operation.items()):
            if op_id == operation_id:
                self._entry_to_operation.pop(entry_id, None)
        transport_key = operation.transport_key
        start_next = False
        if transport_key is not None:
            queue = self._transport_queues.get(transport_key)
            if queue is not None:
                was_head = bool(queue and queue[0] == operation_id)
                try:
                    queue.remove(operation_id)
                except ValueError:
                    pass
                if not queue:
                    self._transport_queues.pop(transport_key, None)
                elif was_head and transport_key not in self._active_transports:
                    start_next = True
            if self._active_transports.get(transport_key) == operation_id:
                self._active_transports.pop(transport_key, None)
                start_next = True
        self._stop_listening_if_idle()
        self._complete_future(operation.future, result=result, error=error)
        if start_next:
            self._start_next_transport(transport_key)

    def _cancel_operation(self, operation_id: str) -> None:
        operation = self._operations.get(operation_id)
        if operation is None:
            return
        if operation.kind == "wait" and operation.commanded_receiver is not None:
            abort = operation.commanded_receiver.cancel(reason=2)
            if abort is not None:
                self._dispatch_wait_control(operation_id, abort)
            self._finish_operation(operation_id, error=RuntimeError("Plugin operation canceled"))
            return
        if operation.session is not None and operation.session._awaiting in {"announce", "dt", "abort"}:
            operation.cancel_requested = True
            return
        if operation.session is not None and operation.session.destination != 0xFF:
            if operation.session.state in {"send_announce", "wait_cts", "send_window", "wait_eom", "hold_cts"}:
                operation.session.error = RuntimeError("Plugin operation canceled")
                abort = operation.session._begin_abort(reason=2)
            else:
                abort = []
            if abort:
                self._dispatch_plugin_frame(
                    operation_id, abort[0],
                    frame_kind=operation.session.frame_kind(abort[0]),
                )
                return
        self._finish_operation(operation_id, error=RuntimeError("Plugin operation canceled"))

    @Slot(object)
    def _record_transport_frames(self, chunk: pl.DataFrame) -> None:
        if not {"TS", "ID", "DATA"}.issubset(chunk.columns):
            return
        rows = list(chunk.select(["TS", "ID", "DATA"]).iter_rows())
        latest_ts = max((float(row[0]) for row in rows if row[0] is not None), default=0.0)
        chunk_monotonic = time.monotonic()
        for ts, raw_id, data_hex in rows:
            try:
                can_id = int(str(raw_id), 16)
                data = bytes.fromhex(str(data_hex))
                identifier = J1939.decode_identifier(can_id)
                if identifier is None:
                    continue
                delta = max(0.0, latest_ts - float(ts)) if ts is not None else 0.0
                received_at = chunk_monotonic - min(delta, 3600.0)
                messages = self._transport_receiver.ingest(received_at, can_id, data)
                for operation_id, operation in tuple(self._operations.items()):
                    if operation.kind == "wait":
                        response = None
                        if identifier.pgn == operation.wait_pgn and (
                            operation.wait_sa is None or identifier.source_address == operation.wait_sa
                        ):
                            response = J1939Response(float(ts), identifier.source_address,
                                                     identifier.destination_address, data)
                        if response is None:
                            for message in messages:
                                if message.pgn == operation.wait_pgn and (
                                    operation.wait_sa is None or message.source_address == operation.wait_sa
                                ):
                                    response = J1939Response(float(ts), message.source_address,
                                                             message.destination_address, message.data)
                                    break
                        if response is None and operation.commanded_receiver is not None:
                            frame, message = operation.commanded_receiver.receive(received_at, can_id, data)
                            if message is not None:
                                operation.pending_response = J1939Response(
                                    message.timestamp, message.source_address,
                                    message.destination_address, message.data,
                                )
                            if frame is not None:
                                self._dispatch_wait_control(operation_id, frame)
                                if frame[1][0] == 0xFF:
                                    self._finish_operation(
                                        operation_id,
                                        error=TimeoutError("J1939 CMDT response timed out")
                                        if frame[1][1] == 3 else RuntimeError("J1939 CMDT response was aborted"),
                                    )
                                    continue
                            self._arm_receiver_timer(operation_id)
                            if message is not None and frame is None:
                                response = operation.pending_response
                        if response is not None:
                            self._finish_operation(operation_id, result=response)
                    elif operation.session is not None:
                        try:
                            frames = operation.session.receive(can_id, data, now=received_at)
                        except J1939AbortError as exc:
                            self._finish_operation(operation_id, error=exc)
                            continue
                        self._dispatch_session_result(operation_id, frames)
            except (TypeError, ValueError):
                continue

    def wait_for(self, pgn: int, sa: int | None, timeout: float, *,
                 local_source_address: int | None = None, _owner: str = "") -> Future[J1939Response]:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive")
        if not 0 <= int(pgn) <= 0x3FFFF:
            raise ValueError("PGN is out of range")
        if sa is not None and not 0 <= int(sa) <= 0xFF:
            raise ValueError("Source address is out of range")
        if local_source_address is not None and not 0 <= int(local_source_address) <= 0xFF:
            raise ValueError("Local source address is out of range")
        if self._closed:
            return self._failed_future(RuntimeError("Plugin context is shut down"))
        if QCoreApplication.instance() is None:
            return self._failed_future(RuntimeError("GUI event loop is unavailable"))
        if timeout > 3600.0 or int(timeout * 1000) > 2_147_483_647:
            raise ValueError("timeout cannot exceed one hour")
        future: Future[J1939Response] = _GuiFuture(self._dispatch_callback, self.thread())
        operation_id = uuid.uuid4().hex
        future.add_done_callback(
            lambda done, op_id=operation_id: self._cancel_requested.emit(op_id) if done.cancelled() else None
        )
        called_at = time.monotonic()
        try:
            self._call_gui(lambda: self._begin_wait_for(
                operation_id, future, int(pgn), sa, called_at + timeout, _owner,
                None if local_source_address is None else int(local_source_address),
            ))
        except Exception as exc:
            self._complete_future(future, error=exc)
        return future

    def _begin_wait_for(self, operation_id: str, future: Future, pgn: int, sa: int | None,
                        deadline: float, owner: str, local_source_address: int | None) -> None:
        if future.cancelled():
            return
        if getattr(self._host, "connection_vm", None) is None:
            future.set_exception(RuntimeError("CAN receive stream is unavailable"))
            return
        operation = _PluginOperation(future, owner, "wait")
        operation.wait_pgn = pgn
        operation.wait_sa = sa
        operation.deadline = deadline
        if local_source_address is not None and sa is not None:
            operation.commanded_receiver = J1939CommandedReceiver(
                pgn, local_source_address, sa,
                t1=J1939TransmitTimeouts().t1, t2=J1939TransmitTimeouts().t2,
            )
        operation.timer = QTimer(self)
        operation.timer.setSingleShot(True)
        operation.timer.timeout.connect(lambda op_id=operation_id: self._expire_wait(op_id))
        try:
            self._operations[operation_id] = operation
            self._listen_for_operations()
            remaining_ms = min(3_600_000, max(1, int((deadline - time.monotonic()) * 1000)))
            operation.timer.start(remaining_ms)
        except Exception as exc:
            self._finish_operation(operation_id, error=exc)

    def _expire_wait(self, operation_id: str) -> None:
        operation = self._operations.get(operation_id)
        if operation is not None and operation.commanded_receiver is not None:
            abort = operation.commanded_receiver.cancel(reason=3)
            if abort is not None:
                self._dispatch_wait_control(operation_id, abort)
        self._finish_operation(operation_id, error=TimeoutError("Timed out waiting for J1939 response"))

    def _dispatch_wait_control(self, operation_id: str, frame: tuple[int, bytes]) -> None:
        operation = self._operations.get(operation_id)
        can_send_vm = getattr(self._host, "can_send_vm", None)
        if operation is None or can_send_vm is None:
            self._finish_operation(operation_id, error=RuntimeError("CAN Send is unavailable"))
            return
        entry_id = f"plugin:{uuid.uuid4().hex}"
        operation.control_entry_ids.add(entry_id)
        self._entry_to_operation[entry_id] = operation_id
        try:
            can_send_vm.send_plugin_frame(frame[0], frame[1], extended=True, entry_id=entry_id)
        except Exception as exc:
            operation.control_entry_ids.discard(entry_id)
            self._entry_to_operation.pop(entry_id, None)
            self._finish_operation(operation_id, error=exc)

    def _arm_receiver_timer(self, operation_id: str) -> None:
        operation = self._operations.get(operation_id)
        receiver = operation.commanded_receiver if operation is not None else None
        if operation is None or receiver is None or receiver.deadline is None:
            return
        if operation.receiver_timer is None:
            operation.receiver_timer = QTimer(self)
            operation.receiver_timer.setSingleShot(True)
            operation.receiver_timer.timeout.connect(lambda op_id=operation_id: self._receiver_timeout(op_id))
        operation.receiver_timer.start(min(2_147_483_647,
                                           max(1, int((receiver.deadline - time.monotonic()) * 1000))))

    def _receiver_timeout(self, operation_id: str) -> None:
        operation = self._operations.get(operation_id)
        if operation is None or operation.commanded_receiver is None:
            return
        abort = operation.commanded_receiver.tick(time.monotonic())
        if abort is not None:
            self._dispatch_wait_control(operation_id, abort)
            self._finish_operation(operation_id, error=TimeoutError("J1939 CMDT response timed out"))
        else:
            self._arm_receiver_timer(operation_id)

    def request_pgn(self, pgn: int, *, source_address: int, destination_address: int = 255) -> str:
        frame = build_single_frame(0xEA00, int(pgn).to_bytes(3, "little"), source_address, destination_address)
        return self.send_frame(frame.can_id, frame.data, extended=True)

    def scoped(self, plugin_id: str) -> _PluginContextScope:
        return _PluginContextScope(self, plugin_id)

    def unsubscribe_owner(self, plugin_id: str) -> None:
        for operation_id, operation in tuple(self._operations.items()):
            if operation.owner == plugin_id:
                operation.future.cancel()
                self._cancel_operation(operation_id)
        for unsubscribe in tuple(self._subscriptions.get(plugin_id, ())):
            unsubscribe()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        for operation_id, operation in tuple(self._operations.items()):
            operation.future.cancel()
            self._cancel_operation(operation_id)
        self._stop_listening_if_idle()

    def subscribe_live_chunks(
        self,
        callback: Callable[[pl.DataFrame], None],
        *,
        lifetime: QObject,
        plugin_id: str = "",
    ) -> Callable[[], None]:
        connection_vm = getattr(self._host, "connection_vm", None)
        if not callable(callback) or lifetime is None or not hasattr(lifetime, "destroyed"):
            raise ValueError("A chunk subscription needs a callback and a QWidget lifetime")
        if connection_vm is None:
            raise RuntimeError("CAN live stream is unavailable")

        bridge = _PluginChunkBridge(callback, plugin_id, self._host)
        connection = connection_vm.chunk_ready
        connection.connect(bridge.receive)
        active = True

        def unsubscribe(*_args: object) -> None:
            nonlocal active
            if not active:
                return
            active = False
            try:
                connection.disconnect(bridge.receive)
            except (RuntimeError, TypeError):
                pass
            bridge.deleteLater()
            subscriptions = self._subscriptions.get(plugin_id, [])
            if unsubscribe in subscriptions:
                subscriptions.remove(unsubscribe)

        self._subscriptions.setdefault(plugin_id, []).append(unsubscribe)
        lifetime.destroyed.connect(unsubscribe)
        return unsubscribe

class _PluginContextScope:
    def __init__(self, context: _PluginContext, plugin_id: str) -> None:
        self._context = context
        self._plugin_id = plugin_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._context, name)

    def send_pgn(self, pgn: int, data: bytes, *, source_address: int,
                 destination_address: int = 255) -> Future:
        return self._context.send_pgn(pgn, data, source_address=source_address,
                                      destination_address=destination_address, _owner=self._plugin_id)

    def wait_for(self, pgn: int, sa: int | None, timeout: float, *,
                 local_source_address: int | None = None) -> Future[J1939Response]:
        return self._context.wait_for(pgn, sa, timeout, local_source_address=local_source_address,
                                      _owner=self._plugin_id)

    def subscribe_live_chunks(
        self, callback: Callable[[pl.DataFrame], None], *, lifetime: QObject
    ) -> Callable[[], None]:
        return self._context.subscribe_live_chunks(callback, lifetime=lifetime, plugin_id=self._plugin_id)


class PluginViewModel(QObject):
    plugins_changed = QtSignal(object)

    def __init__(self, host: Any, parent: QObject | None = None):
        super().__init__(parent)
        self._host = host
        self._context = _PluginContext(host)
        self._manager = PluginManager(host.session_state.root / "plugins.json")
        self._chunk_connections: dict[str, list[tuple[Any, Any]]] = {}

    def refresh(self) -> tuple[PluginRecord, ...]:
        records = self._manager.discover()
        for record in records:
            if record.enabled and not record.loaded:
                self._manager.set_enabled(record.id, True, self._context.scoped(record.id))
        self._connect_live_listeners()
        records = self._manager.records()
        self._sync_analysis_actions()
        self.plugins_changed.emit(records)
        return records

    def set_enabled(self, plugin_id: str, enabled: bool) -> tuple[PluginRecord, ...]:
        if not enabled:
            self._disconnect_plugin(plugin_id)
            self._context.unsubscribe_owner(plugin_id)
        self._manager.set_enabled(plugin_id, enabled, self._context.scoped(plugin_id) if enabled else None)
        if enabled:
            self._connect_live_listeners(plugin_id)
        records = self._manager.records()
        self._sync_analysis_actions()
        self.plugins_changed.emit(records)
        return records

    def import_plugin(self, source: str | Path) -> PluginRecord:
        source_path = Path(source).expanduser()
        record = (
            self._manager.import_archive(source_path)
            if source_path.suffix.lower() == ".zip"
            else self._manager.import_folder(source_path)
        )
        self.refresh()
        return record

    def plugin_directories(self) -> tuple[Path, ...]:
        return self._manager.plugin_dirs

    def ui_extensions(self, kind: str) -> dict[str, tuple[str, Any]]:
        return self._manager.ui_extensions(kind)

    @property
    def context(self) -> _PluginContext:
        return self._context

    def context_for_plugin(self, plugin_id: str) -> _PluginContextScope:
        return self._context.scoped(plugin_id)

    def _sync_analysis_actions(self) -> None:
        self._host.analysis_context_vm.set_marker_provider(self._context.list_session_markers)
        send_to = {
            f"{self._display_extension_name(name)} [{owner}]": self._guarded(callback, owner, name)
            for name, (owner, callback) in self._manager.ui_extensions("send_to_actions").items()
        }
        contextual = {
            f"{self._display_extension_name(name)} [{owner}]": self._guarded(callback, owner, name)
            for name, (owner, callback) in self._manager.ui_extensions("context_actions").items()
        }
        self._host.analysis_context_vm.set_plugin_actions(send_to, contextual)

    @staticmethod
    def _display_extension_name(name: str) -> str:
        return name.split(":", 1)[1].replace("_", " ").strip().title()

    @staticmethod
    def _guarded(
        callback: Callable[[AnalysisContext], None], owner: str, name: str
    ) -> Callable[[AnalysisContext], None]:
        def invoke(context: AnalysisContext) -> None:
            try:
                callback(context)
            except Exception:
                logger.exception("Plugin %s action %s failed", owner, name)
        return invoke

    def _connect_live_listeners(self, plugin_id: str | None = None) -> None:
        connected = {id(callback) for slots in self._chunk_connections.values() for callback, _ in slots}
        for owner, callback in self._manager.live_chunk_listeners():
            if (plugin_id is not None and owner != plugin_id) or id(callback) in connected:
                continue

            def deliver(chunk, *, listener=callback, owner_id=owner):
                try:
                    listener(chunk.clone())
                except Exception:
                    logger.exception("Plugin %s live chunk listener failed", owner_id)

            bridge = _PluginChunkBridge(callback, owner, self)
            self._host.connection_vm.chunk_ready.connect(bridge.receive)
            self._chunk_connections.setdefault(owner, []).append((callback, bridge))
            connected.add(id(callback))

    def _disconnect_plugin(self, plugin_id: str) -> None:
        for _callback, bridge in self._chunk_connections.pop(plugin_id, []):
            try:
                self._host.connection_vm.chunk_ready.disconnect(bridge.receive)
            except (RuntimeError, TypeError):
                pass
            bridge.deleteLater()

    def shutdown(self) -> None:
        for plugin_id in tuple(self._chunk_connections):
            self._disconnect_plugin(plugin_id)
        for plugin_id in tuple(self._context._subscriptions):
            self._context.unsubscribe_owner(plugin_id)
        self._context.shutdown()
        self._manager.shutdown()
        self._host.analysis_context_vm.set_plugin_actions({}, {})
        self._host.analysis_context_vm.set_marker_provider(None)
