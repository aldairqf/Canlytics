from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


TimeRange = tuple[float, float]


@dataclass(frozen=True)
class AnalysisMarker:
    sequence: int
    name: str
    timestamp: float
    state: str | None = None


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
    markers: tuple[AnalysisMarker, ...] = ()

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
        normalized_markers: list[AnalysisMarker] = []
        for marker in self.markers:
            if isinstance(marker, AnalysisMarker):
                normalized_markers.append(marker)
            elif isinstance(marker, dict):
                normalized_markers.append(
                    AnalysisMarker(
                        sequence=int(marker["sequence"]),
                        name=str(marker["name"]),
                        timestamp=float(marker["timestamp"]),
                        state=str(marker["state"]) if marker.get("state") is not None else None,
                    )
                )
            else:
                raise TypeError("markers must be AnalysisMarker instances or marker dictionaries")
        object.__setattr__(self, "markers", tuple(normalized_markers))
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
        if any(
            marker.sequence < 1 or not marker.name.strip() or not isfinite(marker.timestamp)
            for marker in self.markers
        ):
            raise ValueError("markers need a positive sequence, name, and finite timestamp")

    def suggested_signal_geometry(self) -> tuple[int, int, bool]:
        """Return start bit, length, and little-endian hint from captured evidence."""
        if self.bit_indices:
            bits = self.bit_indices
            if bits == tuple(range(bits[0], bits[0] + len(bits))):
                return bits[0], len(bits), True
            byte = bits[0] // 8
            bit = bits[0] % 8
            expected = []
            for _ in bits:
                expected.append(byte * 8 + bit)
                if bit > 0:
                    bit -= 1
                else:
                    byte += 1
                    bit = 7
            if bits == tuple(expected):
                return bits[0], len(bits), False
        if self.byte_indices:
            bytes_ = self.byte_indices
            if bytes_ == tuple(range(bytes_[0], bytes_[-1] + 1)):
                return bytes_[0] * 8, len(bytes_) * 8, True
            return bytes_[0] * 8, 8, True
        return 0, 8, True


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
