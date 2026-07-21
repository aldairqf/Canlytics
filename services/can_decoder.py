import numpy as np
import polars as pl

from models.frame_selector import FrameSelector
from models.signal import Signal
from services.bam_reassembly import assemble_bam_messages
from utils.can_id import can_id_to_int_or_none
from utils.dbc_payload import DbcPayload
from utils.j1939 import STANDARD_ID_MAX, J1939


def filter_frames_for_signal(df: pl.DataFrame, signal: Signal, selector: FrameSelector) -> pl.DataFrame:
    """The exact/j1939 id-or-PGN filter, exposed so callers can filter once and reuse it."""
    return _filter_by_selector(df, signal, selector)


def with_data_int(df: pl.DataFrame) -> pl.DataFrame:
    """Add DATA_INT (8 data bytes as one little-endian uint64) for bit extraction.

    Idempotent (a no-op if DATA_INT is already a column) and prefers the already-
    parsed D0..D7 integer columns over re-parsing the DATA hex string when they're
    present -- both matter because callers that try many specs against the same
    group (Candidate Interpretations' brute-force search, BUGS.md B-30) used to pay
    a full hex re-parse on every single spec even though the group's DATA_INT never
    changes; the caller now computes it once per group and every further call in
    that group is free. Measured on a real ~47K-row group: ~5.32ms/call eliminated
    per redundant call.
    """
    if "DATA_INT" in df.columns:
        return df

    if all(f"D{i}" in df.columns for i in range(8)):
        data_int_expr = None
        for i in range(8):
            term = pl.col(f"D{i}").cast(pl.UInt64) * (2 ** (8 * i))
            data_int_expr = term if data_int_expr is None else (data_int_expr + term)
        return df.with_columns(data_int_expr.alias("DATA_INT"))

    # Fallback for dataframes without D0..D7 -- re-parse DATA the original way.
    data_int_expr = None
    for i in range(8):
        byte = (
            pl.col("DATA")
            .str.slice(i * 2, 2)
            .str.to_integer(base=16, strict=False)
            .fill_null(0)
            .cast(pl.UInt64)
        )
        term = byte * (2 ** (8 * i))
        data_int_expr = term if data_int_expr is None else (data_int_expr + term)
    return df.with_columns(data_int_expr.alias("DATA_INT"))


def _raw_bit_expr(signal: Signal) -> pl.Expr:
    """Vectorized DbcPayload.extract_bits -- can't call Python per-row without losing vectorization."""
    if signal.le:
        raw_expr = None
        for i in range(signal.length):
            bit_index = signal.start_bit + i
            bit = ((pl.col("DATA_INT") // (2**bit_index)) % 2) * (2**i)
            raw_expr = bit if raw_expr is None else (raw_expr + bit)
        return raw_expr

    raw_expr = None
    start_byte = signal.start_bit // 8
    start_bit_in_byte = signal.start_bit % 8

    byte = start_byte
    bit = start_bit_in_byte

    for i in range(signal.length):
        bit_index = byte * 8 + bit
        term = ((pl.col("DATA_INT") // (2**bit_index)) % 2) * (
            2 ** (signal.length - 1 - i)
        )
        raw_expr = term if raw_expr is None else raw_expr + term

        if bit > 0:
            bit -= 1
        else:
            byte += 1
            bit = 7

    return raw_expr


def extract_signal_raw(df: pl.DataFrame, signal: Signal):
    """Timestamps + raw bits for ``signal`` from an already filtered+with_data_int() df."""
    if signal.mux_bytes > 0:
        # Vectorized DbcPayload.mux_value (D0..D7 columns exist for every row -- no truncation case here).
        mux_expr = None
        start = signal.mux_start
        for i in range(signal.mux_bytes):
            byte_col = f"D{start + i}"
            shift = 8 * (signal.mux_bytes - 1 - i)
            # Explicit upcast before the shift-multiply: D{i} is UInt8, and relying on
            # Polars' literal-based auto-promotion instead (like with_data_int() does
            # deliberately) is an implicit dependency worth avoiding here too.
            term = pl.col(byte_col).cast(pl.UInt64) * (2**shift)
            mux_expr = term if mux_expr is None else mux_expr + term

        df = df.with_columns(mux_expr.alias("MUX_VALUE"))

        if signal.mux_value is not None:
            df = df.filter(pl.col("MUX_VALUE") == int(signal.mux_value))
        if df.is_empty():
            return [], []

    df = df.with_columns(_raw_bit_expr(signal).alias("RAW"))

    raw_array = df["RAW"].cast(pl.UInt64).to_numpy()
    timestamps = df["TS"].to_numpy()

    return timestamps.tolist(), raw_array.tolist()


def extract_signals_raw_batch(df: pl.DataFrame, signals: list[Signal]):
    """Batched extract_signal_raw() for non-muxed signals sharing one with_columns() call."""
    if not signals:
        return []
    exprs = [_raw_bit_expr(signal).alias(f"__RAW_{i}") for i, signal in enumerate(signals)]
    augmented = df.with_columns(*exprs)
    timestamps = augmented["TS"].to_numpy().tolist()
    return [
        (timestamps, augmented[f"__RAW_{i}"].cast(pl.UInt64).to_numpy().tolist())
        for i in range(len(signals))
    ]


def decode_signal_raw(df: pl.DataFrame, signal: Signal, selector: FrameSelector):
    """Timestamps + raw, type-agnostic bits for ``signal`` -- before type/scale/offset."""
    if df is None or df.is_empty():
        return [], []

    if selector.mode == "bam":
        return _decode_signal_raw_bam(df, signal, selector)

    df = filter_frames_for_signal(df, signal, selector)
    if df.is_empty():
        return [], []

    df = with_data_int(df)
    return extract_signal_raw(df, signal)


def convert_raw_signal_values(signal: Signal, raw_values, *, mode: str = "exact") -> list[float]:
    """uint/int/float32 typing + NaN handling + scale/offset for raw decode_signal_raw() values."""
    if not raw_values:
        return []

    if mode == "bam":
        return [_convert_raw_value(signal, raw) for raw in raw_values]

    raw_array = np.asarray(raw_values, dtype=np.uint64)

    if signal.type_data == "float32":
        raw_array32 = raw_array.astype(np.uint32, copy=False)
        values = raw_array32.view(np.float32)
    elif signal.type_data == "int":
        bit_length = int(getattr(signal, "length", 0) or 0)
        if bit_length <= 0:
            values = raw_array.astype(np.int64, copy=False)
        elif bit_length >= 64:
            values = raw_array.view(np.int64)
        else:
            sign_bit = np.uint64(1 << (bit_length - 1))
            full_scale = np.int64(1 << bit_length)
            values = raw_array.astype(np.int64, copy=True)
            negative_mask = (raw_array & sign_bit) != 0
            values[negative_mask] -= full_scale
    else:
        values = raw_array.astype(np.uint64, copy=False)

    values = np.nan_to_num(
        values,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )
    values = values * signal.scale + signal.offset

    return values.tolist()


def decode_signal(df: pl.DataFrame, signal: Signal, selector: FrameSelector):
    timestamps, raw_values = decode_signal_raw(df, signal, selector)
    if not timestamps:
        return [], []
    values = convert_raw_signal_values(signal, raw_values, mode=selector.mode)
    return timestamps, values


def _j1939_pgn_expr(id_expr: pl.Expr) -> pl.Expr:
    """Vectorized J1939.extract_pgn -- can't call Python per-row without losing vectorization."""
    id_masked = id_expr % (2**29)
    dp = (id_masked // (2**24)) % 2
    pf = (id_masked // (2**16)) % 256
    ps = (id_masked // (2**8)) % 256
    pgn = pl.when(pf < 240).then(dp * (2**16) + pf * (2**8)).otherwise(dp * (2**16) + pf * (2**8) + ps)
    return pl.when(id_masked <= STANDARD_ID_MAX).then(None).otherwise(pgn)


def with_id_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Precompute _ID_INT and its J1939 _PGN once for the whole dataframe."""
    if "_ID_INT" in df.columns:
        return df
    df = df.with_columns(pl.col("ID").str.to_integer(base=16, strict=False).alias("_ID_INT"))
    df = df.filter(pl.col("_ID_INT").is_not_null())
    return df.with_columns(_j1939_pgn_expr(pl.col("_ID_INT")).alias("_PGN"))


def partition_by_pgn(df: pl.DataFrame) -> dict[int, pl.DataFrame]:
    """Split the whole log into one dataframe per J1939 PGN, in a single pass."""
    if "_PGN" not in df.columns:
        df = with_id_columns(df)
    groups = df.partition_by("_PGN", as_dict=True)
    return {(key[0] if isinstance(key, tuple) else key): group for key, group in groups.items()}


def partition_by_id(df: pl.DataFrame) -> dict[int, pl.DataFrame]:
    """Same as partition_by_pgn but keyed by frame id, for exact-match messages."""
    if "_ID_INT" not in df.columns:
        df = with_id_columns(df)
    groups = df.partition_by("_ID_INT", as_dict=True)
    return {(key[0] if isinstance(key, tuple) else key): group for key, group in groups.items()}


def _filter_by_selector(df: pl.DataFrame, signal: Signal, selector: FrameSelector) -> pl.DataFrame:
    if "_ID_INT" not in df.columns:
        df = df.with_columns(pl.col("ID").str.to_integer(base=16, strict=False).alias("_ID_INT"))
        df = df.filter(pl.col("_ID_INT").is_not_null())

    if selector.mode == "j1939":
        pgn = selector.pgn
        if pgn is None:
            cid = can_id_to_int_or_none(selector.selected_id) or can_id_to_int_or_none(signal.can_id) or selector.target_id
            if cid is not None:
                pgn = J1939.extract_pgn(cid)
        if pgn is None:
            return df.head(0)

        if "_PGN" not in df.columns:
            df = df.with_columns(_j1939_pgn_expr(pl.col("_ID_INT")).alias("_PGN"))
        df = df.filter(pl.col("_PGN") == int(pgn))

        chosen_id = can_id_to_int_or_none(signal.can_id)
        if chosen_id is not None:
            df = df.filter(pl.col("_ID_INT") == int(chosen_id))

        return df

    target = can_id_to_int_or_none(signal.can_id)
    if target is None:
        target = selector.selected_id_int()
    if target is None:
        target = selector.target_id
    if target is None:
        return df.head(0)

    return df.filter(pl.col("_ID_INT") == int(target))

def _decode_signal_raw_bam(df: pl.DataFrame, signal: Signal, selector: FrameSelector):
    pgn = selector.pgn
    if pgn is None:
        return [], []

    source = _derive_source(selector.selected_id)

    messages = assemble_bam_messages(df, pgn, source_address=source)
    if not messages:
        return [], []

    timestamps: list[float] = []
    raw_values: list[int] = []

    for msg in messages:
        raw = _extract_raw_from_payload(signal, msg.data)
        if raw is None:
            continue
        timestamps.append(float(msg.timestamp))
        raw_values.append(int(raw))

    return timestamps, raw_values


def _extract_raw_from_payload(signal: Signal, payload: bytes):
    if not payload:
        return None

    if signal.mux_bytes > 0:
        mux_value = DbcPayload.mux_value(payload, signal.mux_start, signal.mux_bytes)
        if signal.mux_value is not None and mux_value != int(signal.mux_value):
            return None

    return DbcPayload.extract_bits(payload, signal.start_bit, signal.length, signal.le)


def _convert_raw_value(signal: Signal, raw_value: int) -> float:
    nbits = getattr(signal, "length", 32) or 32
    raw = int(raw_value) & ((1 << nbits) - 1)

    if signal.type_data == "float32":
        raw32 = raw & 0xFFFFFFFF
        value = float(np.array([raw32], dtype=np.uint32).view(np.float32)[0])
        # Match convert_raw_signal_values' nan_to_num guard for the exact/j1939 path.
        if not np.isfinite(value):
            value = 0.0
        return float(value * signal.scale + signal.offset)

    if signal.type_data == "int":
        sign_bit = 1 << (nbits - 1)
        signed = raw - (1 << nbits) if (raw & sign_bit) else raw
        return float(signed * signal.scale + signal.offset)

    return float(raw * signal.scale + signal.offset)


def _derive_source(value):
    if value is None:
        return None
    raw = can_id_to_int_or_none(value)
    if raw is None:
        return None
    if raw > 0xFF:
        return raw & 0xFF
    return raw
