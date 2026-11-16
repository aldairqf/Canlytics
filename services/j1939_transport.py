from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import polars as pl

from utils.can_bytes import parse_hex_bytes
from utils.can_id import can_id_to_int
from config.defaults import DEFAULT_TP_TIMEOUT_SECONDS, MAX_TP_PAYLOAD_BYTES, MAX_TP_SESSIONS
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
