from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


TimeRange = tuple[float, float]


@dataclass(frozen=True)
class AnalysisContext:
    """Immutable evidence passed between analysis tools."""

    can_id: str | None = None
    byte_indices: tuple[int, ...] = ()
    bit_indices: tuple[int, ...] = ()
    time_range: TimeRange | None = None
    range_a: TimeRange | None = None
    range_b: TimeRange | None = None
    mux_case: int | str | None = None
    source_window: str = ""

    @classmethod
    def from_signal(
        cls,
        *,
        can_id: str | None,
        start_bit: int,
        length: int,
        little_endian: bool,
        source_window: str,
        time_range: TimeRange | None = None,
        mux_case: int | str | None = None,
    ) -> AnalysisContext:
        """Build a context using the signal's actual bit ordering."""
        positions = _signal_bit_positions(start_bit, length, little_endian)
        return cls(
            can_id=can_id,
            byte_indices=tuple(sorted({position // 8 for position in positions})),
            bit_indices=positions,
            time_range=time_range,
            mux_case=mux_case,
            source_window=source_window,
        )

    def __post_init__(self) -> None:
        object.__setattr__(self, "byte_indices", tuple(self.byte_indices))
        object.__setattr__(self, "bit_indices", tuple(self.bit_indices))
        for name in ("time_range", "range_a", "range_b"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, tuple(value))
        if self.can_id is not None and not str(self.can_id).strip():
            raise ValueError("can_id must be non-empty when provided")
        if any(index < 0 or index > 7 for index in self.byte_indices):
            raise ValueError("byte indices must be between 0 and 7")
        if any(index < 0 or index > 63 for index in self.bit_indices):
            raise ValueError("bit indices must be between 0 and 63")
        for time_range in (self.time_range, self.range_a, self.range_b):
            if time_range is not None and (
                len(time_range) != 2
                or not all(isfinite(value) for value in time_range)
                or time_range[0] > time_range[1]
            ):
                raise ValueError("time ranges must be finite ordered pairs")


def _signal_bit_positions(start_bit: int, length: int, little_endian: bool) -> tuple[int, ...]:
    if start_bit < 0 or start_bit >= 64 or length <= 0:
        raise ValueError("signal bit range is outside classic CAN payload")
    positions: list[int] = []
    if little_endian:
        positions = list(range(start_bit, start_bit + length))
    else:
        byte = start_bit // 8
        bit_in_byte = start_bit % 8
        for _ in range(length):
            positions.append(byte * 8 + bit_in_byte)
            if bit_in_byte > 0:
                bit_in_byte -= 1
            else:
                byte += 1
                bit_in_byte = 7
    if any(position < 0 or position >= 64 for position in positions):
        raise ValueError("signal bit range is outside classic CAN payload")
    return tuple(positions)
