"""Pure helpers to discover available J1939 PGNs from a CAN log DataFrame.

Used by DecodeTab to populate the PGN dropdown instead of asking the user
to type a PGN manually.
"""

from __future__ import annotations

import polars as pl

from utils.can_bytes import parse_hex_bytes
from utils.can_id import can_id_to_int
from utils.j1939 import J1939


def available_j1939_pgns(df: pl.DataFrame) -> list[int]:
    """Return sorted unique J1939 PGNs derived from every CAN ID in *df*."""
    if df is None or df.is_empty() or "ID" not in df.columns:
        return []
    pgns: set[int] = set()
    for raw_id in df["ID"].unique().to_list():
        try:
            pgn = J1939.extract_pgn(can_id_to_int(raw_id))
        except ValueError:
            continue
        if pgn is not None:
            pgns.add(pgn)
    return sorted(pgns)


def available_bam_pgns(df: pl.DataFrame) -> list[int]:
    """Return sorted unique PGNs announced via J1939 BAM TP.CM frames in *df*."""
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
        pgn = J1939.parse_bam_announce(payload)
        if pgn is not None:
            pgns.add(pgn)
    return sorted(pgns)
