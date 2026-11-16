from __future__ import annotations

from dataclasses import dataclass
import math
from collections import deque

from config.defaults import (
    DEFAULT_TP_BAM_INTER_PACKET_SECONDS,
    DEFAULT_TP_CONTROL_FRAME_TOLERANCE_SECONDS,
    DEFAULT_TP_T1_SECONDS,
    DEFAULT_TP_T2_SECONDS,
    DEFAULT_TP_T3_SECONDS,
    DEFAULT_TP_T4_SECONDS,
    MAX_TP_PAYLOAD_BYTES,
)
from utils.j1939 import J1939

TP_CM_PGN = 0xEC00
TP_DT_PGN = 0xEB00
GLOBAL_ADDRESS = 0xFF


@dataclass(frozen=True)
class J1939TransmitTimeouts:
    t1: float = DEFAULT_TP_T1_SECONDS
    t2: float = DEFAULT_TP_T2_SECONDS
    t3: float = DEFAULT_TP_T3_SECONDS
    t4: float = DEFAULT_TP_T4_SECONDS
    bam_inter_packet: float = DEFAULT_TP_BAM_INTER_PACKET_SECONDS
    control_frame_tolerance: float = DEFAULT_TP_CONTROL_FRAME_TOLERANCE_SECONDS

    def __post_init__(self) -> None:
        if any(not math.isfinite(value) or value <= 0 for value in (
            self.t1, self.t2, self.t3, self.t4, self.bam_inter_packet
        )):
            raise ValueError("J1939 transport timeouts must be positive and finite")
        if (not math.isfinite(self.control_frame_tolerance)
                or self.control_frame_tolerance < 0 or self.control_frame_tolerance > 0.05):
            raise ValueError("J1939 control-frame timestamp tolerance must be between 0 and 50 ms")
        if not 0.05 <= self.bam_inter_packet <= 0.2:
            raise ValueError("BAM inter-packet delay must be between 50 and 200 ms")


class J1939AbortError(RuntimeError):
    def __init__(self, reason: int):
        self.reason = int(reason)
        super().__init__(f"J1939 connection aborted (reason {self.reason})")


class J1939TransmitSession:
    """Qt-free BAM and RTS/CTS sender advanced by injected frames and a clock."""

    def __init__(
        self,
        pgn: int,
        data: bytes,
        source: int,
        destination: int = GLOBAL_ADDRESS,
        *,
        now: float,
        timeouts: J1939TransmitTimeouts | None = None,
    ) -> None:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("J1939 payload must be bytes-like")
        self.pgn = int(pgn)
        self.data = bytes(data)
        self.source = int(source)
        self.destination = int(destination)
        self._started_at = float(now)
        self.timeouts = timeouts or J1939TransmitTimeouts()
        self._control_valid_after = float(now) - self.timeouts.control_frame_tolerance
        self._frames = build_transport_frames(self.pgn, self.data, self.source, self.destination)
        self._next_packet = 1
        self._window: deque[int] = deque()
        self._awaiting: str | None = None
        self._deadline: float | None = None
        self._next_due: float | None = None
        self.state = "new"
        self.error: Exception | None = None

    def start(self) -> J1939TransmitFrame:
        if self.state != "new":
            raise RuntimeError("J1939 transmit session already started")
        self.state = "send_announce"
        self._awaiting = "announce"
        return self._frames[0]

    def on_send_result(self, success: bool, *, now: float, error: str = "",
                       frame_kind: str | None = None) -> list[J1939TransmitFrame]:
        kind = frame_kind or self._awaiting
        if kind == "abort":
            self.state = "failed"
            self._awaiting = None
            self._deadline = None
            self._next_due = None
            return []
        if self.state == "send_abort" and kind in {"announce", "dt"}:
            return []
        if self.state in {"failed", "complete"}:
            return []
        if not success:
            self.error = RuntimeError(error or "CAN send failed")
            if self.destination != GLOBAL_ADDRESS:
                return self._begin_abort(reason=2)
            self.state = "failed"
            self._deadline = None
            self._next_due = None
            return []
        self._awaiting = None
        if kind == "announce":
            if self.destination == GLOBAL_ADDRESS:
                self._next_due = None
                self.state = "bam_delay"
                self._next_due = now + self.timeouts.bam_inter_packet
            else:
                self.state = "wait_cts"
                self._deadline = now + self.timeouts.t3
        elif kind == "dt":
            if self.destination == GLOBAL_ADDRESS:
                if self._next_packet > len(self._frames) - 1:
                    self.state = "complete"
                else:
                    self.state = "bam_delay"
                    self._next_due = now + self.timeouts.bam_inter_packet
            elif self._window:
                self._awaiting = "dt"
                return [self._data_frame(self._window.popleft())]
            elif self._next_packet > len(self._frames) - 1:
                self.state = "wait_eom"
                self._deadline = now + self.timeouts.t3
            else:
                self.state = "wait_cts"
                self._deadline = now + self.timeouts.t3
        return []

    def receive(self, can_id: int, data: bytes, *, now: float) -> list[J1939TransmitFrame]:
        active_states = {"wait_cts", "hold_cts", "wait_eom", "send_window"}
        if (now < self._control_valid_after or self.state not in active_states or len(data) < 8):
            return []
        identifier = J1939.decode_identifier(can_id)
        if identifier is None or identifier.pgn != TP_CM_PGN:
            return []
        if identifier.source_address != self.destination or identifier.destination_address != self.source:
            return []
        control = data[0]
        if _message_pgn(data) != self.pgn:
            return []
        if control == 0xFF:
            self.error = J1939AbortError(data[1])
            self.state = "failed"
            self._deadline = None
            self._next_due = None
            raise self.error
        if control == 0x13 and self.state == "wait_eom":
            self.state = "complete"
            self._deadline = None
            self._next_due = None
            return []
        if control == 0x11 and self.state == "send_window":
            self.error = RuntimeError("Unexpected CTS received during an active transmit window")
            return self._begin_abort(reason=4)
        if control != 0x11 or self.state not in {"wait_cts", "hold_cts"}:
            return []
        count, first = data[1], data[2]
        if count == 0:
            self._window.clear()
            self._deadline = None
            self.state = "hold_cts"
            self._deadline = now + self.timeouts.t4
            return []
        if first < 1 or first > len(self._frames) - 1 or count > 0xFF:
            return []
        self._deadline = None
        self._next_due = None
        self._window.clear()
        end = min(len(self._frames) - 1, first + count - 1)
        self._window.extend(range(first + 1, end + 1))
        self._next_packet = end + 1
        self.state = "send_window"
        self._awaiting = "dt"
        return [self._data_frame(first)]

    def tick(self, *, now: float) -> list[J1939TransmitFrame] | None:
        if self.state in {"failed", "complete"}:
            return None
        if self._deadline is not None and now >= self._deadline:
            if self.error is None:
                self.error = TimeoutError(f"J1939 transport timeout in {self.state}")
            if self.destination != GLOBAL_ADDRESS:
                return self._begin_abort(reason=3)
            self.state = "failed"
            return None
        if self.state == "bam_delay" and self._next_due is not None and now >= self._next_due:
            self._next_due = None
            frame = self._data_frame(self._next_packet)
            self._next_packet += 1
            self._awaiting = "dt"
            self.state = "send_bam_dt"
            return [frame]
        return None

    def _begin_abort(self, *, reason: int) -> list[J1939TransmitFrame]:
        self._deadline = None
        self._next_due = None
        self._window.clear()
        self.state = "send_abort"
        self._awaiting = "abort"
        return [self._abort_frame(reason=reason)]

    def _data_frame(self, sequence: int) -> J1939TransmitFrame:
        return self._frames[sequence]

    @staticmethod
    def frame_kind(frame: J1939TransmitFrame) -> str:
        identifier = J1939.decode_identifier(frame.can_id)
        if identifier is not None and identifier.pgn == TP_DT_PGN:
            return "dt"
        if frame.data and frame.data[0] == 0xFF:
            return "abort"
        return "announce"

    def _abort_frame(self, *, reason: int) -> J1939TransmitFrame:
        pgn_bytes = self.pgn.to_bytes(3, "little")
        payload = bytes((0xFF, reason, 0xFF, 0xFF, 0xFF)) + pgn_bytes
        return J1939TransmitFrame(_id(TP_CM_PGN, self.source, self.destination, 7), payload)


def _message_pgn(data: bytes) -> int:
    return data[5] | (data[6] << 8) | (data[7] << 16)


@dataclass(frozen=True)
class J1939TransmitFrame:
    can_id: int
    data: bytes


def build_single_frame(pgn: int, data: bytes, source: int, destination: int = GLOBAL_ADDRESS,
                       priority: int = 6) -> J1939TransmitFrame:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("J1939 payload must be bytes-like")
    if len(data) > 8:
        raise ValueError("Single-frame PGN payload cannot exceed 8 bytes")
    return J1939TransmitFrame(_id(pgn, source, destination, priority), bytes(data))


def build_transport_frames(pgn: int, data: bytes, source: int, destination: int = GLOBAL_ADDRESS,
                           priority: int = 6) -> tuple[J1939TransmitFrame, ...]:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("J1939 payload must be bytes-like")
    payload = bytes(data)
    if not payload or len(payload) > min(MAX_TP_PAYLOAD_BYTES, 255 * 7):
        raise ValueError("J1939 transport payload size is invalid")
    packets = (len(payload) + 6) // 7
    pgn_bytes = bytes((pgn & 0xFF, (pgn >> 8) & 0xFF, (pgn >> 16) & 0x03))
    frames: list[J1939TransmitFrame] = []
    if destination == GLOBAL_ADDRESS:
        cm = bytes((0x20, len(payload) & 0xFF, len(payload) >> 8, packets, 0xFF)) + pgn_bytes
        frames.append(J1939TransmitFrame(_id(TP_CM_PGN, source, GLOBAL_ADDRESS, 7), cm))
    else:
        cm = bytes((0x10, len(payload) & 0xFF, len(payload) >> 8, packets, 0xFF)) + pgn_bytes
        frames.append(J1939TransmitFrame(_id(TP_CM_PGN, source, destination, 7), cm))
    for seq in range(packets):
        chunk = payload[seq * 7:(seq + 1) * 7]
        dt = bytes((seq + 1,)) + chunk.ljust(7, b"\xff")
        frames.append(J1939TransmitFrame(_id(TP_DT_PGN, source, destination, 7), dt))
    return tuple(frames)


def _id(pgn: int, source: int, destination: int, priority: int) -> int:
    pgn = int(pgn)
    if not 0 <= pgn <= 0x3FFFF or not 0 <= source <= 0xFF or not 0 <= destination <= 0xFF:
        raise ValueError("Invalid J1939 PGN or address")
    if J1939.is_pdu1(pgn) and pgn & 0xFF:
        raise ValueError("PDU1 PGNs must have a zero group extension")
    frame_pgn = pgn if not J1939.is_pdu1(pgn) else pgn | destination
    return J1939.pgn_to_frame_id(frame_pgn, priority=priority, source_address=source)
