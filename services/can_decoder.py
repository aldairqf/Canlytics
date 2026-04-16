import numpy as np
import polars as pl

from models.frame_selector import FrameSelector
from models.signal import Signal
from services.bam_reassembly import assemble_bam_messages


def decode_signal(df: pl.DataFrame, signal: Signal, selector: FrameSelector):
    if df is None or df.is_empty():
        return [], []

    if selector.mode == "bam":
        return _decode_signal_bam(df, signal, selector)

    df = _filter_by_selector(df, signal, selector)
    if df.is_empty():
        return [], []

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

    df = df.with_columns(data_int_expr.alias("DATA_INT"))

    if signal.le:
        raw_expr = None
        for i in range(signal.length):
            bit_index = signal.start_bit + i
            bit = ((pl.col("DATA_INT") // (2**bit_index)) % 2) * (2**i)
            raw_expr = bit if raw_expr is None else (raw_expr + bit)
    else:
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

    df = df.with_columns(raw_expr.alias("RAW"))

    raw_array = df["RAW"].cast(pl.UInt64).to_numpy()

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
    timestamps = df["TS"].to_numpy()

    return timestamps.tolist(), values.tolist()


def _extract_j1939_pgn(frame_id: int) -> int:
    frame_id = int(frame_id) & 0x1FFFFFFF

    dp = (frame_id >> 24) & 0x01
    pf = (frame_id >> 16) & 0xFF
    ps = (frame_id >> 8) & 0xFF

    if pf < 240:
        return (dp << 16) | (pf << 8)

    return (dp << 16) | (pf << 8) | ps


def _filter_by_selector(df: pl.DataFrame, signal: Signal, selector: FrameSelector) -> pl.DataFrame:
    if selector.mode == "j1939":
        pgn = selector.pgn
        if pgn is None:
            cid = _hex_to_int(selector.selected_id) or _hex_to_int(signal.can_id) or selector.target_id
            if cid is not None:
                pgn = _extract_j1939_pgn(cid)
        if pgn is None:
            return df.head(0)

        df = df.with_columns(pl.col("ID").str.to_integer(base=16, strict=False).alias("_ID_INT"))
        df = df.filter(pl.col("_ID_INT").is_not_null())
        df = df.filter(
            pl.col("_ID_INT").map_elements(
                lambda x: _extract_j1939_pgn(int(x)) == int(pgn),
                return_dtype=pl.Boolean,
            )
        )

        chosen_id = _hex_to_int(signal.can_id)
        if chosen_id is not None:
            df = df.filter(pl.col("_ID_INT") == int(chosen_id))

        return df.drop("_ID_INT")

    target = _hex_to_int(signal.can_id)
    if target is None:
        target = selector.selected_id_int()
    if target is None:
        target = selector.target_id
    if target is None:
        return df.head(0)

    df = df.with_columns(pl.col("ID").str.to_integer(base=16, strict=False).alias("_ID_INT"))
    df = df.filter(pl.col("_ID_INT").is_not_null())
    return df.filter(pl.col("_ID_INT") == int(target)).drop("_ID_INT")

def _decode_signal_bam(df: pl.DataFrame, signal: Signal, selector: FrameSelector):
    pgn = selector.pgn
    if pgn is None:
        return [], []

    source = _derive_source(selector.selected_id)

    messages = assemble_bam_messages(df, pgn, source_address=source)
    if not messages:
        return [], []

    timestamps: list[float] = []
    values: list[float] = []

    for msg in messages:
        raw = _extract_raw_from_payload(signal, msg.data)
        if raw is None:
            continue
        value = _convert_raw_value(signal, raw)
        timestamps.append(float(msg.timestamp))
        values.append(value)

    return timestamps, values


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
