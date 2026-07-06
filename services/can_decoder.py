import numpy as np
import polars as pl

from models.frame_selector import FrameSelector
from models.signal import Signal
from services.bam_reassembly import assemble_bam_messages


def filter_frames_for_signal(df: pl.DataFrame, signal: Signal, selector: FrameSelector) -> pl.DataFrame:
    """The exact/j1939 id-or-PGN filter, exposed so a caller that's decoding many
    signals of the *same* message (same id/PGN) can filter once and reuse the
    result instead of re-filtering per signal -- see with_data_int/extract_signal_raw
    and services/signal_coverage.py."""
    return _filter_by_selector(df, signal, selector)


def with_data_int(df: pl.DataFrame) -> pl.DataFrame:
    """Add the DATA_INT column (the frame's 8 data bytes as one little-endian
    uint64) that bit extraction reads from. Depends only on DATA, so it's the
    same for every signal of a message -- compute once, reuse per signal."""
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
    """The LE/BE bit-extraction expression for ``signal`` against a DATA_INT
    column. Pure expression building, no dataframe I/O -- shared by
    extract_signal_raw() (one signal) and extract_signals_raw_batch() (many)."""
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
    """Timestamps + raw bit pattern for ``signal`` from a dataframe already
    filtered by filter_frames_for_signal() and augmented by with_data_int()."""
    if signal.mux_bytes > 0:
        mux_expr = None
        start = signal.mux_start
        for i in range(signal.mux_bytes):
            byte_col = f"D{start + i}"
            shift = 8 * (signal.mux_bytes - 1 - i)
            term = pl.col(byte_col) * (2**shift)
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
    """Batched extract_signal_raw() for multiple *non-muxed* signals that share
    the same already-filtered+DATA_INT dataframe: builds every signal's raw-bit
    column in ONE with_columns() call instead of one call per signal.

    Each Polars with_columns()/collect() has fixed per-call overhead that
    doesn't shrink with the dataframe size -- for a DBC with thousands of
    signals, that fixed cost (not the actual bit arithmetic) dominates the
    runtime. Batching turns N calls into 1. Callers must not pass muxed
    signals here (mux_bytes > 0) since each may need its own row subset --
    those still go through extract_signal_raw() individually.
    """
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
    """Timestamps + the raw, type-agnostic bit pattern ``signal`` occupies in each matching frame.

    This is everything ``decode_signal`` does up through bit extraction (and mux
    filtering) -- before the uint/int/float32 type interpretation and before
    scale/offset are applied. Because it's the raw bit pattern, "all bits set"
    (``2**signal.length - 1``) means the same thing ("not available", the SAE J1939
    convention) regardless of how the signal is typed -- see services/signal_coverage.py.

    Single-signal convenience wrapper around filter_frames_for_signal() +
    with_data_int() + extract_signal_raw() -- callers decoding many signals of the
    same message should call those three directly and reuse the filtered frame.
    """
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
    """Apply the same uint/int/float32 typing + NaN handling + scale/offset that
    decode_signal() applies, given raw values already obtained from decode_signal_raw().

    Split out so a caller that already has the raw bit pattern (e.g. to test for a
    "not available" sentinel) doesn't have to re-run the dataframe filter and bit
    extraction a second time just to also get the scaled value -- see
    services/signal_coverage.py.
    """
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


# J1939 is always carried on 29-bit extended frames; an id that fits in an
# 11-bit standard frame (<= 0x7FF) cannot be a real J1939 PDU. Without this
# guard, extracting pf/ps/dp from such an id reads all-zero high bits and
# resolves to PGN 0 (TSC1) for practically every standard-id frame on the bus,
# silently merging unrelated non-J1939 traffic into whatever message owns PGN 0.
_STANDARD_ID_MAX = 0x7FF


def _extract_j1939_pgn(frame_id: int) -> int | None:
    frame_id = int(frame_id) & 0x1FFFFFFF
    if frame_id <= _STANDARD_ID_MAX:
        return None

    dp = (frame_id >> 24) & 0x01
    pf = (frame_id >> 16) & 0xFF
    ps = (frame_id >> 8) & 0xFF

    if pf < 240:
        return (dp << 16) | (pf << 8)

    return (dp << 16) | (pf << 8) | ps


def _j1939_pgn_expr(id_expr: pl.Expr) -> pl.Expr:
    """Vectorized equivalent of _extract_j1939_pgn -- same PDU1/PDU2 split (and
    the same standard-id guard), computed for every row at once instead of a
    per-row Python callback."""
    id_masked = id_expr % (2**29)
    dp = (id_masked // (2**24)) % 2
    pf = (id_masked // (2**16)) % 256
    ps = (id_masked // (2**8)) % 256
    pgn = pl.when(pf < 240).then(dp * (2**16) + pf * (2**8)).otherwise(dp * (2**16) + pf * (2**8) + ps)
    return pl.when(id_masked <= _STANDARD_ID_MAX).then(None).otherwise(pgn)


def with_id_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Precompute the parsed CAN id (``_ID_INT``) and its J1939 PGN (``_PGN``)
    once for the whole dataframe. Filtering many signals/messages against the
    same log otherwise means every one of them re-parses the ID column from
    scratch -- for a DBC with thousands of signals that dominates the runtime.
    _filter_by_selector reuses these columns when present instead of recomputing
    them; see services/signal_coverage.py, which calls this once before scanning.
    """
    if "_ID_INT" in df.columns:
        return df
    df = df.with_columns(pl.col("ID").str.to_integer(base=16, strict=False).alias("_ID_INT"))
    df = df.filter(pl.col("_ID_INT").is_not_null())
    return df.with_columns(_j1939_pgn_expr(pl.col("_ID_INT")).alias("_PGN"))


def partition_by_pgn(df: pl.DataFrame) -> dict[int, pl.DataFrame]:
    """Split the whole log into one dataframe per J1939 PGN, in a single pass.

    A caller that scans every message of a DBC against the log (see
    services/signal_coverage.py) would otherwise filter the full dataframe once
    per message -- most DBC messages never appear in a given log at all, so
    that's thousands of full-table scans. Partitioning once up front turns each
    message lookup into an O(1) dict lookup (or a miss, for free, when the PGN
    never appears in the log).
    """
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
            cid = _hex_to_int(selector.selected_id) or _hex_to_int(signal.can_id) or selector.target_id
            if cid is not None:
                pgn = _extract_j1939_pgn(cid)
        if pgn is None:
            return df.head(0)

        if "_PGN" not in df.columns:
            df = df.with_columns(_j1939_pgn_expr(pl.col("_ID_INT")).alias("_PGN"))
        df = df.filter(pl.col("_PGN") == int(pgn))

        chosen_id = _hex_to_int(signal.can_id)
        if chosen_id is not None:
            df = df.filter(pl.col("_ID_INT") == int(chosen_id))

        return df

    target = _hex_to_int(signal.can_id)
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
        mux_value = _compute_mux_value(signal, payload)
        if signal.mux_value is not None and mux_value != int(signal.mux_value):
            return None

    data_int = int.from_bytes(payload, byteorder="little", signed=False)

    if signal.le:
        raw = 0
        for i in range(signal.length):
            bit_index = signal.start_bit + i
            bit = ((data_int >> bit_index) & 1) << i
            raw |= bit
        return raw

    raw = 0
    start_byte = signal.start_bit // 8
    start_bit_in_byte = signal.start_bit % 8
    byte = start_byte
    bit = start_bit_in_byte

    for i in range(signal.length):
        bit_index = byte * 8 + bit
        raw |= ((data_int >> bit_index) & 1) << (signal.length - 1 - i)
        if bit > 0:
            bit -= 1
        else:
            byte += 1
            bit = 7

    return raw


def _compute_mux_value(signal: Signal, payload: bytes) -> int:
    value = 0
    start = signal.mux_start
    for i in range(signal.mux_bytes):
        idx = start + i
        if idx >= len(payload):
            break
        shift = 8 * (signal.mux_bytes - 1 - i)
        value += payload[idx] << shift
    return value


def _convert_raw_value(signal: Signal, raw_value: int) -> float:
    nbits = getattr(signal, "length", 32) or 32
    raw = int(raw_value) & ((1 << nbits) - 1)

    if signal.type_data == "float32":
        raw32 = raw & 0xFFFFFFFF
        value = np.array([raw32], dtype=np.uint32).view(np.float32)[0]
        return float(value * signal.scale + signal.offset)

    if signal.type_data == "int":
        sign_bit = 1 << (nbits - 1)
        signed = raw - (1 << nbits) if (raw & sign_bit) else raw
        return float(signed * signal.scale + signal.offset)

    return float(raw * signal.scale + signal.offset)


def _hex_to_int(value):
    if not value:
        return None
    try:
        return int(str(value), 16)
    except (TypeError, ValueError):
        return None


def _derive_source(value):
    if value is None:
        return None
    raw = _hex_to_int(value)
    if raw is None:
        return None
    if raw > 0xFF:
        return raw & 0xFF
    return raw
