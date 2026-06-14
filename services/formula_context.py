from __future__ import annotations

import math
import struct
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from services.bam_reassembly import BamMessage, assemble_bam_messages
from services.signal_aligner import align as _align_impl
from utils.can_bytes import parse_hex_bytes
from utils.can_id import can_id_to_int

if TYPE_CHECKING:
    pass


# dtype string → struct format (little-endian / big-endian)
_DTYPE_FMT: dict[str, str] = {
    "uint8":    "B",  "int8":    "b",
    "uint16le": "<H", "int16le": "<h",
    "uint16be": ">H", "int16be": ">h",
    "uint32le": "<I", "int32le": "<i",
    "uint32be": ">I", "int32be": ">i",
    "uint64le": "<Q", "int64le": "<q",
    "uint64be": ">Q", "int64be": ">q",
    "float32le": "<f", "float32be": ">f",
    "float64le": "<d", "float64be": ">d",
}


def _dtype_nbytes(dtype: str) -> int:
    fmt = _DTYPE_FMT.get(dtype.lower())
    if fmt is None:
        raise ValueError(f"Unknown dtype {dtype!r}. Valid: {list(_DTYPE_FMT)}")
    return struct.calcsize(fmt)


def decode_bytes(data: bytes, offset: int, n: int, dtype: str) -> int | float:
    """Decode ``n`` bytes starting at ``offset`` in ``data`` using ``dtype``.

    dtype examples: 'uint8', 'int16le', 'uint32be', 'float32le'.
    """
    fmt = _DTYPE_FMT.get(dtype.lower())
    if fmt is None:
        raise ValueError(f"Unknown dtype {dtype!r}. Valid: {list(_DTYPE_FMT)}")
    required = struct.calcsize(fmt)
    if required != n:
        raise ValueError(f"dtype {dtype!r} needs {required} bytes, got n={n}")
    return struct.unpack_from(fmt, data, offset)[0]


def build_formula_context(
    df: pl.DataFrame,
    decoded: dict[str, tuple[np.ndarray, np.ndarray]],
) -> dict:
    """Return the sandbox namespace for formula evaluation.

    Parameters
    ----------
    df:
        The full raw CAN DataFrame (FRAME_SCHEMA).
    decoded:
        Already-decoded signals from the current plot, keyed by signal name.
        Each value is a ``(ts_array, y_array)`` tuple.
    """

    # ------------------------------------------------------------------ #
    # signal(name) — reference a decoded plot signal                       #
    # ------------------------------------------------------------------ #
    def _signal(name: str) -> tuple[np.ndarray, np.ndarray]:
        if name not in decoded:
            available = list(decoded.keys())
            raise KeyError(
                f"Signal {name!r} not found in this plot. Available: {available}"
            )
        return decoded[name]

    # ------------------------------------------------------------------ #
    # bam_messages(pgn, source=None) → list[BamMessage]                   #
    # ------------------------------------------------------------------ #
    def _bam_messages(
        pgn: int, source: int | None = None
    ) -> list[BamMessage]:
        return assemble_bam_messages(df, int(pgn), source_address=source)

    # ------------------------------------------------------------------ #
    # bam_extract(pgn, offset, n, dtype, source=None) → (ts, y)           #
    # ------------------------------------------------------------------ #
    def _bam_extract(
        pgn: int,
        offset: int,
        n: int,
        dtype: str = "uint8",
        source: int | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        messages = assemble_bam_messages(df, int(pgn), source_address=source)
        ts_list: list[float] = []
        y_list: list[float] = []
        for msg in messages:
            if offset + n > len(msg.data):
                continue
            val = decode_bytes(msg.data, offset, n, dtype)
            ts_list.append(msg.timestamp)
            y_list.append(float(val))
        return np.array(ts_list), np.array(y_list)

    # ------------------------------------------------------------------ #
    # raw_frames(can_id, mode='exact', pgn=None) → iterator (ts, bytes)   #
    # ------------------------------------------------------------------ #
    def _raw_frames(
        can_id: int | str,
        mode: str = "exact",
        pgn: int | None = None,
    ):
        if df is None or df.is_empty():
            return

        target_int = can_id_to_int(str(can_id)) if isinstance(can_id, (int, str)) else int(can_id)

        for ts, raw_id, data_hex in df.select(["TS", "ID", "DATA"]).iter_rows():
            if raw_id is None:
                continue
            try:
                fid = can_id_to_int(raw_id)
            except ValueError:
                continue

            match = False
            if mode == "exact":
                match = fid == target_int
            elif mode == "j1939":
                pf = (fid >> 16) & 0xFF
                ps = (fid >> 8) & 0xFF
                frame_pgn = (pf << 8) | (ps if pf >= 0xF0 else 0)
                match = frame_pgn == target_int
            elif mode == "pgn" and pgn is not None:
                pf = (fid >> 16) & 0xFF
                ps = (fid >> 8) & 0xFF
                frame_pgn = (pf << 8) | (ps if pf >= 0xF0 else 0)
                match = frame_pgn == int(pgn)

            if match:
                payload = parse_hex_bytes(data_hex)
                yield float(ts), payload

    # ------------------------------------------------------------------ #
    # raw_extract(can_id, offset, n, dtype, mode='exact') → (ts, y)       #
    # ------------------------------------------------------------------ #
    def _raw_extract(
        can_id: int | str,
        offset: int,
        n: int,
        dtype: str = "uint8",
        mode: str = "exact",
        pgn: int | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        ts_list: list[float] = []
        y_list: list[float] = []
        for ts, payload in _raw_frames(can_id, mode=mode, pgn=pgn):
            if offset + n > len(payload):
                continue
            val = decode_bytes(payload, offset, n, dtype)
            ts_list.append(ts)
            y_list.append(float(val))
        return np.array(ts_list), np.array(y_list)

    # ------------------------------------------------------------------ #
    # align(*[(ts, y), ...]) → (common_ts, [y1, y2, ...])                 #
    # ------------------------------------------------------------------ #
    def _align(*series: tuple[np.ndarray, np.ndarray]):
        return _align_impl(*series)

    return {
        "__builtins__": {},
        "np": np,
        "math": math,
        # data access helpers
        "signal": _signal,
        "bam_messages": _bam_messages,
        "bam_extract": _bam_extract,
        "raw_frames": _raw_frames,
        "raw_extract": _raw_extract,
        "decode_bytes": decode_bytes,
        "align": _align,
    }
