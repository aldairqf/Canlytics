from __future__ import annotations

from dataclasses import dataclass

from config.app_config import get_option
from config.defaults import MAX_TP_PAYLOAD_BYTES, MAX_TP_SESSIONS


@dataclass(frozen=True)
class IsoTpMessage:
    can_id: int
    payload: bytes


class IsoTpObserver:
    """Passive classical CAN ISO-TP reassembler, updated one frame at a time."""

    def __init__(self, timeout_seconds: float = 1.0, can_ids=None) -> None:
        self.timeout_seconds = float(timeout_seconds)
        self.can_ids = set(int(value, 16) if isinstance(value, str) else int(value)
                           for value in (can_ids if can_ids is not None else get_option("diagnostics_can_ids", [])))
        self._sessions: dict[int, tuple[float, int, bytearray, int]] = {}

    @staticmethod
    def is_diagnostic_id(can_id: int) -> bool:
        return can_id == 0x7DF or 0x7E0 <= can_id <= 0x7EF or (can_id & 0x1FFF0000) == 0x18DA0000 or can_id == 0x18DB33F1

    def ingest(self, can_id: int, data: bytes, timestamp: float) -> tuple[IsoTpMessage, ...]:
        self.expire(timestamp)
        if not data or len(data) > 8 or not (self.is_diagnostic_id(can_id) or can_id in self.can_ids):
            return ()
        pci = data[0] >> 4
        if pci == 0:
            size = data[0] & 0x0F
            return (IsoTpMessage(can_id, bytes(data[1:1 + size])),) if size and size <= len(data) - 1 else ()
        if pci == 1 and len(data) >= 2:
            size = ((data[0] & 0x0F) << 8) | data[1]
            if not size or size > MAX_TP_PAYLOAD_BYTES:
                return ()
            chunk = bytearray(data[2:])
            if len(chunk) >= size:
                return (IsoTpMessage(can_id, bytes(chunk[:size])),)
            if can_id not in self._sessions and len(self._sessions) >= MAX_TP_SESSIONS:
                oldest = min(self._sessions, key=lambda key: self._sessions[key][0])
                del self._sessions[oldest]
            self._sessions[can_id] = (float(timestamp), size, chunk, 1)
        elif pci == 2:
            session = self._sessions.get(can_id)
            if session is None:
                return ()
            _started, size, payload, sequence = session
            if (data[0] & 0x0F) != sequence:
                self._sessions.pop(can_id, None)
                return ()
            payload.extend(data[1:])
            if len(payload) >= size:
                self._sessions.pop(can_id, None)
                return (IsoTpMessage(can_id, bytes(payload[:size])),)
            self._sessions[can_id] = (float(timestamp), size, payload, (sequence + 1) & 0x0F)
        # Flow control frames are intentionally observed but do not alter passive state.
        return ()

    def expire(self, timestamp: float) -> int:
        stale = [key for key, session in self._sessions.items()
                 if float(timestamp) - session[0] > self.timeout_seconds]
        for key in stale:
            del self._sessions[key]
        return len(stale)


def decode_uds(payload: bytes) -> dict[str, int | bool | str]:
    """Decode basic UDS service identity and negative response marker."""
    if not payload:
        return {"valid": False}
    if payload[0] == 0x7F and len(payload) >= 3:
        return {"valid": True, "sid": payload[1], "negative": True, "nrc": payload[2],
                "classification": "response pending" if payload[2] == 0x78 else "negative response",
                "response_pending": payload[2] == 0x78}
    sid = payload[0]
    return {"valid": True, "sid": sid, "negative": False,
            "positive": 0x40 <= sid <= 0x7E,
            "request_sid": sid - 0x40 if 0x40 <= sid <= 0x7E else 0}


def decode_obd(payload: bytes) -> dict[str, int | bool]:
    """Decode basic OBD mode and PID response identifiers."""
    if len(payload) < 2:
        return {"valid": False}
    if payload[0] == 0x7F and len(payload) >= 3:
        return {"valid": True, "mode": payload[1], "pid": 0, "negative": True, "nrc": payload[2]}
    if not (1 <= payload[0] <= 0x0A or 0x41 <= payload[0] <= 0x4A or
            (payload[0] == 0x7F and len(payload) >= 3 and 1 <= payload[1] <= 0x0A)):
        return {"valid": False}
    mode = payload[0] - 0x40 if 0x41 <= payload[0] <= 0x4A else payload[0]
    return {"valid": True, "mode": mode, "pid": payload[1], "negative": payload[0] == 0x7F}


def classify_diagnostic_payload(can_id: int, payload: bytes) -> dict | None:
    if not payload:
        return None
    uds = decode_uds(payload)
    obd_address = can_id == 0x7DF or 0x7E0 <= can_id <= 0x7EF
    obd_service = 1 <= payload[0] <= 0x0A or 0x41 <= payload[0] <= 0x4A
    if payload[0] == 0x7F and len(payload) >= 3:
        obd_service = 1 <= payload[1] <= 0x0A
    if obd_address and obd_service:
        obd = decode_obd(payload)
        return {"protocol": "OBD", "can_id": can_id, **obd, "payload": payload.hex(" ").upper()} if obd.get("valid") else None
    if not uds.get("valid"):
        return None
    return {"protocol": "UDS", "can_id": can_id, **uds, "payload": payload.hex(" ").upper()}
