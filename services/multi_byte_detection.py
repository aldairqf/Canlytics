"""P2: detect whether two adjacent bytes behave as one wider (16-bit) value.

Qt-free, shared primitive: whenever the low byte wraps around (a jump of at least
half the 8-bit range, e.g. 255->0), a genuine carry-linked high byte changes by
exactly +/-1 at that same transition almost every time. Two independent bytes
essentially never coincide like that. Consumed by Candidate Interpretations (P2.2)
now, and Diff Analyzer (P2.3) later -- one core, two consumers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

_WRAP_JUMP_THRESHOLD = 200  # |delta| beyond this on an 8-bit value counts as a wraparound
_COINCIDENCE_THRESHOLD = 0.7  # informational only -- labels the verdict, never hides the numbers


@dataclass(frozen=True)
class MultiByteHint:
    low_byte_index: int
    high_byte_index: int
    coincidence_ratio: float  # fraction of low's wrap events where high carried by exactly +/-1
    wrap_count: int
    is_multi_byte: bool


def detect_carry_alignment(
    low_values: Sequence[int],
    high_values: Sequence[int],
    *,
    low_byte_index: int,
    high_byte_index: int,
) -> MultiByteHint | None:
    """None only when there isn't enough data (fewer than 2 samples, or mismatched
    lengths). Weak or zero evidence is still returned, never swallowed by a
    confidence threshold -- is_multi_byte is an informational verdict label only,
    never a gate on whether this is returned."""
    if len(low_values) != len(high_values) or len(low_values) < 2:
        return None
    low = np.asarray(low_values, dtype=np.int64)
    high = np.asarray(high_values, dtype=np.int64)
    dlow = np.diff(low)
    dhigh = np.diff(high)

    wrap_mask = np.abs(dlow) >= _WRAP_JUMP_THRESHOLD
    wrap_count = int(wrap_mask.sum())
    if wrap_count == 0:
        return MultiByteHint(
            low_byte_index=low_byte_index,
            high_byte_index=high_byte_index,
            coincidence_ratio=0.0,
            wrap_count=0,
            is_multi_byte=False,
        )

    carried = np.abs(dhigh[wrap_mask]) == 1
    coincidence_ratio = float(carried.sum()) / wrap_count
    return MultiByteHint(
        low_byte_index=low_byte_index,
        high_byte_index=high_byte_index,
        coincidence_ratio=coincidence_ratio,
        wrap_count=wrap_count,
        is_multi_byte=coincidence_ratio >= _COINCIDENCE_THRESHOLD,
    )


def format_multi_byte_hint(hint: MultiByteHint | None) -> str:
    """Always describes the actual measured evidence -- never hides a weak result
    behind the confidence threshold. hint is None only when there wasn't enough
    data to compute anything (see detect_carry_alignment)."""
    if hint is None:
        return ""
    if hint.wrap_count == 0:
        return f"B{hint.high_byte_index}: no wrap events observed"
    verdict = ", likely 16-bit" if hint.is_multi_byte else ""
    return f"pairs with B{hint.high_byte_index} ({hint.coincidence_ratio:.0%} carry over {hint.wrap_count} wrap(s){verdict})"
