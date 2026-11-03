from __future__ import annotations

import json
import logging
import os
import secrets
import sys
import tempfile
import threading
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client, Listener
from pathlib import Path

import polars as pl
from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from services.mcp_session import McpSessionSnapshot

logger = logging.getLogger(__name__)
_MAX_REQUEST_BYTES = 65_536


class McpSessionViewModel(QObject):
    """Own the local session listener and maintain its Qt-free request snapshot."""

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        endpoint_path: str | Path | None = None,
        enabled: bool = True,
    ):
        super().__init__(parent)
        configured_path = endpoint_path or os.environ.get("CANLYTICS_MCP_SESSION_FILE")
        self.endpoint_path = Path(configured_path).expanduser() if configured_path else (
            Path.home() / ".canlytics" / "mcp" / "session-endpoint.json"
        )
        self.snapshot = McpSessionSnapshot()
        self._thread: QThread | None = None
        self._worker: _McpSessionIpcWorker | None = None
        if not enabled:
            return
        self._worker = _McpSessionIpcWorker(self.snapshot, self.endpoint_path)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    @property
    def ready(self) -> bool:
        return self._worker.ready_event.is_set() if self._worker is not None else False

    @property
    def thread_running(self) -> bool:
        return self._thread.isRunning() if self._thread is not None else False

    def replace_dataframe(
        self,
        dataframe: pl.DataFrame | None,
        *,
        can_ids: tuple[str, ...],
        source_paths: tuple[str, ...],
        unsaved: bool,
        connection_running: bool,
    ) -> None:
        self.snapshot.replace_dataframe(
            dataframe,
            can_ids=can_ids,
            source_paths=source_paths,
            unsaved=unsaved,
            connection_running=connection_running,
        )

    def append_rows(
        self,
        dataframe: pl.DataFrame,
        *,
        can_ids: tuple[str, ...],
        source_paths: tuple[str, ...],
        total_frames: int,
        unsaved: bool,
        connection_running: bool,
    ) -> None:
        self.snapshot.append_rows(
            dataframe,
            can_ids=can_ids,
            source_paths=source_paths,
            total_frames=total_frames,
            unsaved=unsaved,
            connection_running=connection_running,
        )

    def shutdown(self) -> None:
        if self._thread is None or self._worker is None or not self._thread.isRunning():
            return
        self._worker.request_stop()
        self._thread.quit()
        if not self._thread.wait(5000):
            raise RuntimeError("MCP session worker did not stop")


class _McpSessionIpcWorker(QObject):
    finished = QtSignal()

    def __init__(self, snapshot: McpSessionSnapshot, endpoint_path: Path):
        super().__init__()
        self._snapshot = snapshot
        self._endpoint_path = endpoint_path
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._listener_lock = threading.Lock()
        self._listener: Listener | None = None
        self._address = ""
        self._family = ""
        self._authkey = b""
        self._session_id = secrets.token_hex(16)

    @property
    def ready_event(self) -> threading.Event:
        return self._ready_event

    def run(self) -> None:
        listener = None
        try:
            self._endpoint_path.parent.mkdir(parents=True, exist_ok=True)
            if os.name != "nt":
                self._endpoint_path.parent.chmod(0o700)
            self._family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
            self._authkey = secrets.token_bytes(32)
            if self._family == "AF_PIPE":
                separator = chr(92)
                self._address = f"{separator}{separator}.{separator}pipe{separator}Canlytics-{os.getpid()}-{self._session_id}"
            else:
                self._address = str(self._endpoint_path.parent / f"s-{self._session_id[:12]}.sock")
            listener = Listener(self._address, family=self._family, authkey=self._authkey)
            with self._listener_lock:
                self._listener = listener
            if os.name != "nt":
                Path(self._address).chmod(0o600)
            self._write_descriptor()
            self._ready_event.set()
            if not self._stop_event.is_set():
                self._accept_requests(listener)
        except Exception:
            logger.exception("MCP session listener failed")
        finally:
            self._ready_event.clear()
            with self._listener_lock:
                self._listener = None
            if listener is not None:
                listener.close()
            if self._family == "AF_UNIX" and self._address:
                Path(self._address).unlink(missing_ok=True)
            self._remove_descriptor()
            self.finished.emit()

    def request_stop(self) -> None:
        self._stop_event.set()
        with self._listener_lock:
            listener = self._listener
        if listener is None:
            return
        try:
            wake_connection = Client(self._address, family=self._family, authkey=self._authkey)
            wake_connection.close()
        except (AuthenticationError, EOFError, OSError):
            listener.close()

    def _accept_requests(self, listener: Listener) -> None:
        while not self._stop_event.is_set():
            try:
                connection = listener.accept()
            except (AuthenticationError, EOFError, OSError):
                if self._stop_event.is_set():
                    break
                continue
            try:
                if self._stop_event.is_set():
                    break
                if connection.poll(2.0):
                    try:
                        request = json.loads(connection.recv_bytes(maxlength=_MAX_REQUEST_BYTES).decode("utf-8"))
                        response = _dispatch_request(self._snapshot, request)
                    except Exception as exc:
                        response = {"ok": False, "error": {"message": str(exc)}}
                    try:
                        connection.send_bytes(json.dumps(response, allow_nan=False).encode("utf-8"))
                    except (OSError, TypeError, ValueError):
                        logger.debug("MCP session response could not be sent", exc_info=True)
            finally:
                connection.close()

    def _write_descriptor(self) -> None:
        descriptor = {
            "session_id": self._session_id,
            "pid": os.getpid(),
            "address": self._address,
            "family": self._family,
            "authkey": self._authkey.hex(),
        }
        fd, temporary_name = tempfile.mkstemp(
            prefix=".session-endpoint.", suffix=".tmp", dir=self._endpoint_path.parent,
        )
        try:
            if os.name != "nt":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(descriptor, handle, allow_nan=False)
                handle.write("\n")
            os.replace(temporary_name, self._endpoint_path)
        except BaseException:
            Path(temporary_name).unlink(missing_ok=True)
            raise

    def _remove_descriptor(self) -> None:
        try:
            descriptor = json.loads(self._endpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if descriptor.get("session_id") == self._session_id:
            self._endpoint_path.unlink(missing_ok=True)


def _dispatch_request(snapshot: McpSessionSnapshot, request: object) -> dict:
    if not isinstance(request, dict) or not isinstance(request.get("method"), str):
        raise ValueError("request must include a method")
    params = request.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    method = request["method"]
    if method == "get_open_session":
        result = snapshot.get_open_session()
    elif method == "get_recent_frames":
        result = snapshot.get_recent_frames(
            limit=params.get("limit", 100),
            can_id=params.get("can_id"),
            ts_min=params.get("ts_min"),
            ts_max=params.get("ts_max"),
        )
    elif method == "get_analysis_context":
        result = {"context": snapshot.get_analysis_context()}
    elif method == "add_session_marker":
        result = {"marker": snapshot.add_session_marker(params.get("name", ""), timestamp=params.get("timestamp"))}
    elif method == "list_session_markers":
        result = {"markers": snapshot.list_session_markers()}
    else:
        raise ValueError(f"Unknown MCP session method: {method}")
    return {"ok": True, "result": result}
