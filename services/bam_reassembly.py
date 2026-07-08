from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from utils.can_bytes import parse_hex_bytes
from utils.can_id import can_id_to_int
from utils.j1939 import J1939


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
            frame_id = can_id_to_int(raw_id)
        except ValueError:
            continue

        pf = (frame_id >> 16) & 0xFF
        sa = frame_id & 0xFF

        if source_address is not None and sa != source_address:
            continue

        payload = parse_hex_bytes(data_hex)

        if pf == 0xEC:
            msg_pgn = J1939.parse_bam_announce(payload)
            if msg_pgn is None or msg_pgn != target_pgn:
                continue
            total_bytes = payload[1] | (payload[2] << 8)
            total_packets = payload[3]

            sessions[sa] = {
                "total_bytes": total_bytes,
                "total_packets": total_packets,
                "data": bytearray(total_bytes),
                "received": set(),
                "timestamp": float(ts),
            }
            continue

        if pf != 0xEB:
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
