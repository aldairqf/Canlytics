import numpy as np
import polars as pl

from models.frame_selector import FrameSelector
from models.signal import Signal


def decode_signal(df: pl.DataFrame, signal: Signal, selector: FrameSelector):
    if df is None or df.is_empty():
        return [], []

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


def _hex_to_int(value):
    if not value:
        return None
    try:
        return int(str(value), 16)
    except (TypeError, ValueError):
        return None
