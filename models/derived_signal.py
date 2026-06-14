from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DerivedSignal:
    """Signal computed via a user-defined Python/NumPy formula.

    The formula is a multi-line script executed in a restricted sandbox.
    It must assign ``result = (ts_array, y_array)`` before it ends.

    Available in the formula namespace:
        np, math
        signal(name)               -> (ts, y) from a decoded plot signal
        bam_messages(pgn, source)  -> list[BamMessage]
        bam_extract(pgn, offset, n, dtype)  -> (ts, y)
        raw_frames(can_id, mode, pgn)       -> iterator of (ts, bytes)
        raw_extract(can_id, offset, n, dtype, mode, pgn)  -> (ts, y)
        decode_bytes(data, offset, n, dtype)  -> scalar
        align(*[(ts, y), ...])     -> (common_ts, [y1_aligned, ...])
    """

    name: str
    formula: str
    inputs: list[str] = field(default_factory=list)
