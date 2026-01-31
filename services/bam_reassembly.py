from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass
class BamMessage:
    timestamp: float
    source_address: int
    pgn: int
    data: bytes


def assemble_bam_messages(
    df: pl.DataFrame,
    target_pgn: int,
    source_address: int | None = None,
) -> list[BamMessage]:
    if df is None or df.is_empty():
        return []

    target_pgn = int(target_pgn)
    sessions: dict[int, dict] = {}
    results: list[BamMessage] = []

    for ts, raw_id, data_hex in df.select(["TS", "ID", "DATA"]).iter_rows():
        if raw_id is None:
            continue
        try:
            frame_id = int(str(raw_id), 16)
        except ValueError:
            continue

        pgn = (frame_id >> 8) & 0x3FFFF
        sa = frame_id & 0xFF

        if source_address is not None and sa != source_address:
            continue

        payload = _parse_bytes(data_hex)

        if pgn == 0xEC00:
            if len(payload) < 8:
                continue
            if payload[0] != 0x20:
                continue
            total_bytes = payload[1] | (payload[2] << 8)
            total_packets = payload[3]
            pgn_bytes = payload[5:8]
            msg_pgn = pgn_bytes[0] | (pgn_bytes[1] << 8) | (pgn_bytes[2] << 16)
            if msg_pgn != target_pgn:
                continue

            sessions[sa] = {
                "total_bytes": total_bytes,
                "total_packets": total_packets,
                "data": bytearray(total_bytes),
                "received": set(),
                "timestamp": float(ts),
            }
            continue

        if pgn != 0xEB00:
            continue

        if len(payload) < 8:
            continue

        session = sessions.get(sa)
        if not session:
            continue

        seq = payload[0]
        if seq == 0:
            continue

        start = (seq - 1) * 7
        end = start + 7
        data_bytes = payload[1:8]
        if start < len(session["data"]):
            session["data"][start:min(end, len(session["data"]))] = data_bytes[: max(0, len(session["data"]) - start)]
        session["received"].add(seq)
        session["timestamp"] = float(ts)

        if len(session["received"]) >= session["total_packets"]:
            results.append(
                BamMessage(
                    timestamp=session["timestamp"],
                    source_address=sa,
                    pgn=target_pgn,
                    data=bytes(session["data"]),
                )
            )
            sessions.pop(sa, None)

    return results


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
