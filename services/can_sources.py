from __future__ import annotations

import sys
import time
import re
from collections import deque
from pathlib import Path
from typing import Any, Callable

from services.can_data_parser import StreamCanParser, load_can_dataframe
from services.can_send import ResolvedFrame, build_cansend_command
from services.can_source import CanSource, SourceFrame
from services.kvaser_config import (
    _build_kvaser_bus_kwargs,
    _is_kvaser_backend,
    _patch_kvaser_linux_local_txecho,
    _validate_kvaser_channel_available,
)


class SourceCanceled(RuntimeError):
    """A connection attempt was canceled before it completed."""


def parse_candump_error_line(line: str) -> SourceFrame | None:
    """Parse Linux candump error records without treating them as data frames."""
    import re

    text = (line or "").strip()
    match = re.match(r"^\(?([\d.]+)\)?\s+(\S+)\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)", text)
    if match and (int(match.group(3), 16) & 0x20000000 or "ERRORFRAME" in text.upper()):
        return SourceFrame(int(match.group(3), 16) & 0x1FFFFFFF,
                           bytes.fromhex(match.group(4)[:16 - (len(match.group(4)[:16]) % 2)]), float(match.group(1)),
                           match.group(2), is_error=True,
                           error_type="errorframe" if "ERRORFRAME" in text.upper() else "candump_error_flag")
    if "ERRORFRAME" in text.upper():
        match = re.match(r"^\(([\d.]+)\)\s+(\S+)\s+([0-9A-Fa-f]+)\s+\[(\d+)\]\s*((?:[0-9A-Fa-f]{2}\s*){0,8})\s*ERRORFRAME\s*$", text)
        if match:
            payload_text = re.sub(r"\s+", "", match.group(5))
            payload_text = payload_text[:len(payload_text) - (len(payload_text) % 2)]
            return SourceFrame(int(match.group(3), 16), bytes.fromhex(payload_text), float(match.group(1)),
                               match.group(2), is_error=True, error_type="errorframe")
        simple = re.match(r"^\(([\d.]+)\)\s+(\S+)\s+ERRORFRAME\s*$", text)
        if simple:
            return SourceFrame(0, b"", float(simple.group(1)), simple.group(2), is_error=True, error_type="errorframe")
    return None


class SshCanSource:
    _IDLE_PING_SECONDS = 5.0

    def __init__(self, config: dict[str, Any], *, clock: Callable[[], float] = time.monotonic):
        self._config = config
        self._clock = clock
        self._connection = None
        self._channel = None
        self._parser: StreamCanParser | None = None
        self._buffer = b""
        self._frames: deque[SourceFrame] = deque()
        self._canceled: Callable[[], bool] = lambda: False
        self._last_activity = 0.0
        self._finished = False
        self.bitrate: int | None = None

    @property
    def finished(self) -> bool:
        return self._finished

    def open(self, *, canceled: Callable[[], bool], status: Callable[[str], None]) -> None:
        from services.remote_connection import RemoteConnection, SshAuth

        self._canceled = canceled
        self._finished = False
        if canceled():
            raise SourceCanceled()
        status("Connecting via SSH...")
        auth = SshAuth(
            username=self._config["username"],
            key_file=self._config.get("key_file"),
            key_passphrase=self._config.get("key_passphrase"),
        )
        self._connection = RemoteConnection(self._config["host"], auth)
        self._connection.open(cancel_check=canceled)
        if canceled():
            raise SourceCanceled()
        command = f"candump -e -ta {self._config['iface']},0:0,#FFFFFFFF"
        status(f"Streaming: {command}")
        self._channel = self._connection.exec_stream(command)
        self._parser = StreamCanParser(normalize_time=False, format_hint="candump")
        self._last_activity = self._clock()

    def receive(self, timeout: float) -> SourceFrame | None:
        deadline = self._clock() + max(0.0, timeout)
        while not self._canceled():
            if self._frames:
                return self._frames.popleft()
            if self._channel is None or self._channel.closed:
                self._finished = True
                return None
            if self._channel.exit_status_ready():
                raise ConnectionError("Remote command exited (interface down?)")
            try:
                if self._channel.recv_ready():
                    data = self._channel.recv(4096)
                    if data == b"":
                        raise ConnectionError("SSH session closed by remote host")
                    self._buffer += data
                    self._last_activity = self._clock()
                    self._parse_buffer()
                    if self._frames:
                        return self._frames.popleft()
                    continue
            except ConnectionError:
                raise
            except Exception:
                pass
            now = self._clock()
            if now - self._last_activity >= self._IDLE_PING_SECONDS:
                if self._connection is None or not self._connection.ping():
                    raise ConnectionError("SSH connection lost (no response)")
                self._last_activity = now
            if now >= deadline:
                return None
            time.sleep(min(0.01, max(0.0, deadline - now)))
        return None

    def _parse_buffer(self) -> None:
        while b"\n" in self._buffer:
            raw_line, self._buffer = self._buffer.split(b"\n", 1)
            text = raw_line.decode("utf-8", errors="ignore")
            error = parse_candump_error_line(text)
            if error is not None:
                self._frames.append(error)
                continue
            row = self._parser.parse_line(text)
            if row:
                try:
                    can_id = int(str(row["ID"]).removeprefix("0x"), 16)
                    payload = bytes.fromhex(str(row["DATA"]))
                    timestamp = float(row["TS"])
                except (KeyError, TypeError, ValueError):
                    continue
                self._frames.append(SourceFrame(
                    can_id, payload, timestamp, str(row.get("Bus") or ""),
                    length=int(row.get("LEN", len(payload))),
                ))

    def send(self, frame: ResolvedFrame) -> None:
        if self._connection is None:
            raise RuntimeError("SSH not connected")
        command = build_cansend_command(
            self._config["iface"], frame.can_id, frame.data, frame.extended,
        )
        exit_status, _out, error = self._connection.exec_once(command)
        if exit_status != 0:
            raise RuntimeError(error.decode(errors="ignore").strip() or f"cansend exited {exit_status}")

    def close(self) -> None:
        if self._channel is not None:
            try:
                self._channel.close()
            except Exception:
                pass
        if self._connection is not None:
            try:
                self._connection.cancel()
            except Exception:
                pass
        self._channel = None
        self._connection = None
        self._finished = True


class KvaserCanSource:
    _BITRATE_PROBE_SECONDS = 3.0

    def __init__(
        self,
        config: dict[str, Any],
        *,
        can_module: Any = None,
        platform: str | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self._config = config
        self._can = can_module
        self._platform = platform if platform is not None else sys.platform
        self._monotonic = monotonic
        self._bus = None
        self._canceled: Callable[[], bool] = lambda: False
        self.bitrate: int | None = None

    @property
    def finished(self) -> bool:
        return False

    def open(self, *, canceled: Callable[[], bool], status: Callable[[str], None]) -> None:
        try:
            if self._can is None:
                import can
                self._can = can
        except ImportError as exc:
            raise RuntimeError(
                "python-can is required for Kvaser connections. Install it before using this mode."
            ) from exc
        self._canceled = canceled
        interface = str(self._config["interface"]).strip()
        channel = self._config["channel"]
        if self._platform.startswith("win") and _is_kvaser_backend(interface):
            _validate_kvaser_channel_available(self._can, channel)
        if self._platform.startswith("linux") and _is_kvaser_backend(interface):
            _patch_kvaser_linux_local_txecho(self._can)
        extra = dict(self._config.get("extra_kwargs") or {})
        candidates = list(self._config.get("bitrate_candidates") or [])
        if self._config.get("try_all_bitrates") and candidates:
            self.bitrate = self._probe_bitrates(interface, channel, extra, candidates, status)
            if self.bitrate is None:
                raise SourceCanceled()
            return
        self.bitrate = self._config.get("bitrate")
        kwargs = _build_kvaser_bus_kwargs(
            interface=interface, channel=channel, bitrate=self.bitrate, extra_kwargs=extra,
        )
        status(f"Connecting via {interface}...")
        self._bus = self._can.Bus(**kwargs)

    def _probe_bitrates(
        self,
        interface: str,
        channel: Any,
        extra: dict[str, Any],
        candidates: list[int],
        status: Callable[[str], None],
    ) -> int | None:
        for index, bitrate in enumerate(candidates, start=1):
            if self._canceled():
                return None
            status(f"Probing {bitrate} bps ({index}/{len(candidates)})...")
            kwargs = _build_kvaser_bus_kwargs(
                interface=interface, channel=channel, bitrate=bitrate, extra_kwargs=extra,
            )
            try:
                bus = self._can.Bus(**kwargs)
            except Exception:
                continue
            if self._probe_has_traffic(bus):
                self._bus = bus
                return bitrate
            try:
                bus.shutdown()
            except Exception:
                pass
        raise ConnectionError("No bitrate produced valid CAN traffic")

    def _probe_has_traffic(self, bus: Any) -> bool:
        deadline = self._monotonic() + self._BITRATE_PROBE_SECONDS
        while self._monotonic() < deadline:
            if self._canceled():
                return False
            message = bus.recv(timeout=0.2)
            if message is not None and not getattr(message, "is_error_frame", False):
                return True
        return False

    def receive(self, timeout: float) -> SourceFrame | None:
        if self._bus is None:
            return None
        message = self._bus.recv(timeout=timeout)
        if message is None:
            return None
        return SourceFrame(
            can_id=int(getattr(message, "arbitration_id", 0)),
            data=bytes(getattr(message, "data", b"")),
            timestamp=getattr(message, "timestamp", None),
            bus=str(getattr(message, "channel", None) or "kvaser"),
            is_error=bool(getattr(message, "is_error_frame", False)),
            error_type=(str(getattr(message, "error_type", "kvaser_error"))
                        if bool(getattr(message, "is_error_frame", False)) else "bus"),
        )

    def send(self, frame: ResolvedFrame) -> None:
        if self._bus is None:
            raise RuntimeError("Bus not connected")
        message = self._can.Message(
            arbitration_id=frame.can_id,
            data=frame.data,
            is_extended_id=frame.extended,
            dlc=len(frame.data),
        )
        self._bus.send(message)

    def close(self) -> None:
        if self._bus is not None:
            try:
                self._bus.shutdown()
            except Exception:
                pass
        self._bus = None


class ReplayCanSource:
    def __init__(
        self,
        config: dict[str, Any],
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._config = config
        self._monotonic = monotonic
        self._sleep = sleep
        self._rows = None
        self._start_ts = 0.0
        self._previous_ts: float | None = None
        self._wall_start = 0.0
        self._speed = 1.0
        self._error_frames: deque[SourceFrame] = deque()
        self._pending_row = None
        self._canceled: Callable[[], bool] = lambda: False
        self._finished = False
        self.bitrate: int | None = None

    @property
    def finished(self) -> bool:
        return self._finished

    def open(self, *, canceled: Callable[[], bool], status: Callable[[str], None]) -> None:
        self._canceled = canceled
        path = Path(self._config["path"])
        if not path.exists():
            raise FileNotFoundError(path)
        self._speed = float(self._config.get("speed", 1.0))
        if self._speed <= 0:
            raise ValueError("Replay speed must be greater than zero.")
        status(f"Replay: {path.name}")
        self._error_frames = deque()
        dataframe = load_can_dataframe(path, normalize_time=False,
                                       on_error_frame=lambda record: self._error_frames.append(_source_frame_from_error_record(record)))
        if dataframe.is_empty():
            self._rows = iter(())
            self._finished = not self._error_frames
            return
        self._rows = iter(dataframe.iter_rows(named=True))
        self._start_ts = float(dataframe[0, "TS"])
        self._wall_start = self._monotonic()

    def receive(self, timeout: float) -> SourceFrame | None:
        rows = self._rows
        if self._finished or rows is None or self._canceled():
            return None
        try:
            row = self._pending_row if self._pending_row is not None else next(rows)
            self._pending_row = None
        except StopIteration:
            if self._error_frames:
                return self._error_frames.popleft()
            self._finished = True
            return None
        if self._error_frames and self._error_frames[0].timestamp is not None \
                and self._error_frames[0].timestamp <= float(row.get("TS") or 0.0):
            self._pending_row = row
            return self._error_frames.popleft()
        current = float(row.get("TS") or 0.0)
        if self._previous_ts is not None:
            target = self._wall_start + max(0.0, current - self._start_ts) / self._speed
            while not self._canceled():
                remaining = target - self._monotonic()
                if remaining <= 0:
                    break
                self._sleep(min(remaining, 0.05))
            if self._canceled():
                return None
        self._previous_ts = current
        return SourceFrame(
            can_id=int(str(row["ID"]).removeprefix("0x"), 16),
            data=bytes.fromhex(str(row["DATA"])),
            timestamp=current,
            bus=str(row.get("Bus") or ""),
            length=int(row.get("LEN", len(str(row["DATA"])) // 2)),
        )

    def send(self, frame: ResolvedFrame) -> None:
        raise RuntimeError("Sending is not supported in this mode")

    def close(self) -> None:
        self._finished = True
        self._rows = None
        self._pending_row = None
        self._error_frames.clear()


def _source_frame_from_error_record(record: dict) -> SourceFrame:
    payload = re.sub(r"\s+", "", str(record.get("DATA", "")))
    payload = payload[:len(payload) - len(payload) % 2]
    return SourceFrame(int(record.get("ID", 0)), bytes.fromhex(payload),
                       float(record.get("TS", 0.0)), str(record.get("Bus", "")),
                       is_error=True, error_type=str(record.get("type", "imported_error_frame")))


def create_can_source(config: dict[str, Any]) -> CanSource:
    mode = config.get("mode")
    if mode == "ssh":
        return SshCanSource(config)
    if mode == "kvaser":
        return KvaserCanSource(config)
    if mode == "replay":
        return ReplayCanSource(config)
    raise ValueError(f"Unsupported connection mode: {mode}")
