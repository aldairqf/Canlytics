from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, Qt, QThread, Signal as QtSignal

from config.app_config import get_text
from services.can_source import CanSource
from services.can_sources import SourceCanceled, create_can_source
from services.can_stream import CanStreamRunner
from services.kvaser_config import _coerce_scalar, parse_kvaser_kwargs, bitrate_probe_order


class _ConnectionStreamWorker(QObject):
    status = QtSignal(str)
    error = QtSignal(str)
    chunk_ready = QtSignal(object)
    finished = QtSignal()
    send_succeeded = QtSignal(str)
    send_failed = QtSignal(str, str)
    kvaser_bitrate_resolved = QtSignal(int)

    def __init__(self, config: dict[str, Any], parent: QObject | None = None):
        super().__init__(parent)
        self._config = config
        self._stop = False
        self._source: CanSource | None = None

    def stop(self) -> None:
        self._stop = True
        if self._source is not None:
            self._source.close()

    def send_frame(self, frame) -> None:
        """Send a queued frame through the active source on its worker thread."""
        try:
            if self._source is None:
                raise RuntimeError("CAN source not connected")
            self._source.send(frame)
        except Exception as exc:
            self.send_failed.emit(frame.entry_id, str(exc))
        else:
            self.send_succeeded.emit(frame.entry_id)

    def run(self) -> None:
        try:
            self._source = create_can_source(self._config)
            runner = CanStreamRunner(
                self._source,
                self._config,
                canceled=lambda: self._stop,
                status=self.status.emit,
                on_chunk=self.chunk_ready.emit,
                pump_events=QCoreApplication.processEvents,
                on_bitrate=self.kvaser_bitrate_resolved.emit,
            )
            runner.run()
        except SourceCanceled:
            self.status.emit("Stopped")
        except Exception as exc:
            if self._stop:
                self.status.emit("Stopped")
            else:
                self.error.emit(str(exc))
        finally:
            if self._source is not None:
                self._source.close()
                self._source = None
            self.finished.emit()


class ConnectionStreamViewModel(QObject):
    running_changed = QtSignal(bool)
    status_changed = QtSignal(str)
    error = QtSignal(str)
    chunk_ready = QtSignal(object)
    send_requested = QtSignal(object)   # ResolvedFrame, GUI thread -> worker thread (queued)
    send_succeeded = QtSignal(str)      # entry_id
    send_failed = QtSignal(str, str)    # entry_id, error message

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _ConnectionStreamWorker | None = None
        self._running = False
        self._config: dict[str, Any] | None = None
        self._last_kvaser_bitrate: int | None = None

    def request_send(self, frame) -> None:
        if not self._running or self._worker is None or self._config is None:
            self.send_failed.emit(frame.entry_id, "Not connected.")
            return
        if self._config.get("mode") == "replay":
            self.send_failed.emit(frame.entry_id, get_text("can_send_replay_unavailable"))
            return
        self.send_requested.emit(frame)

    @staticmethod
    def bitrate_probe_order(values: list[int]) -> list[int]:
        """Return the preferred bitrate probe order for connection settings."""
        return bitrate_probe_order(values)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def is_replay(self) -> bool:
        return self._running and (self._config or {}).get("mode") == "replay"

    @property
    def last_kvaser_bitrate(self) -> int | None:
        """Bitrate of the most recent Kvaser connection, for stamping saved
        logs with recording metadata (see main_window.py::_save_current_log).
        None if the current/most recent connection wasn't Kvaser, or no
        bitrate was ever resolved."""
        return self._last_kvaser_bitrate

    @property
    def capture_source_label(self) -> str:
        config = self._config or {}
        mode = str(config.get("mode") or "capture")
        if mode == "ssh":
            return f"ssh_{config.get('host', 'host')}_{config.get('iface', 'can0')}"
        if mode == "kvaser":
            return f"kvaser_{config.get('interface', 'can')}_{config.get('channel', '0')}"
        if mode == "replay":
            return f"replay_{Path(str(config.get('path') or 'log')).stem}"
        return mode

    def start_ssh(
        self,
        *,
        host: str,
        username: str,
        key_file: str | None,
        key_passphrase: str | None,
        iface: str,
        normalize: bool,
        ts_source: str = "pc",
        ts_offset: float = 0.0,
    ) -> None:
        self._start_worker(
            {
                "mode": "ssh",
                "host": host,
                "username": username,
                "key_file": key_file,
                "key_passphrase": key_passphrase,
                "iface": iface,
                "normalize": normalize,
                "ts_source": ts_source,
                "ts_offset": float(ts_offset),
            }
        )

    def start_kvaser(
        self,
        *,
        interface: str,
        channel: str | int | None,
        bitrate: int | None,
        normalize: bool,
        ts_source: str = "pc",
        ts_offset: float = 0.0,
        extra_kwargs_text: str = "",
        try_all_bitrates: bool = False,
        bitrate_candidates: list[int] | None = None,
    ) -> None:
        self._start_worker(
            {
                "mode": "kvaser",
                "interface": interface,
                "channel": _coerce_scalar(channel),
                "bitrate": bitrate,
                "normalize": normalize,
                "ts_source": ts_source,
                "ts_offset": float(ts_offset),
                "extra_kwargs": parse_kvaser_kwargs(extra_kwargs_text),
                "poll_timeout": 0.1,
                "try_all_bitrates": try_all_bitrates,
                "bitrate_candidates": list(bitrate_candidates or []),
            }
        )

    def start_replay(
        self,
        *,
        path: str,
        speed: float,
        ts_offset: float = 0.0,
    ) -> None:
        self._start_worker(
            {
                "mode": "replay",
                "path": path,
                "speed": speed,
                "ts_offset": ts_offset,
            }
        )

    def stop(self) -> None:
        if self._worker:
            self._worker.stop()

    def stop_and_drain(self) -> None:
        """Stop capture and deliver every worker chunk to the GUI thread."""
        self.stop()
        thread = self._thread
        app = QCoreApplication.instance()
        if thread is None:
            return
        while thread.isRunning():
            thread.wait(50)
            if app is not None:
                app.processEvents()
        if app is not None:
            app.processEvents()

    def shutdown(self) -> None:
        self.stop()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)

    def _start_worker(self, config: dict[str, Any]) -> None:
        if self._thread and self._thread.isRunning():
            return

        # Reset regardless of mode -- switching to SSH/replay after a prior
        # Kvaser session must not leave stale bitrate metadata attached to
        # data that no longer came from that connection.
        self._last_kvaser_bitrate = None

        self._config = config
        self._worker = _ConnectionStreamWorker(config)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.status.connect(self.status_changed.emit)
        self._worker.error.connect(self.error.emit)
        self._worker.chunk_ready.connect(self.chunk_ready.emit, Qt.ConnectionType.DirectConnection)
        self._worker.kvaser_bitrate_resolved.connect(self._on_kvaser_bitrate_resolved)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup)
        # Explicit QueuedConnection -- the one connection in this file whose
        # cross-thread delivery timing actually matters (see the worker
        # loops' processEvents() pump).
        self.send_requested.connect(self._worker.send_frame, Qt.ConnectionType.QueuedConnection)
        self._worker.send_succeeded.connect(self.send_succeeded.emit)
        self._worker.send_failed.connect(self.send_failed.emit)

        self._running = True
        self.running_changed.emit(True)
        self._thread.start()

    def _on_kvaser_bitrate_resolved(self, bitrate: int) -> None:
        self._last_kvaser_bitrate = bitrate

    def _cleanup(self) -> None:
        self._running = False
        self._config = None
        self.running_changed.emit(False)
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        if self._thread:
            self._thread.deleteLater()
            self._thread = None
