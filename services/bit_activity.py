from __future__ import annotations

from dataclasses import dataclass, field
import math
from collections.abc import Callable

import polars as pl

from config.app_config import get_option
from utils.can_id import can_id_sort_key

MAX_BYTES = 8
BITS_PER_BYTE = 8
HISTOGRAM_BINS = 256
MIN_COUNTER_SAMPLES = int(get_option("bit_activity_min_counter_samples", 9))
MIN_CRC_SAMPLES = int(get_option("bit_activity_min_crc_samples", 16))


@dataclass(frozen=True)
class BitSignalSuggestion:
    start_bit: int
    length: int
    kind: str
    sample_count: int


@dataclass(frozen=True)
class ByteHistogram:
    byte_index: int
    sample_count: int
    counts: tuple[int, ...]


@dataclass(frozen=True)
class BitActivitySnapshot:
    can_id: str
    frame_count: int
    bit_flip_counts: tuple[int, ...]
    bit_comparison_counts: tuple[int, ...]
    flip_rates: tuple[float | None, ...]
    magnitudes: tuple[float | None, ...]
    boundaries: tuple[int, ...]
    suggestions: tuple[BitSignalSuggestion, ...]
    byte_histograms: tuple[ByteHistogram, ...]


class BitActivityCanceled(Exception):
    """Raised when the caller cancels a full bit activity rebuild."""

    pass


@dataclass
class _CanIdActivity:
    frame_count: int = 0
    previous: tuple[int, ...] | None = None
    flips: list[int] = field(default_factory=list)
    comparisons: list[int] = field(default_factory=list)
    observations: list[int] = field(default_factory=list)
    histograms: list[list[int]] = field(default_factory=list)
    byte_samples: list[int] = field(default_factory=list)

    def ingest(self, payload: tuple[int, ...]) -> None:
        self.frame_count += 1
        self._ensure_bit_capacity(len(payload) * BITS_PER_BYTE)
        for bit_index in range(len(payload) * BITS_PER_BYTE):
            self.observations[bit_index] += 1
        while len(self.histograms) < len(payload):
            self.histograms.append([0] * HISTOGRAM_BINS)
            self.byte_samples.append(0)
        for byte_index, value in enumerate(payload):
            self.histograms[byte_index][value] += 1
            self.byte_samples[byte_index] += 1

        if self.previous is not None:
            compared_bits = min(len(self.previous), len(payload)) * BITS_PER_BYTE
            self._ensure_bit_capacity(compared_bits)
            for bit_index in range(compared_bits):
                byte_index, bit_in_byte = divmod(bit_index, BITS_PER_BYTE)
                self.comparisons[bit_index] += 1
                if ((self.previous[byte_index] ^ payload[byte_index]) >> bit_in_byte) & 1:
                    self.flips[bit_index] += 1
        self.previous = payload

    def _ensure_bit_capacity(self, bit_count: int) -> None:
        missing = bit_count - len(self.flips)
        if missing > 0:
            self.flips.extend([0] * missing)
            self.comparisons.extend([0] * missing)
            self.observations.extend([0] * missing)


class BitActivityAccumulator:
    """Keep bounded per-ID bit transitions and byte histograms from new frames."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._ids: dict[str, _CanIdActivity] = {}

    def seed(
        self,
        dataframe: pl.DataFrame | None,
        *,
        should_cancel: Callable[[], bool] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> tuple[BitActivitySnapshot, ...]:
        self.reset()
        self.ingest(dataframe, should_cancel=should_cancel, on_progress=on_progress)
        return self.snapshot()

    def ingest(
        self,
        dataframe: pl.DataFrame | None,
        *,
        should_cancel: Callable[[], bool] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> tuple[BitActivitySnapshot, ...]:
        if dataframe is None or dataframe.is_empty():
            return ()
        changed: set[str] = set()
        required = {"ID", "LEN", *(f"D{i}" for i in range(MAX_BYTES))}
        if not required.issubset(dataframe.columns):
            return ()
        columns = ["ID", "LEN", *(f"D{i}" for i in range(MAX_BYTES))]
        total = dataframe.height
        progress_step = max(total // 100, 1)
        for index, row in enumerate(dataframe.select(columns).iter_rows(named=True), start=1):
            if should_cancel is not None and should_cancel():
                raise BitActivityCanceled()
            if on_progress is not None and (index % progress_step == 0 or index == total):
                on_progress(index, total)
            can_id = str(row["ID"] or "").strip().upper().removeprefix("0X")
            if not can_id:
                continue
            try:
                length = int(row["LEN"])
                payload = tuple(int(row[f"D{i}"]) & 0xFF for i in range(length))
            except (TypeError, ValueError, KeyError):
                continue
            if length < 0 or length > MAX_BYTES:
                continue
            self._ids.setdefault(can_id, _CanIdActivity()).ingest(payload)
            changed.add(can_id)
        return tuple(self._snapshot(can_id) for can_id in sorted(changed, key=can_id_sort_key))

    def snapshot(self) -> tuple[BitActivitySnapshot, ...]:
        return tuple(self._snapshot(can_id) for can_id in sorted(self._ids, key=can_id_sort_key))

    def _snapshot(self, can_id: str) -> BitActivitySnapshot:
        activity = self._ids[can_id]
        rates: list[float | None] = []
        magnitudes: list[float | None] = []
        for flips, comparisons in zip(activity.flips, activity.comparisons):
            rate = flips / comparisons if comparisons else None
            rates.append(rate)
            magnitudes.append(math.log10(rate) if rate and rate > 0 else None)
        boundaries = _suggest_boundaries(magnitudes)
        suggestions = _suggest_segments(rates, boundaries, activity.observations)
        histograms = tuple(
            ByteHistogram(index, activity.byte_samples[index], tuple(counts))
            for index, counts in enumerate(activity.histograms)
        )
        return BitActivitySnapshot(
            can_id=can_id,
            frame_count=activity.frame_count,
            bit_flip_counts=tuple(activity.flips),
            bit_comparison_counts=tuple(activity.comparisons),
            flip_rates=tuple(rates),
            magnitudes=tuple(magnitudes),
            boundaries=boundaries,
            suggestions=suggestions,
            byte_histograms=histograms,
        )


def _suggest_boundaries(magnitudes: list[float | None]) -> tuple[int, ...]:
    result: list[int] = []
    read_order = tuple(reversed(range(len(magnitudes))))
    for order_index in range(1, len(read_order)):
        previous_bit = read_order[order_index - 1]
        current_bit = read_order[order_index]
        previous = magnitudes[previous_bit]
        current = magnitudes[current_bit]
        if previous is not None and current is not None and current < previous:
            result.append(max(previous_bit, current_bit))
    return tuple(sorted(set(result)))


def _suggest_segments(
    rates: list[float | None],
    boundaries: tuple[int, ...],
    observations: list[int],
    *,
    allow_crc: bool = True,
) -> tuple[BitSignalSuggestion, ...]:
    if not rates:
        return ()
    crc_start = _crc_suffix_start(rates, _sample_count(observations, 0, len(rates))) if allow_crc else None
    if crc_start is not None:
        prefix_boundaries = tuple(boundary for boundary in boundaries if boundary < crc_start)
        prefix = list(_suggest_segments(rates[:crc_start], prefix_boundaries, observations[:crc_start], allow_crc=False))
        prefix.append(BitSignalSuggestion(
            crc_start,
            len(rates) - crc_start,
            "crc",
            _sample_count(observations, crc_start, len(rates) - crc_start),
        ))
        return tuple(sorted(prefix, key=lambda item: item.start_bit))
    starts = (0, *boundaries)
    ends = (*boundaries, len(rates))
    suggestions: list[BitSignalSuggestion] = []
    for start, end in zip(starts, ends):
        segment_rates = rates[start:end]
        sample_count = _sample_count(observations, start, end - start)
        read_rates = list(reversed(segment_rates))
        counter = _counter_suffix_start(read_rates) if sample_count >= MIN_COUNTER_SAMPLES else None
        if counter is not None:
            physical_length = end - start - counter
            suggestions.append(BitSignalSuggestion(
                start, counter, "counter", _sample_count(observations, start, counter)
            ))
            if physical_length > 0:
                _append_activity_groups(
                    suggestions,
                    start + counter,
                    segment_rates[counter:],
                    observations[start + counter:end],
                )
        elif _looks_like_crc(segment_rates, sample_count):
            suggestions.append(BitSignalSuggestion(start, end - start, "crc", sample_count))
        else:
            _append_activity_groups(suggestions, start, segment_rates, observations[start:end])
    return tuple(sorted((item for item in suggestions if item.length > 0), key=lambda item: item.start_bit))


def _append_activity_groups(
    suggestions: list[BitSignalSuggestion],
    start_bit: int,
    rates: list[float | None],
    observations: list[int],
) -> None:
    groups = [
        ("insufficient" if rate is None else "constant" if rate == 0.0 else "physical", samples)
        for rate, samples in zip(rates, observations)
    ]
    group_start = 0
    for index in range(1, len(groups) + 1):
        if index == len(groups) or groups[index] != groups[group_start]:
            suggestions.append(BitSignalSuggestion(
                start_bit + group_start,
                index - group_start,
                groups[group_start][0],
                groups[group_start][1],
            ))
            group_start = index


def _sample_count(observations: list[int], start: int, length: int) -> int:
    segment = observations[start:start + length]
    return min(segment) if segment else 0


def _counter_suffix_start(rates: list[float | None]) -> int | None:
    for start in range(len(rates)):
        candidate = rates[start:]
        if len(candidate) < 2 or any(rate is None or rate <= 0 for rate in candidate):
            continue
        values = [float(rate) for rate in candidate]
        if max(values) < 0.9:
            continue
        if all(_approximately_doubles(a, b) for a, b in zip(values, values[1:])):
            return len(rates) - start
    return None


def _approximately_doubles(first: float, second: float) -> bool:
    ratio = max(first, second) / min(first, second) if min(first, second) > 0 else math.inf
    return abs(ratio - 2.0) <= 0.25


def _looks_like_crc(rates: list[float | None], sample_count: int) -> bool:
    values = [float(rate) for rate in rates if rate is not None]
    if sample_count < MIN_CRC_SAMPLES or len(values) < 4 or len(values) != len(rates):
        return False
    mean = sum(values) / len(values)
    return 0.2 <= min(values) and max(values) <= 0.8 and abs(mean - 0.5) <= 0.1


def _crc_suffix_start(rates: list[float | None], sample_count: int) -> int | None:
    if sample_count < MIN_CRC_SAMPLES:
        return None
    for start in range(len(rates) - 3):
        if _looks_like_crc(rates[start:], sample_count):
            return start
    return None
