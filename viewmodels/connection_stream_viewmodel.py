from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from services.can_data_parser import StreamCanParser, frame_dict, load_can_dataframe, rows_to_df
from services.kvaser_config import (
    _build_kvaser_bus_kwargs,
    _coerce_scalar,
    _is_kvaser_backend,
    _patch_kvaser_linux_local_txecho,
    _validate_kvaser_channel_available,
    parse_kvaser_kwargs,
)
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
        self._conn: RemoteConnection | None = None
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

        ts_source = str(self._config.get("ts_source", "pc")).lower()
        cmd = f"candump -ta {self._config['iface']}"
        self.status.emit(f"Streaming: {cmd}")
        self._channel = self._conn.exec_stream(cmd)

        normalize = bool(self._config.get("normalize"))
        # When using PC timestamp, let the parser pass through device TS unchanged
        # (we replace it in _stream_lines). When using device TS, let the parser
        # apply normalize itself.
        ts_offset = float(self._config.get("ts_offset", 0.0))
        parser = StreamCanParser(
            normalize_time=(normalize and ts_source == "device"),
            format_hint="candump",
        )
        self._stream_lines(parser, ts_source=ts_source, normalize=normalize, ts_offset=ts_offset)
        self.status.emit("Stopped")

    def _stream_lines(
        self,
        parser: StreamCanParser,
        *,
        ts_source: str = "pc",
        normalize: bool = False,
        ts_offset: float = 0.0,
    ) -> None:
        buf = b""
        rows: list[dict] = []
        last_flush = time.monotonic()
        batch_size = 200
        flush_interval = 0.05
        use_pc_ts = ts_source != "device"

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
                    if use_pc_ts:
                        ts = time.time()
                        if normalize:
                            if self._start_ts is None:
                                self._start_ts = ts
                            ts = round(ts - self._start_ts, 6)
                        ts += ts_offset
                        row["TS"] = ts
                    elif ts_offset:
                        row["TS"] = round(float(row["TS"]) + ts_offset, 6)
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
        ts_source = str(self._config.get("ts_source", "pc")).lower()
        ts_offset = float(self._config.get("ts_offset", 0.0))
        self._start_ts = None

        while not self._stop:
            msg = self._reader.recv(timeout=reader_timeout)
            if msg is None:
                last_flush = self._flush_rows(rows, last_flush, batch_size, flush_interval)
                continue

            row = self._message_to_row(msg, normalize=normalize, ts_source=ts_source, ts_offset=ts_offset)
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

    def _message_to_row(self, msg, *, normalize: bool, ts_source: str = "pc", ts_offset: float = 0.0) -> dict | None:
        if getattr(msg, "is_error_frame", False):
            return None

        if ts_source == "device":
            ts = float(getattr(msg, "timestamp", None) or time.time())
        else:
            ts = time.time()
        if normalize:
            if self._start_ts is None:
                self._start_ts = ts
            ts = round(ts - self._start_ts, 6)
        ts += ts_offset

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
        self._thread: QThread | None = None
        self._worker: _ConnectionStreamWorker | None = None
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
