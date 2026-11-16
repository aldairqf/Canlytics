from __future__ import annotations

from PySide6.QtCore import QObject, Signal as QtSignal

from collections import deque

import polars as pl
from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from config.app_config import get_option
from config.defaults import MAX_DIAGNOSTIC_MESSAGES
from services.error_diagnostics import ErrorFrameCounter
from services.protocol_observer import IsoTpObserver, classify_diagnostic_payload
from viewmodels.diagnostics_history_worker import DiagnosticsHistoryWorker


class DiagnosticsViewModel(QObject):
    changed = QtSignal(object, object)
    message_observed = QtSignal(object)
    history_loaded = QtSignal(object)
    history_scan_started = QtSignal(int)
    history_scan_progress = QtSignal(int, int)
    history_scan_finished = QtSignal(bool)
    history_scan_failed = QtSignal(str)
    tx_requested = QtSignal(str)

    def __init__(self, connection_vm, can_send_vm, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._connection_vm = connection_vm
        self._can_send_vm = can_send_vm
        self._counter = ErrorFrameCounter(float(get_option("diagnostics_error_window_seconds", 60.0)))
        self._observer = IsoTpObserver(float(get_option("diagnostics_isotp_timeout_seconds", 1.0)))
        self._messages = deque(maxlen=max(1, int(get_option("diagnostics_message_limit", MAX_DIAGNOSTIC_MESSAGES))))
        self._history_dataframe: pl.DataFrame | None = None
        self._history_generation = 0
        self._scan_generation = -1
        self._scan_thread: QThread | None = None
        self._scan_worker: DiagnosticsHistoryWorker | None = None
        self._scan_pending = False
        self._live_pending = deque(maxlen=max(1, int(get_option("diagnostics_message_limit", MAX_DIAGNOSTIC_MESSAGES))))
        self._transport_errors = 0
        self._application_errors = 0
        connection_vm.error_frame_received.connect(self.ingest_error_frame)
        connection_vm.transport_error.connect(self.ingest_transport_error)
        connection_vm.application_error.connect(self.ingest_application_error)
        connection_vm.running_changed.connect(self._on_running_changed)
        can_send_vm.tx_log_appended.connect(self._on_tx_log)

    @property
    def snapshot(self):
        return self._counter.snapshot()

    @property
    def messages(self) -> list[dict]:
        return list(self._messages)

    @property
    def transport_errors(self) -> int:
        return self._transport_errors

    @property
    def application_errors(self) -> int:
        return self._application_errors

    def ingest_error_frame(self, frame) -> None:
        if bool(getattr(self._connection_vm, "is_replay", False)):
            snapshot = self._counter.record(frame.error_type, frame.timestamp, frame.can_id, frame.data)
        else:
            snapshot = self._counter.ingest((frame,))
        self.changed.emit(snapshot, self._transport_errors)

    def ingest_error_record(self, record: dict) -> None:
        from services.can_source import SourceFrame
        payload = str(record.get("DATA", "")).replace(" ", "")
        payload = payload[:len(payload) - len(payload) % 2]
        frame = SourceFrame(int(record.get("ID", 0)), bytes.fromhex(payload),
                            float(record.get("TS", 0.0)), str(record.get("Bus", "")),
                            is_error=True, error_type=str(record.get("type", "imported_error_frame")))
        self.changed.emit(self._counter.record(frame.error_type, frame.timestamp, frame.can_id, frame.data),
                          self._transport_errors)

    def ingest_transport_error(self, _message: str) -> None:
        self._transport_errors += 1
        self.changed.emit(self._counter.snapshot(), self._transport_errors)

    def ingest_application_error(self, _message: str) -> None:
        self._application_errors += 1
        self.changed.emit(self._counter.snapshot(), self._transport_errors)

    def _on_running_changed(self, running: bool) -> None:
        if running:
            self.reset_for_source()
            self.changed.emit(self._counter.snapshot(), self._transport_errors)

    def reset_observer(self) -> None:
        self._observer = IsoTpObserver(float(get_option("diagnostics_isotp_timeout_seconds", 1.0)))

    def reset_for_source(self) -> None:
        self._history_generation += 1
        self._history_dataframe = None
        self._scan_pending = False
        self._live_pending.clear()
        if self._scan_worker is not None:
            self.history_scan_finished.emit(False)
            self._scan_worker.cancel()
        self._counter.reset()
        self._transport_errors = 0
        self._application_errors = 0
        self.reset_observer()
        self._messages.clear()
        self.history_loaded.emit([])

    def replace_dataframe(self, dataframe: pl.DataFrame | None) -> None:
        if dataframe is self._history_dataframe:
            return
        self._history_dataframe = dataframe
        self._history_generation += 1
        self.reset_observer()
        self._messages.clear()
        self._live_pending.clear()
        self.history_loaded.emit([])
        if self._scan_thread is not None:
            self._scan_pending = True
            if self._scan_worker is not None:
                self.history_scan_finished.emit(False)
                self._scan_worker.cancel()
            return
        self._start_history_scan()

    def ensure_loaded_dataframe(self, dataframe: pl.DataFrame | None) -> None:
        if dataframe is not None and dataframe is not self._history_dataframe:
            self.replace_dataframe(dataframe)

    def cancel_history_scan(self) -> None:
        if self._scan_worker is not None:
            self._scan_worker.cancel()

    def _start_history_scan(self) -> None:
        dataframe = self._history_dataframe
        if dataframe is None or dataframe.is_empty():
            self.history_loaded.emit([])
            self.history_scan_finished.emit(True)
            return
        self._scan_generation = self._history_generation
        self._scan_pending = False
        self._scan_thread = QThread(self)
        self._scan_worker = DiagnosticsHistoryWorker(
            dataframe,
            float(get_option("diagnostics_isotp_timeout_seconds", 1.0)),
            list(get_option("diagnostics_can_ids", [])),
            int(get_option("diagnostics_history_progress_batch_size", 2000)),
        )
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.started.connect(self.history_scan_started)
        self._scan_worker.progress.connect(self.history_scan_progress)
        self._scan_worker.finished.connect(self._on_history_scan_finished)
        self._scan_worker.canceled.connect(self._on_history_scan_canceled)
        self._scan_worker.failed.connect(self._on_history_scan_failed)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.canceled.connect(self._scan_thread.quit)
        self._scan_worker.failed.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._cleanup_history_scan)
        self._scan_thread.start()

    def _on_history_scan_finished(self, messages: list[dict]) -> None:
        if self._scan_generation == self._history_generation:
            for message in messages:
                self._messages.append(message)
            for message in self._live_pending:
                self._messages.append(message)
            self._live_pending.clear()
            current = self.messages
            self.history_loaded.emit(current)
            self.history_scan_finished.emit(True)

    def _on_history_scan_canceled(self) -> None:
        if self._scan_generation == self._history_generation:
            self.history_scan_finished.emit(False)

    def _on_history_scan_failed(self, message: str) -> None:
        if self._scan_generation == self._history_generation:
            self.history_scan_failed.emit(message)
            self.history_scan_finished.emit(False)

    def _cleanup_history_scan(self) -> None:
        if self._scan_worker is not None:
            self._scan_worker.deleteLater()
        if self._scan_thread is not None:
            self._scan_thread.deleteLater()
        self._scan_worker = None
        self._scan_thread = None
        if self._scan_pending:
            self._start_history_scan()

    def shutdown(self) -> None:
        if self._scan_worker is not None:
            self._scan_worker.cancel()
        if self._scan_thread is not None and self._scan_thread.isRunning():
            self._scan_thread.quit()
            self._scan_thread.wait(2000)

    def ingest_chunk(self, chunk) -> None:
        if chunk is None or chunk.is_empty():
            return
        for row in chunk.iter_rows(named=True):
            try:
                can_id = int(str(row["ID"]), 16)
                data = bytes.fromhex(str(row["DATA"]))
                messages = self._observer.ingest(can_id, data, float(row["TS"]))
            except (ValueError, TypeError, KeyError, OverflowError):
                continue
            for message in messages:
                item = classify_diagnostic_payload(message.can_id, message.payload)
                if item is None:
                    continue
                if self._scan_thread is not None:
                    self._live_pending.append(item)
                else:
                    self._messages.append(item)
                self.message_observed.emit(item)
        self._observer.expire(float(chunk[-1, "TS"]))

    def request_j1939_pgn(self, pgn: int, source_address: int | None = None) -> str:
        if not 0 <= int(pgn) <= 0x3FFFF:
            raise ValueError("PGN must fit in 18 bits")
        payload = bytes((int(pgn) & 0xFF, (int(pgn) >> 8) & 0xFF, (int(pgn) >> 16) & 0x03))
        source = int(get_option("j1939_request_source_address", 0xF9) if source_address is None else source_address)
        can_id = (6 << 26) | (0xEA << 16) | (0xFF << 8) | (source & 0xFF)
        return self._can_send_vm.send_plugin_frame(can_id, payload, extended=True)

    def request_obd_pid(self, pid: int, mode: int = 1) -> str:
        if not 0 <= int(pid) <= 0xFF or not 1 <= int(mode) <= 0x3F:
            raise ValueError("OBD mode/PID is out of range")
        payload = bytes((2, int(mode), int(pid), 0, 0, 0, 0, 0))
        return self._can_send_vm.send_plugin_frame(0x7DF, payload, extended=False)

    def _on_tx_log(self, record) -> None:
        self.tx_requested.emit(record.entry_id)
