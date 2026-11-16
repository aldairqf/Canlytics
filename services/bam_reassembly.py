from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from services.j1939_transport import assemble_transport_messages


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
    """Compatibility wrapper for the existing BAM-only callers."""
    messages = assemble_transport_messages(df, target_pgn, source_address=source_address)
    return [
        BamMessage(message.timestamp, message.source_address, message.pgn, message.data)
        for message in messages
        if message.protocol == "BAM"
    ]
