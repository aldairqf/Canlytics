from __future__ import annotations

import polars as pl

from services.bam_reassembly import assemble_bam_messages
from services.signal_formatting import format_signal_value, normalize_display_text
from utils.can_bytes import parse_hex_bytes
from utils.can_id import can_id_to_int
from utils.j1939 import J1939


def decode_bam_frame(df: pl.DataFrame, row_index: int, dbc_manager) -> list[dict]:
    if df is None or df.is_empty():
        return []

    if row_index < 0 or row_index >= df.height:
        return []

    record = df.row(row_index, named=True)
    raw_id = record.get("ID")
    data_hex = record.get("DATA")
    ts = record.get("TS")

    if raw_id is None:
        return []

    try:
        frame_id = can_id_to_int(raw_id)
    except ValueError:
        return []

    frame_pf = (frame_id >> 16) & 0xFF
    source = frame_id & 0xFF

    target_pgn = None
    if frame_pf == 0xEC:
        target_pgn = J1939.parse_bam_announce(parse_hex_bytes(data_hex))
    elif frame_pf == 0xEB:
        target_pgn = _find_last_bam_pgn(df, source, ts)

    if target_pgn is None:
        return []

    resolved = dbc_manager.get_message_by_pgn(target_pgn)
    if not resolved:
        return []
    entry, message = resolved

    messages = assemble_bam_messages(df, target_pgn, source_address=source)
    if not messages:
        return []

    payload = messages[-1].data
    try:
        data_bytes = bytes(payload)
    except Exception:
        return []

    if len(data_bytes) < message.length:
        data_bytes = data_bytes.ljust(message.length, b"\x00")
    elif len(data_bytes) > message.length:
        data_bytes = data_bytes[: message.length]

    try:
        decoded = message.decode(data_bytes, decode_choices=False)
    except Exception:
        return []

    items = []
    for signal in message.signals:
        if signal.name not in decoded:
            continue
        value = decoded[signal.name]
        value_str = format_signal_value(value)
        unit = normalize_display_text(getattr(signal, "unit", None))
        try:
            signal_def = dbc_manager.get_signal_definition(
                entry.name,
                message.name,
                signal.name,
                scaled=True,
            )
        except Exception:
            signal_def = None
        items.append({
            "name": normalize_display_text(signal.name),
            "value": value_str,
            "unit": unit,
            "signal_def": signal_def,
        })
    return items


def _find_last_bam_pgn(df: pl.DataFrame, source: int, ts) -> int | None:
    target = None
    if df is None or df.is_empty():
        return None
    for row_ts, raw_id, data_hex in df.select(["TS", "ID", "DATA"]).iter_rows():
        if row_ts is None or row_ts > ts:
            break
        try:
            frame_id = can_id_to_int(raw_id)
        except ValueError:
            continue
        if (frame_id & 0xFF) != source:
            continue
        if ((frame_id >> 16) & 0xFF) != 0xEC:
            continue
        pgn = J1939.parse_bam_announce(parse_hex_bytes(data_hex))
        if pgn is not None:
            target = pgn
    return target
