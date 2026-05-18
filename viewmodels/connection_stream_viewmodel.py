from __future__ import annotations

import ast
import sys
import time
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from services.can_data_parser import StreamCanParser, frame_dict, load_can_dataframe, rows_to_df
from services.remote_connection import RemoteConnection, SshAuth, SshCanceled


class _ConnectionStreamWorker(QObject):
    status = QtSignal(str)
    error = QtSignal(str)
    chunk_ready = QtSignal(object)
    finished = QtSignal()

    def __init__(self, config: dict[str, Any], parent: QObject | None = None):
        super().__init__(parent)
        self._config = config
        self._stop = False
        self._conn: Optional[RemoteConnection] = None
        self._channel = None
        self._bus = None
        self._reader = None
        self._start_ts: float | None = None

    def stop(self) -> None:
        self._stop = True
        try:
            if self._reader:
                self._reader.stop()
        except Exception:
            pass
        try:
            if self._bus:
                self._bus.shutdown()
        except Exception:
            pass
        try:
            if self._conn:
                self._conn.cancel()
        except Exception:
            pass
        try:
            if self._channel:
                self._channel.close()
        except Exception:
            pass

    def run(self) -> None:
        try:
            mode = self._config.get("mode")
            if mode == "ssh":
                self._run_ssh()
            elif mode == "kvaser":
                self._run_kvaser()
            elif mode == "replay":
                self._run_replay()
            else:
                raise ValueError(f"Unsupported connection mode: {mode}")
        except SshCanceled:
            self.status.emit("Stopped")
        except Exception as exc:
            if self._stop:
                self.status.emit("Stopped")
            else:
                self.error.emit(str(exc))
        finally:
            self._cleanup()
            self.finished.emit()

    def _run_ssh(self) -> None:
        self.status.emit("Connecting via SSH...")
        auth = SshAuth(
            username=self._config["username"],
            key_file=self._config.get("key_file"),
            key_passphrase=self._config.get("key_passphrase"),
        )
        self._conn = RemoteConnection(self._config["host"], auth)
        self._conn.open(cancel_check=lambda: self._stop)

        if self._stop:
            self.status.emit("Stopped")
            return

        cmd = f"candump -ta {self._config['iface']}"
        self.status.emit(f"Streaming: {cmd}")
        self._channel = self._conn.exec_stream(cmd)

        parser = StreamCanParser(normalize_time=bool(self._config.get("normalize")), format_hint="candump")
        self._stream_lines(parser)
        self.status.emit("Stopped")

    def _stream_lines(self, parser: StreamCanParser) -> None:
        buf = b""
        rows: list[dict] = []
        last_flush = time.monotonic()
        batch_size = 200
        flush_interval = 0.05

        while not self._stop:
            if self._channel is None or self._channel.closed:
                break

            got_data = False
            try:
                if self._channel.recv_ready():
                    data = self._channel.recv(4096)
                    if data:
                        buf += data
                        got_data = True
            except Exception:
                pass

            while b"\n" in buf:
                raw_line, buf = buf.split(b"\n", 1)
                row = parser.parse_line(raw_line.decode("utf-8", errors="ignore"))
                if row:
                    rows.append(row)

            last_flush = self._flush_rows(rows, last_flush, batch_size, flush_interval)

            if not got_data:
                time.sleep(0.01)

        if rows:
            self.chunk_ready.emit(rows_to_df(rows))

    def _run_kvaser(self) -> None:
        try:
            import can
        except ImportError as exc:
            raise RuntimeError(
                "python-can is required for Kvaser connections. Install it before using this mode."
            ) from exc

        interface = str(self._config["interface"]).strip()
        channel_value = self._config["channel"]

        if sys.platform.startswith("win") and _is_kvaser_backend(interface):
            _validate_kvaser_channel_available(can, channel_value)

        if sys.platform.startswith("linux") and _is_kvaser_backend(interface):
            _patch_kvaser_linux_local_txecho(can)

        bitrate = self._config.get("bitrate")
        extra_kwargs = dict(self._config.get("extra_kwargs") or {})
        bus_kwargs = _build_kvaser_bus_kwargs(
            interface=interface,
            channel=channel_value,
            bitrate=bitrate,
            extra_kwargs=extra_kwargs,
        )

        self.status.emit(f"Connecting via {interface}...")
        self._bus = can.Bus(**bus_kwargs)
        reader_timeout = float(self._config.get("poll_timeout", 0.1))
        self._reader = self._bus

        label = f"{interface}:{channel_value}" if channel_value != "" else interface
        self.status.emit(f"Streaming: {label}")

        rows: list[dict] = []
        last_flush = time.monotonic()
        batch_size = 200
        flush_interval = 0.05
        normalize = bool(self._config.get("normalize"))
        self._start_ts = None

        while not self._stop:
            msg = self._reader.recv(timeout=reader_timeout)
            if msg is None:
                last_flush = self._flush_rows(rows, last_flush, batch_size, flush_interval)
                continue

            row = self._message_to_row(msg, normalize=normalize)
            if row:
                rows.append(row)

            last_flush = self._flush_rows(rows, last_flush, batch_size, flush_interval)

        if rows:
            self.chunk_ready.emit(rows_to_df(rows))

        self.status.emit("Stopped")

    def _run_replay(self) -> None:
        path = Path(self._config["path"])
        if not path.exists():
            raise FileNotFoundError(path)

        speed = float(self._config.get("speed", 1.0))
        if speed <= 0:
            raise ValueError("Replay speed must be greater than zero.")

        self.status.emit(f"Replay: {path.name}")
        df = load_can_dataframe(path, normalize_time=False)
        if df.is_empty():
            self.status.emit("Stopped")
            return

        rows = df.iter_rows(named=True)
        previous_ts: float | None = None
        batch: list[dict] = []
        batch_size = 200
        flush_interval = 0.05
        last_flush = time.monotonic()
        start_ts = float(df[0, "TS"])
        ts_offset = float(self._config.get("ts_offset", 0.0))
        wall_start = time.monotonic()

        for row in rows:
            if self._stop:
                break

            current_ts = float(row.get("TS") or 0.0)
            if previous_ts is not None:
                replay_elapsed = max(0.0, current_ts - start_ts) / speed
                target_wall = wall_start + replay_elapsed
                wait = target_wall - time.monotonic()
                if wait > 0:
                    self._sleep_interruptible(wait)
                    if self._stop:
                        break
            previous_ts = current_ts

            replay_row = dict(row)
            replay_row["TS"] = round(ts_offset + current_ts - start_ts, 6)
            batch.append(replay_row)
            last_flush = self._flush_rows(batch, last_flush, batch_size, flush_interval)

        if batch:
            self.chunk_ready.emit(rows_to_df(batch))

        self.status.emit("Stopped")

    def _message_to_row(self, msg, *, normalize: bool) -> dict | None:
        if getattr(msg, "is_error_frame", False):
            return None

        ts = time.time()
        if normalize:
            if self._start_ts is None:
                self._start_ts = ts
            ts = round(ts - self._start_ts, 6)

        channel = getattr(msg, "channel", None)
        if channel is None or channel == "":
            bus = "kvaser"
        else:
            bus = str(channel)

        return frame_dict(
            ts=ts,
            bus=bus,
            can_id=int(getattr(msg, "arbitration_id", 0)),
            data=bytes(getattr(msg, "data", b"")),
        )

    def _flush_rows(
        self,
        rows: list[dict],
        last_flush: float,
        batch_size: int,
        flush_interval: float,
    ) -> float:
        now = time.monotonic()
        if rows and (len(rows) >= batch_size or (now - last_flush) >= flush_interval):
            self.chunk_ready.emit(rows_to_df(rows))
            rows.clear()
            return now
        return last_flush

    def _cleanup(self) -> None:
        try:
            if self._reader and self._reader is not self._bus:
                self._reader.stop()
        except Exception:
            pass
        self._reader = None

        try:
            if self._bus:
                self._bus.shutdown()
        except Exception:
            pass
        self._bus = None

        try:
            if self._channel:
                self._channel.close()
        except Exception:
            pass
        self._channel = None

        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass
        self._conn = None

    def _sleep_interruptible(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while not self._stop:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.05))


class ConnectionStreamViewModel(QObject):
    running_changed = QtSignal(bool)
    status_changed = QtSignal(str)
    error = QtSignal(str)
    chunk_ready = QtSignal(object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._worker: Optional[_ConnectionStreamWorker] = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start_ssh(
        self,
        *,
        host: str,
        username: str,
        key_file: str | None,
        key_passphrase: str | None,
        iface: str,
        normalize: bool,
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
            }
        )

    def start_kvaser(
        self,
        *,
        interface: str,
        channel: str | int | None,
        bitrate: int | None,
        normalize: bool,
        extra_kwargs_text: str = "",
    ) -> None:
        self._start_worker(
            {
                "mode": "kvaser",
                "interface": interface,
                "channel": _coerce_scalar(channel),
                "bitrate": bitrate,
                "normalize": normalize,
                "extra_kwargs": parse_kvaser_kwargs(extra_kwargs_text),
                "poll_timeout": 0.1,
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

    def shutdown(self) -> None:
        self.stop()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)

    def _start_worker(self, config: dict[str, Any]) -> None:
        if self._thread and self._thread.isRunning():
            return

        self._worker = _ConnectionStreamWorker(config)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.status.connect(self.status_changed.emit)
        self._worker.error.connect(self.error.emit)
        self._worker.chunk_ready.connect(self.chunk_ready.emit)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup)

        self._running = True
        self.running_changed.emit(True)
        self._thread.start()

    def _cleanup(self) -> None:
        self._running = False
        self.running_changed.emit(False)
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        if self._thread:
            self._thread.deleteLater()
            self._thread = None


def parse_kvaser_kwargs(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}

    result: dict[str, Any] = {}
    for chunk in text.split(","):
        part = chunk.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"Invalid extra parameter '{part}'. Use key=value format.")
        key, value = part.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("Extra parameter keys cannot be empty.")
        result[key] = _coerce_scalar(value.strip())
    return result


def _patch_kvaser_linux_local_txecho(can_module) -> None:
    try:
        from can.interfaces.kvaser import canlib
    except Exception:
        return

    if getattr(canlib, "_cananalyzer_linux_txecho_patch", False):
        return

    original_can_ioctl_init = canlib.canIoCtlInit
    original_can_set_acceptance_filter = canlib.canSetAcceptanceFilter
    local_txecho = canlib.canstat.canIOCTL_SET_LOCAL_TXECHO
    local_txack = canlib.canstat.canIOCTL_SET_LOCAL_TXACK

    def can_ioctl_init_linux(handle, func, buf, buflen):
        try:
            return original_can_ioctl_init(handle, func, buf, buflen)
        except canlib.CanError as exc:
            error_code = getattr(exc, "error_code", None)
            # Linux Kvaser driver may reject local TX echo setup even when RX works.
            if func in {local_txecho, local_txack} and (
                error_code == -1 or "Error Code -1" in str(exc)
            ):
                return 0
            raise

    def can_set_acceptance_filter_linux(handle, code, mask, extended):
        try:
            return original_can_set_acceptance_filter(handle, code, mask, extended)
        except canlib.CanError as exc:
            error_code = getattr(exc, "error_code", None)
            # Some Linux Kvaser backends do not implement hardware acceptance filters.
            if error_code == -32 or "Error Code -32" in str(exc):
                return 0
            raise

    canlib.canIoCtlInit = can_ioctl_init_linux
    canlib.canSetAcceptanceFilter = can_set_acceptance_filter_linux
    canlib._cananalyzer_linux_txecho_patch = True


def _build_kvaser_bus_kwargs(
    *,
    interface: str,
    channel: Any,
    bitrate: int | None,
    extra_kwargs: dict[str, Any],
) -> dict[str, Any]:
    bus_kwargs: dict[str, Any] = {"interface": interface}
    if channel != "":
        bus_kwargs["channel"] = channel
    if bitrate is not None:
        bus_kwargs["bitrate"] = bitrate
    bus_kwargs.update(extra_kwargs)
    return bus_kwargs


def _is_kvaser_backend(interface: str) -> bool:
    return interface.strip().lower() == "kvaser"


def _coerce_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value

    text = str(value).strip()
    if text == "":
        return ""

    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "none":
        return None

    try:
        return ast.literal_eval(text)
    except Exception:
        return text


def _validate_kvaser_channel_available(can_module, channel: Any) -> None:
    try:
        available = can_module.detect_available_configs(interfaces=["kvaser"])
    except Exception:
        # If detection is unavailable, keep python-can default behavior.
        return

    if not available:
        raise RuntimeError("No Kvaser device detected on this system.")

    physical_available = [cfg for cfg in available if not _is_virtual_kvaser_config(cfg)]
    if not physical_available:
        raise RuntimeError("No physical Kvaser device detected (only virtual channels are available).")

    normalized_channel = str(channel).strip() if channel is not None else ""
    if normalized_channel == "":
        return

    available_channels = {
        str(cfg.get("channel")).strip()
        for cfg in physical_available
        if cfg.get("channel") is not None and str(cfg.get("channel")).strip() != ""
    }

    if available_channels and normalized_channel not in available_channels:
        listed = ", ".join(sorted(available_channels))
        raise RuntimeError(
            f"Kvaser channel '{normalized_channel}' is not available. Detected channels: {listed}."
        )


def _is_virtual_kvaser_config(cfg: Any) -> bool:
    device_name = str(cfg.get("device_name", "")).strip().lower()
    serial = cfg.get("serial", None)
    return "virtual" in device_name or serial in {0, "0"}
