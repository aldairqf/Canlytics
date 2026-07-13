from __future__ import annotations

# 29-bit extended frames only; a lower id can't be a real J1939 PDU.
STANDARD_ID_MAX = 0x7FF


class J1939:
    """J1939 protocol math -- single source of truth for the whole app."""

    @staticmethod
    def extract_pgn(frame_id: int) -> int | None:
        frame_id = int(frame_id) & 0x1FFFFFFF
        if frame_id <= STANDARD_ID_MAX:
            return None

        dp = (frame_id >> 24) & 0x01
        pf = (frame_id >> 16) & 0xFF
        ps = (frame_id >> 8) & 0xFF

        if pf < 0xF0:
            return (dp << 16) | (pf << 8)
        return (dp << 16) | (pf << 8) | ps

    @staticmethod
    def pgn_to_frame_id(pgn: int, *, priority: int = 6, source_address: int = 0x00) -> int:
        """Inverse of :meth:`extract_pgn` -- build a 29-bit id carrying *pgn*."""
        pgn = int(pgn) & 0x3FFFF
        priority = int(priority) & 0x07
        source_address = int(source_address) & 0xFF
        dp = (pgn >> 16) & 0x01
        pf = (pgn >> 8) & 0xFF
        ps = pgn & 0xFF
        return (priority << 26) | (dp << 24) | (pf << 16) | (ps << 8) | source_address

    @staticmethod
    def format_pgn(pgn: int | None) -> str | None:
        if pgn is None:
            return None
        return f"0x{int(pgn):04X}"

    @staticmethod
    def is_pdu1(pgn: int | None) -> bool | None:
        if pgn is None:
            return None
        return ((pgn >> 8) & 0xFF) < 0xF0

    @staticmethod
    def parse_bam_announce(payload: bytes) -> int | None:
        """Target PGN of a TP.CM_BAM announce frame, or None if it isn't one."""
        if len(payload) < 8 or payload[0] != 0x20:
            return None
        return payload[5] | (payload[6] << 8) | (payload[7] << 16)
