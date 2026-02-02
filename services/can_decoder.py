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
            pl.col("DATA").str.slice(i * 2, 2).str.to_integer(base=16).cast(pl.UInt64)
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

    if signal.type_data == "float32":
        raw_array = df["RAW"].to_numpy().astype(np.uint32)
        values = raw_array.view(np.float32)
    elif signal.type_data == "int":
        raw_array = df["RAW"].to_numpy()
        values = raw_array.astype(np.int32)
    else:
        raw_array = df["RAW"].to_numpy()
        values = raw_array.astype(np.uint32)

    values = values * signal.scale + signal.offset
    timestamps = df["TS"].to_numpy()

    return timestamps.tolist(), values.tolist()


def _filter_by_selector(df: pl.DataFrame, signal: Signal, selector: FrameSelector) -> pl.DataFrame:
    if selector.mode == "j1939":
        pgn = selector.pgn
        if pgn is None:
            cid = _hex_to_int(selector.selected_id) or _hex_to_int(signal.can_id) or selector.target_id
            if cid is not None:
                pgn = (cid >> 8) & 0x3FFFF
        if pgn is None:
            return df.head(0)

        df = df.with_columns(pl.col("ID").str.to_integer(base=16).alias("_ID_INT"))
        df = df.filter(((pl.col("_ID_INT") // 256) % (1 << 18)) == int(pgn))

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

    df = df.with_columns(pl.col("ID").str.to_integer(base=16).alias("_ID_INT"))
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
    if signal.type_data == "float32":
        raw_array = np.array([raw_value], dtype=np.uint32)
        values = raw_array.view(np.float32)
        return float(values[0] * signal.scale + signal.offset)
    if signal.type_data == "int":
        raw_array = np.array([raw_value], dtype=np.int32)
        return float(raw_array[0] * signal.scale + signal.offset)
    raw_array = np.array([raw_value], dtype=np.uint32)
    return float(raw_array[0] * signal.scale + signal.offset)


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
