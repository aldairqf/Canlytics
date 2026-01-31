from __future__ import annotations

import polars as pl

from services.bam_reassembly import assemble_bam_messages


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
        frame_id = int(str(raw_id), 16)
    except ValueError:
        return []

    frame_pgn = (frame_id >> 8) & 0x3FFFF
    source = frame_id & 0xFF

    target_pgn = None
    if frame_pgn == 0xEC00:
        payload = _parse_bytes(data_hex)
        if len(payload) >= 8 and payload[0] == 0x20:
            target_pgn = payload[5] | (payload[6] << 8) | (payload[7] << 16)
    elif frame_pgn == 0xEB00:
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
        value_str = dbc_manager._format_value(value)
        unit = getattr(signal, "unit", None)
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
            "name": signal.name,
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
            frame_id = int(str(raw_id), 16)
        except ValueError:
            continue
        if (frame_id & 0xFF) != source:
            continue
        if ((frame_id >> 8) & 0x3FFFF) != 0xEC00:
            continue
        payload = _parse_bytes(data_hex)
        if len(payload) < 8 or payload[0] != 0x20:
            continue
        target = payload[5] | (payload[6] << 8) | (payload[7] << 16)
    return target


def _parse_bytes(data_hex) -> bytes:
    text = str(data_hex or "")
    if len(text) % 2 == 1:
        text = text + "0"
    if not text:
        return b""
    try:
        return bytes.fromhex(text)
    except ValueError:
        return b""
