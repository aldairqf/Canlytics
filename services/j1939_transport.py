from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import polars as pl

from utils.can_bytes import parse_hex_bytes
from utils.can_id import can_id_to_int
from config.defaults import (
    DEFAULT_TP_CTS_WINDOW_SIZE,
    DEFAULT_TP_TIMEOUT_SECONDS,
    MAX_TP_PAYLOAD_BYTES,
    MAX_TP_SESSIONS,
)
from utils.j1939 import J1939

_TP_CM_PGN = 0xEC00
_TP_DT_PGN = 0xEB00


@dataclass(frozen=True)
class J1939TransportMessage:
    timestamp: float
    source_address: int
    destination_address: int | None
    pgn: int
    data: bytes
    protocol: str


@dataclass
class _TransportSession:
    source_address: int
    destination_address: int
    pgn: int
    total_bytes: int
    total_packets: int
    protocol: str
    timestamp: float
    data: bytearray
    received: set[int]
    cts_window: tuple[int, int] | None = None


def assemble_transport_messages(
    dataframe: pl.DataFrame,
    target_pgn: int | None = None,
    *,
    source_address: int | None = None,
    destination_address: int | None = None,
    timeout_seconds: float = DEFAULT_TP_TIMEOUT_SECONDS,
    max_sessions: int = MAX_TP_SESSIONS,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    on_message: Callable[[J1939TransportMessage], None] | None = None,
) -> list[J1939TransportMessage]:
    """Reassemble complete BAM and RTS/CTS transfers from source-order frames."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if max_sessions < 1:
        raise ValueError("max_sessions must be positive")
    if dataframe is None or dataframe.is_empty() or not {"TS", "ID", "DATA"}.issubset(dataframe.columns):
        return []
    sessions: dict[tuple[int, int], _TransportSession] = {}
    results: list[J1939TransportMessage] = []
    rows = dataframe.select(["TS", "ID", "DATA"]).iter_rows()
    total = dataframe.height
    progress_step = max(1, total // 200)
    for row_index, (timestamp, raw_id, data_hex) in enumerate(rows, start=1):
        if should_cancel is not None and should_cancel():
            return results
        if timestamp is None or raw_id is None:
            if on_progress is not None and (row_index % progress_step == 0 or row_index == total):
                on_progress(row_index, total)
            continue
        try:
            frame_id = can_id_to_int(raw_id)
        except (TypeError, ValueError):
            if on_progress is not None and (row_index % progress_step == 0 or row_index == total):
                on_progress(row_index, total)
            continue
        identifier = J1939.decode_identifier(frame_id)
        if identifier is None or identifier.pgn not in {_TP_CM_PGN, _TP_DT_PGN}:
            if on_progress is not None and (row_index % progress_step == 0 or row_index == total):
                on_progress(row_index, total)
            continue
        try:
            payload = parse_hex_bytes(data_hex)
        except (TypeError, ValueError):
            payload = b""
        current_time = float(timestamp)
        _expire_sessions(sessions, current_time, timeout_seconds)
        if identifier.pgn == _TP_CM_PGN:
            _process_connection_management(
                sessions,
                results,
                identifier.source_address,
                identifier.destination_address,
                payload,
                current_time,
                target_pgn,
                source_address,
                destination_address,
                max_sessions,
            )
        else:
            key = (identifier.source_address, 0xFF if identifier.destination_address is None else identifier.destination_address)
            session = sessions.get(key)
            if session is not None and (target_pgn is None or session.pgn == target_pgn):
                if source_address is not None and session.source_address != source_address:
                    session = None
                if destination_address is not None and session.destination_address != destination_address:
                    session = None
            if session is not None:
                _process_data_transfer(sessions, results, key, session, payload, current_time, on_message)
        if on_progress is not None and (row_index % progress_step == 0 or row_index == total):
            on_progress(row_index, total)
    return results


def _process_connection_management(
    sessions: dict[tuple[int, int], _TransportSession],
    results: list[J1939TransportMessage],
    source: int,
    destination: int | None,
    payload: bytes,
    timestamp: float,
    target_pgn: int | None,
    source_filter: int | None,
    destination_filter: int | None,
    max_sessions: int,
) -> None:
    if len(payload) < 8 or destination is None:
        return
    control = payload[0]
    pgn = payload[5] | (payload[6] << 8) | (payload[7] << 16)
    if control in (0x20, 0x10):
        key = (source, destination)
        sessions.pop(key, None)
        total_bytes = payload[1] | (payload[2] << 8)
        total_packets = payload[3]
        protocol = "BAM" if control == 0x20 else "CMDT"
        expected_packets = (total_bytes + 6) // 7 if total_bytes > 0 else 0
        if (
            total_bytes < 1
            or total_bytes > MAX_TP_PAYLOAD_BYTES
            or total_packets != expected_packets
            or target_pgn is not None and pgn != target_pgn
            or source_filter is not None and source != source_filter
            or destination_filter is not None and destination != destination_filter
            or control == 0x20 and destination != 0xFF
            or control == 0x10 and payload[4] != 0xFF and not 1 <= payload[4] <= total_packets
        ):
            return
        if len(sessions) >= max_sessions:
            oldest = min(sessions, key=lambda session_key: sessions[session_key].timestamp)
            sessions.pop(oldest, None)
        sessions[key] = _TransportSession(
            source,
            destination,
            pgn,
            total_bytes,
            total_packets,
            protocol,
            timestamp,
            bytearray(total_bytes),
            set(),
        )
        return
    if control == 0x11:  # CTS travels in the reverse direction to the original RTS.
        key = (destination, source)
        session = sessions.get(key)
        if session is None or session.protocol != "CMDT" or session.pgn != pgn:
            return
        count, next_sequence = payload[1], payload[2]
        if count == 0:
            session.cts_window = None
        elif next_sequence > 0 and next_sequence + count - 1 <= session.total_packets:
            session.cts_window = (next_sequence, next_sequence + count - 1)
        session.timestamp = timestamp
        return
    if control in (0x13, 0xFF):  # EOM ACK or Abort ends the addressed session.
        key = (destination, source)
        session = sessions.get(key)
        if session is None or session.pgn != pgn:
            session = sessions.get((source, destination))
        if session is not None and session.pgn == pgn:
            sessions.pop((session.source_address, session.destination_address), None)


def _process_data_transfer(
    sessions: dict[tuple[int, int], _TransportSession],
    results: list[J1939TransportMessage],
    key: tuple[int, int],
    session: _TransportSession,
    payload: bytes,
    timestamp: float,
    on_message: Callable[[J1939TransportMessage], None] | None,
) -> None:
    if len(payload) < 8:
        return
    sequence = payload[0]
    if not 1 <= sequence <= session.total_packets or sequence in session.received:
        return
    if session.protocol == "CMDT":
        window = session.cts_window
        if window is None or not window[0] <= sequence <= window[1]:
            return
    offset = (sequence - 1) * 7
    count = min(7, session.total_bytes - offset)
    session.data[offset:offset + count] = payload[1:1 + count]
    session.received.add(sequence)
    session.timestamp = timestamp
    if session.protocol == "CMDT" and session.cts_window is not None and sequence == session.cts_window[1]:
        session.cts_window = None
    if len(session.received) == session.total_packets:
        message = J1939TransportMessage(
            timestamp=timestamp,
            source_address=session.source_address,
            destination_address=None if session.protocol == "BAM" else session.destination_address,
            pgn=session.pgn,
            data=bytes(session.data),
            protocol=session.protocol,
        )
        if on_message is None:
            results.append(message)
        else:
            on_message(message)
        sessions.pop(key, None)


def _expire_sessions(
    sessions: dict[tuple[int, int], _TransportSession],
    current_time: float,
    timeout_seconds: float,
) -> None:
    expired = [
        key
        for key, session in sessions.items()
        if current_time >= session.timestamp and current_time - session.timestamp > timeout_seconds
    ]
    for key in expired:
        sessions.pop(key, None)


class J1939TransportReceiver:
    """Incremental Qt-free BAM and CMDT receiver for live CAN frames."""

    def __init__(self, *, timeout_seconds: float = DEFAULT_TP_TIMEOUT_SECONDS,
                 max_sessions: int = MAX_TP_SESSIONS) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0 or max_sessions < 1:
            raise ValueError("Invalid J1939 receiver limits")
        self.timeout_seconds = timeout_seconds
        self.max_sessions = max_sessions
        self._sessions: dict[tuple[int, int], _TransportSession] = {}

    def reset(self) -> None:
        self._sessions.clear()

    def ingest(self, timestamp: float, can_id: int, data: bytes) -> tuple[J1939TransportMessage, ...]:
        identifier = J1939.decode_identifier(can_id)
        if identifier is None or identifier.pgn not in {_TP_CM_PGN, _TP_DT_PGN}:
            return ()
        _expire_sessions(self._sessions, float(timestamp), self.timeout_seconds)
        results: list[J1939TransportMessage] = []
        payload = bytes(data)
        if identifier.pgn == _TP_CM_PGN:
            _process_connection_management(
                self._sessions, results, identifier.source_address, identifier.destination_address,
                payload, float(timestamp), None, None, None, self.max_sessions,
            )
        else:
            key = (identifier.source_address,
                   0xFF if identifier.destination_address is None else identifier.destination_address)
            session = self._sessions.get(key)
            if session is not None:
                _process_data_transfer(self._sessions, results, key, session, payload, float(timestamp), None)
        return tuple(results)


class J1939CommandedReceiver:
    """Active single-session CMDT receiver for a plugin wait operation."""

    def __init__(self, pgn: int, local_address: int, remote_address: int,
                 *, t1: float = 0.75, t2: float = 1.25,
                 window_size: int = DEFAULT_TP_CTS_WINDOW_SIZE) -> None:
        if not 0 <= pgn <= 0x3FFFF or not 0 <= local_address <= 0xFF or not 0 <= remote_address <= 0xFF:
            raise ValueError("Invalid J1939 CMDT receiver address or PGN")
        if t1 <= 0 or t2 <= 0 or not 1 <= window_size <= 0xFF:
            raise ValueError("Invalid J1939 CMDT receiver limits")
        self.pgn = pgn
        self.local_address = local_address
        self.remote_address = remote_address
        self.t1 = t1
        self.t2 = t2
        self.window_size = window_size
        self.peer_window_size = 0xFF
        self.window_end = 0
        self.total_bytes = 0
        self.total_packets = 0
        self.next_packet = 1
        self.data = bytearray()
        self.deadline: float | None = None
        self.active = False

    def receive(self, timestamp: float, can_id: int, data: bytes) -> tuple[tuple[int, bytes] | None,
                                                                            J1939TransportMessage | None]:
        identifier = J1939.decode_identifier(can_id)
        if identifier is None or identifier.pgn not in {_TP_CM_PGN, _TP_DT_PGN}:
            return None, None
        payload = bytes(data)
        if len(payload) < 8 or identifier.destination_address != self.local_address:
            return None, None
        if identifier.pgn == _TP_CM_PGN and payload[0] == 0x10:
            pgn = payload[5] | payload[6] << 8 | payload[7] << 16
            total_bytes = payload[1] | payload[2] << 8
            total_packets = payload[3]
            if identifier.source_address != self.remote_address or pgn != self.pgn:
                return None, None
            if (not 1 <= total_bytes <= MAX_TP_PAYLOAD_BYTES
                    or total_packets != (total_bytes + 6) // 7 or payload[4] == 0):
                self.active = False
                self.deadline = None
                return self._abort(2), None
            self.total_bytes = total_bytes
            self.total_packets = total_packets
            self.peer_window_size = payload[4]
            self.next_packet = 1
            self.data = bytearray(total_bytes)
            self.active = True
            return self._grant_window(float(timestamp)), None
        if identifier.pgn != _TP_DT_PGN or identifier.source_address != self.remote_address or not self.active:
            return None, None
        sequence = payload[0]
        if self.deadline is not None and float(timestamp) >= self.deadline:
            return self.tick(float(timestamp)), None
        if sequence != self.next_packet or sequence > self.total_packets:
            return self._abort(2), None
        offset = (sequence - 1) * 7
        count = min(7, self.total_bytes - offset)
        self.data[offset:offset + count] = payload[1:1 + count]
        self.next_packet += 1
        self.deadline = float(timestamp) + self.t1
        if sequence == self.total_packets:
            self.active = False
            self.deadline = None
            message = J1939TransportMessage(float(timestamp), self.remote_address,
                                             self.local_address, self.pgn, bytes(self.data), "CMDT")
            return self._control(0x13, self.total_bytes & 0xFF, self.total_bytes >> 8,
                                 self.total_packets), message
        if self.next_packet > self.window_end:
            return self._grant_window(float(timestamp)), None
        return None, None

    def _grant_window(self, timestamp: float) -> tuple[int, bytes]:
        remaining = self.total_packets - self.next_packet + 1
        peer_limit = self.peer_window_size if self.peer_window_size != 0xFF else remaining
        count = min(remaining, peer_limit, self.window_size)
        self.window_end = self.next_packet + count - 1
        self.deadline = timestamp + self.t2
        return self._control(0x11, count, self.next_packet)

    def tick(self, timestamp: float) -> tuple[int, bytes] | None:
        if not self.active or self.deadline is None or timestamp < self.deadline:
            return None
        self.active = False
        self.deadline = None
        return self._abort(3)

    def cancel(self, reason: int = 2) -> tuple[int, bytes] | None:
        if not self.active:
            return None
        self.active = False
        self.deadline = None
        return self._abort(reason)

    def _control(self, control: int, count: int, first: int, packets: int = 0xFF) -> tuple[int, bytes]:
        pgn = self.pgn.to_bytes(3, "little")
        data = bytes((control, count & 0xFF, first & 0xFF, packets & 0xFF, 0xFF)) + pgn
        frame_id = J1939.pgn_to_frame_id(_TP_CM_PGN | self.remote_address, priority=7,
                                          source_address=self.local_address)
        return frame_id, data

    def _abort(self, reason: int) -> tuple[int, bytes]:
        return self._control(0xFF, reason, 0xFF, 0xFF)
