"""Pure helpers to discover available J1939 PGNs from a CAN log DataFrame.

Used by DecodeTab to populate the PGN dropdown instead of asking the user
to type a PGN manually.
"""

from __future__ import annotations

import polars as pl

from utils.can_bytes import parse_hex_bytes
from utils.can_id import can_id_to_int


def _pgn_from_29bit(cid: int) -> int:
    dp = (cid >> 24) & 0x01
    pf = (cid >> 16) & 0xFF
    ps = (cid >> 8) & 0xFF
    if pf < 240:
        return (dp << 16) | (pf << 8)
    return (dp << 16) | (pf << 8) | ps


def available_j1939_pgns(df: pl.DataFrame) -> list[int]:
    """Return sorted unique J1939 PGNs derived from every CAN ID in *df*."""
    if df is None or df.is_empty() or "ID" not in df.columns:
        return []
    pgns: set[int] = set()
    for raw_id in df["ID"].unique().to_list():
        try:
            pgns.add(_pgn_from_29bit(can_id_to_int(raw_id)))
        except ValueError:
            continue
    return sorted(pgns)


def available_bam_pgns(df: pl.DataFrame) -> list[int]:
    """Return sorted unique PGNs announced via J1939 BAM TP.CM frames in *df*.

    Scans for frames where PF == 0xEC (BAM Connection Management) and
    extracts the target PGN from payload bytes 5-7.
    """
    if df is None or df.is_empty() or "ID" not in df.columns or "DATA" not in df.columns:
        return []
    pgns: set[int] = set()
    for raw_id, data_hex in df.select(["ID", "DATA"]).iter_rows():
        try:
            frame_id = can_id_to_int(raw_id)
        except ValueError:
            continue
        if (frame_id >> 16) & 0xFF != 0xEC:
            continue
        try:
            payload = parse_hex_bytes(data_hex)
        except Exception:
            continue
        if len(payload) < 8 or payload[0] != 0x20:
            continue
        pgns.add(payload[5] | (payload[6] << 8) | (payload[7] << 16))
    return sorted(pgns)
