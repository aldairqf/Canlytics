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
    """Return sorted unique PGNs announced via J1939 BAM TP.CM frames in *df*.

    Filters to candidate rows with a vectorized Polars expression first --
    iterating every row in Python to test one PDU-format byte was slow enough
    to freeze the UI on a real multi-million-row log for a single dropdown
    population. BAM announcements are rare, so only that small subset then
    goes through the per-row payload parse (not vectorizable, but cheap now)."""
    if df is None or df.is_empty() or "ID" not in df.columns or "DATA" not in df.columns:
        return []
    id_int = pl.col("ID").str.to_integer(base=16, strict=False)
    is_bam_cm = ((id_int // 2**16) % 256) == 0xEC
    candidates = df.filter(is_bam_cm)
    if candidates.is_empty():
        return []
    pgns: set[int] = set()
    for data_hex in candidates["DATA"].to_list():
        try:
            payload = parse_hex_bytes(data_hex)
        except Exception:
            continue
        pgn = J1939.parse_bam_announce(payload)
        if pgn is not None:
            pgns.add(pgn)
    return sorted(pgns)
