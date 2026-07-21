from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

import polars as pl


FRAME_SCHEMA = {
    "TS": pl.Float64,
    "Bus": pl.Utf8,
    "ID": pl.Utf8,
    "DATA": pl.Utf8,
    # LEN (0-8) and D0..D7 (each a raw byte, 0-255) always fit UInt8 -- 8x less
    # memory than Int64 per value (EPIC Performance y memoria, item 4). Every
    # site that widens these for arithmetic that could exceed 0-255 (DATA_INT
    # reconstruction, mux multi-byte values, byte-diff stats) already casts up
    # explicitly first -- see services/can_decoder.py, services/range_diff.py,
    # services/multi_byte_detection.py, services/mux_detector.py.
    "LEN": pl.UInt8,
    "D0": pl.UInt8,
    "D1": pl.UInt8,
    "D2": pl.UInt8,
    "D3": pl.UInt8,
    "D4": pl.UInt8,
    "D5": pl.UInt8,
    "D6": pl.UInt8,
    "D7": pl.UInt8,
}

def empty_frame() -> pl.DataFrame:
    """Empty dataframe with the full FRAME_SCHEMA (never the narrower display columns)."""
    return pl.DataFrame({key: [] for key in FRAME_SCHEMA.keys()}, schema=FRAME_SCHEMA)


FORMAT_CANDUMP = "candump"
FORMAT_KVASER_MEMORATOR = "kvaser_memorator"
_KVASER_CREATED_AT_PATTERN = r"Memorator Binary logfile created at:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"

_CANDUMP_COMPACT_PATTERN = r"^\(([\d.]+)\)\s+(\S+)\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]{0,16})\s*$"
_CANDUMP_SPACED_PATTERN = r"^\(([\d.]+)\)\s+(\S+)\s+([0-9A-Fa-f]+)\s+\[(\d+)\]\s*((?:[0-9A-Fa-f]{2}\s*){0,8})\s*$"
_KVASER_PATTERN = (
    r"^\s*([\d.]+)\s+(\d+)\s+([0-9A-Fa-f]+)x?\s+\S+\s+(\d+)\s+"
    r"((?:[0-9A-Fa-f]{2}(?:\s+|$)){0,8})"
)

_CANDUMP_COMPACT_RE = re.compile(_CANDUMP_COMPACT_PATTERN)
_CANDUMP_SPACED_RE = re.compile(_CANDUMP_SPACED_PATTERN)
_KVASER_RE = re.compile(_KVASER_PATTERN)
_KVASER_CREATED_AT_RE = re.compile(_KVASER_CREATED_AT_PATTERN)


@dataclass(frozen=True)
class LogMetadata:
    format: str
    created_at_text: str | None = None


def normalize_can_id(can_id: int | str) -> str:
    if isinstance(can_id, str):
        return can_id.strip().upper().removesuffix("X")
    return f"{int(can_id):X}"


def frame_dict(*, ts: float, bus: str, can_id: int | str, data: Sequence[int] | bytes | bytearray) -> dict:
    raw = bytes(data or b"")
    payload = raw[:8]
    data_hex = payload.hex().upper()
    padded = data_hex.ljust(16, "0")
    dcols = [int(padded[i * 2 : i * 2 + 2], 16) for i in range(8)]

    return {
        "TS": float(ts),
        "Bus": str(bus),
        "ID": normalize_can_id(can_id),
        "DATA": data_hex,
        "LEN": int(len(payload)),
        "D0": dcols[0],
        "D1": dcols[1],
        "D2": dcols[2],
        "D3": dcols[3],
        "D4": dcols[4],
        "D5": dcols[5],
        "D6": dcols[6],
        "D7": dcols[7],
    }


def rows_to_df(rows: list[dict]) -> pl.DataFrame:
    cols = {k: [] for k in FRAME_SCHEMA.keys()}
    for row in rows:
        for key in cols.keys():
            cols[key].append(row.get(key))
    return pl.DataFrame(cols, schema=FRAME_SCHEMA)


def load_can_dataframe(
    path: str | Path,
    normalize_time: bool = False,
    *,
    source_tz_offset_minutes: int | None = None,
) -> pl.DataFrame:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(source)

    metadata = inspect_log_metadata(source)
    detected = metadata.format
    if detected == FORMAT_KVASER_MEMORATOR:
        return _load_kvaser_memorator_df(
            source,
            normalize_time=normalize_time,
            start_epoch=_resolve_kvaser_start_epoch(metadata, source_tz_offset_minutes),
        )
    return _load_candump_df(source, normalize_time=normalize_time)


def detect_log_format(path: str | Path) -> str:
    return inspect_log_metadata(path).format


def inspect_log_metadata(path: str | Path) -> LogMetadata:
    source = Path(path)
    created_at_text: str | None = None
    detected_format: str | None = None
    with source.open("r", encoding="utf-8", errors="ignore") as handle:
        for _ in range(120):
            line = handle.readline()
            if not line:
                break
            text = line.strip()
            if not text:
                continue
            created_match = _KVASER_CREATED_AT_RE.search(text)
            if created_match:
                created_at_text = created_match.group(1)
            if "Kvaser Memorator Log" in text:
                detected_format = FORMAT_KVASER_MEMORATOR
                continue
            if parse_candump_line(text) is not None:
                if detected_format != FORMAT_KVASER_MEMORATOR:
                    detected_format = FORMAT_CANDUMP
                break
            if parse_kvaser_memorator_line(text) is not None:
                detected_format = FORMAT_KVASER_MEMORATOR
                break
    return LogMetadata(format=detected_format or FORMAT_CANDUMP, created_at_text=created_at_text)


def _resolve_kvaser_start_epoch(metadata: LogMetadata, source_tz_offset_minutes: int | None) -> float | None:
    if metadata.format != FORMAT_KVASER_MEMORATOR:
        return None
    if not metadata.created_at_text or source_tz_offset_minutes is None:
        return None
    dt = datetime.strptime(metadata.created_at_text, "%Y-%m-%d %H:%M:%S")
    tzinfo = timezone(timedelta(minutes=int(source_tz_offset_minutes)))
    return dt.replace(tzinfo=tzinfo).timestamp()


@dataclass
class StreamCanParser:
    normalize_time: bool = False
    format_hint: str = "auto"

    def __post_init__(self) -> None:
        self._t0: float | None = None
        self._format = self.format_hint

    def parse_line(self, line: str) -> dict | None:
        text = (line or "").strip()
        if not text:
            return None

        if self._format in {"auto", FORMAT_CANDUMP}:
            row = parse_candump_line(text)
            if row is not None:
                self._format = FORMAT_CANDUMP
                return self._normalize_row(row)

        if self._format in {"auto", FORMAT_KVASER_MEMORATOR}:
            row = parse_kvaser_memorator_line(text)
            if row is not None:
                self._format = FORMAT_KVASER_MEMORATOR
                return self._normalize_row(row)

        return None

    def _normalize_row(self, row: dict) -> dict:
        if not self.normalize_time:
            return row

        ts = float(row["TS"])
        if self._t0 is None:
            self._t0 = ts

        normalized = dict(row)
        normalized["TS"] = round(ts - self._t0, 6)
        return normalized


def parse_candump_line(line: str) -> dict | None:
    s = (line or "").strip()
    if not s:
        return None

    compact = _CANDUMP_COMPACT_RE.match(s)
    if compact:
        data = (compact.group(4) or "").upper()[:16]
        return frame_dict(
            ts=float(compact.group(1)),
            bus=compact.group(2),
            can_id=compact.group(3),
            data=bytes.fromhex(data) if data else b"",
        )

    spaced = _CANDUMP_SPACED_RE.match(s)
    if not spaced:
        return None

    parts = ((spaced.group(5) or "").strip()).split()
    declared_len = int(spaced.group(4))
    payload = bytes.fromhex("".join(parts[:8])) if parts else b""
    row = frame_dict(
        ts=float(spaced.group(1)),
        bus=spaced.group(2),
        can_id=spaced.group(3),
        data=payload,
    )
    row["LEN"] = min(declared_len, len(parts))
    return row


def parse_kvaser_memorator_line(line: str) -> dict | None:
    s = (line or "").strip()
    if not s or "Trigger" in s:
        return None

    match = _KVASER_RE.match(s)
    if not match:
        return None

    parts = ((match.group(5) or "").strip()).split()
    declared_len = int(match.group(4))
    payload = bytes.fromhex("".join(parts[:8])) if parts else b""
    row = frame_dict(
        ts=float(match.group(1)),
        bus=match.group(2),
        can_id=match.group(3),
        data=payload,
    )
    row["LEN"] = min(declared_len, len(parts))
    return row


def _build_candump_compact(raw: pl.DataFrame) -> pl.DataFrame:
    return raw.with_columns(
        pl.col("raw").str.extract(_CANDUMP_COMPACT_PATTERN, 1).alias("TS"),
        pl.col("raw").str.extract(_CANDUMP_COMPACT_PATTERN, 2).alias("Bus"),
        pl.col("raw").str.extract(_CANDUMP_COMPACT_PATTERN, 3).alias("ID"),
        pl.col("raw").str.extract(_CANDUMP_COMPACT_PATTERN, 4).fill_null("").alias("DATA"),
        pl.lit(None, dtype=pl.Int64).alias("_declared_len"),
    )


def _build_candump_spaced(raw: pl.DataFrame) -> pl.DataFrame:
    return raw.with_columns(
        pl.col("raw").str.extract(_CANDUMP_SPACED_PATTERN, 1).alias("TS"),
        pl.col("raw").str.extract(_CANDUMP_SPACED_PATTERN, 2).alias("Bus"),
        pl.col("raw").str.extract(_CANDUMP_SPACED_PATTERN, 3).alias("ID"),
        pl.col("raw").str.extract(_CANDUMP_SPACED_PATTERN, 5).fill_null("").alias("_bytes"),
        pl.col("raw").str.extract(_CANDUMP_SPACED_PATTERN, 4).cast(pl.Int64, strict=False).alias("_declared_len"),
    ).with_columns(
        pl.col("_bytes").str.replace_all(r"\s+", "").str.to_uppercase().str.slice(0, 16).alias("DATA")
    )


def _sniff_candump_variant(path: str | Path) -> str | None:
    """Peek a handful of lines to tell compact vs spaced apart cheaply -- avoids
    building both full regex-extract passes over every row (EPIC Performance y
    memoria, item 2) when only one variant will ever match."""
    with Path(path).open("r", encoding="utf-8", errors="ignore") as handle:
        for _ in range(120):
            line = handle.readline()
            if not line:
                break
            text = line.strip()
            if not text:
                continue
            if _CANDUMP_COMPACT_RE.match(text):
                return "compact"
            if _CANDUMP_SPACED_RE.match(text):
                return "spaced"
    return None


def _load_candump_df(path: Path, *, normalize_time: bool) -> pl.DataFrame:
    raw = pl.read_csv(path, has_header=False, new_columns=["raw"])
    variant = _sniff_candump_variant(path)

    df = pl.DataFrame()
    if variant != "spaced":
        df = _build_candump_compact(raw).filter(pl.col("TS").is_not_null())
    if df.is_empty():
        df = _build_candump_spaced(raw).filter(pl.col("TS").is_not_null())
    return _finalize_loaded_df(df, normalize_time=normalize_time)


def _load_kvaser_memorator_df(path: Path, *, normalize_time: bool, start_epoch: float | None = None) -> pl.DataFrame:
    raw = pl.read_csv(path, has_header=False, new_columns=["raw"])

    df = raw.with_columns(
        pl.col("raw").str.extract(_KVASER_PATTERN, 1).alias("TS"),
        pl.col("raw").str.extract(_KVASER_PATTERN, 2).alias("Bus"),
        pl.col("raw").str.extract(_KVASER_PATTERN, 3).alias("ID"),
        pl.col("raw").str.extract(_KVASER_PATTERN, 4).cast(pl.Int64, strict=False).alias("_declared_len"),
        pl.col("raw").str.extract(_KVASER_PATTERN, 5).fill_null("").alias("_bytes"),
    ).with_columns(
        pl.col("_bytes").str.replace_all(r"\s+", "").str.to_uppercase().str.slice(0, 16).alias("DATA")
    )

    df = df.filter(pl.col("TS").is_not_null())
    if start_epoch is not None and not normalize_time:
        df = df.with_columns((pl.col("TS").cast(pl.Float64) + pl.lit(float(start_epoch))).alias("TS"))
    return _finalize_loaded_df(df, normalize_time=normalize_time)


def _finalize_loaded_df(df: pl.DataFrame, *, normalize_time: bool) -> pl.DataFrame:
    if df.is_empty():
        return empty_frame()

    df = df.with_columns(
        pl.col("TS").cast(pl.Float64),
        pl.col("Bus").cast(pl.Utf8),
        pl.col("ID").cast(pl.Utf8).str.to_uppercase().str.replace_all(r"X$", ""),
        pl.col("DATA").fill_null("").cast(pl.Utf8).str.to_uppercase().str.slice(0, 16).alias("DATA"),
    )

    df = df.with_columns(
        pl.when(pl.col("_declared_len").is_not_null())
        .then(pl.min_horizontal(pl.col("_declared_len"), (pl.col("DATA").str.len_chars() / 2).cast(pl.Int64)))
        .otherwise((pl.col("DATA").str.len_chars() / 2).cast(pl.Int64))
        .alias("LEN")
    )

    df = df.with_columns(pl.col("DATA").str.pad_end(16, "0").alias("_data_padded"))

    for i in range(8):
        df = df.with_columns(
            pl.col("_data_padded").str.slice(i * 2, 2).str.to_integer(base=16).alias(f"D{i}")
        )

    if normalize_time and df.height > 0:
        t0 = df.select(pl.first("TS")).item()
        df = df.with_columns((pl.col("TS") - t0).round(6).alias("TS"))

    return df.select(list(FRAME_SCHEMA.keys())).cast(FRAME_SCHEMA)
