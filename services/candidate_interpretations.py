"""Pure logic for candidate signal interpretation.

The brute-force search over (frame length, mux case, signal length, byte order,
start bit, value type) lives here, Qt-free and testable. The ViewModel only drives
this from a worker thread and turns the results into signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import polars as pl

from models.frame_selector import FrameSelector
from models.mux_config import MuxConfigEntry
from models.signal import Signal as DecodedSignal
from services.can_decoder import decode_signal
from utils.can_id import can_id_sort_key
from utils.dbc_payload import DbcPayload


@dataclass(frozen=True)
class CandidateSeries:
    label: str
    x: list[float]
    y: list[float]
    color: str


@dataclass(frozen=True)
class CandidateItem:
    label: str
    can_id: str
    frame_len: int
    mux_label: str
    mux_start: int
    mux_bytes: int
    mux_value: int | None
    start_bit: int
    signal_length: int
    byte_order: str
    value_type: str
    frames: int
    changes: int
    distinct_values: int
    score: float
    min_value: float | None
    max_value: float | None
    sample_values: tuple[str, ...]
    timestamps: tuple[float, ...]
    values: tuple[float, ...]


class CandidateInterpretationsCanceled(Exception):
    pass


def _build_candidate_items(
    df: pl.DataFrame,
    *,
    checked_ids: set[str],
    mux_configs: list[MuxConfigEntry],
    min_length: int,
    max_length: int,
    granularity: int,
    endianness: str,
    value_type: str,
    sensitivity: int,
    should_cancel: Callable[[], bool] | None = None,
) -> list[CandidateItem]:
    if df is None or df.is_empty() or not checked_ids:
        return []

    results: list[CandidateItem] = []
    for can_id in sorted(checked_ids, key=can_id_sort_key):
        _raise_if_canceled(should_cancel)
        can_df = df.filter(pl.col("ID") == can_id)
        if can_df.is_empty() or "LEN" not in can_df.columns:
            continue

        observed_lens = sorted({int(value) for value in can_df["LEN"].to_list() if value is not None})
        for frame_len in observed_lens:
            _raise_if_canceled(should_cancel)
            len_df = can_df.filter(pl.col("LEN").cast(pl.Int64) == frame_len)
            if len_df.is_empty():
                continue

            mux_bytes = _mux_bytes_for_group(mux_configs, can_id, frame_len)
            for mux_label, mux_df in _split_by_mux_case(len_df, mux_bytes):
                _raise_if_canceled(should_cancel)
                available_bits = int(frame_len) * 8
                for signal_length in _iter_signal_lengths(min_length, max_length, granularity):
                    if signal_length > available_bits:
                        continue
                    for byte_order, is_little in _byte_order_options(endianness):
                        for start_bit in _iter_start_bits(
                            available_bits=available_bits,
                            signal_length=signal_length,
                            granularity=granularity,
                            is_little=is_little,
                        ):
                            if _overlaps_mux_bytes(
                                start_bit=start_bit,
                                signal_length=signal_length,
                                mux_bytes=mux_bytes,
                                is_little=is_little,
                                available_bits=available_bits,
                            ):
                                continue
                            for type_label, type_name in _value_type_options(value_type, signal_length):
                                _raise_if_canceled(should_cancel)
                                signal = DecodedSignal(
                                    name=f"{can_id}_{frame_len}_{mux_label}_{start_bit}_{signal_length}_{byte_order}_{type_label}",
                                    can_id=can_id,
                                    start_bit=start_bit,
                                    length=signal_length,
                                    le=is_little,
                                    type_data=type_name,
                                )
                                timestamps, values = decode_signal(
                                    mux_df,
                                    signal,
                                    FrameSelector(selected_id=can_id, mode="exact"),
                                )
                                if not timestamps or not values:
                                    continue
                                clean_values = [float(v) for v in values if _is_finite_number(v)]
                                clean_timestamps = [
                                    float(ts)
                                    for ts, value in zip(timestamps, values)
                                    if _is_finite_number(value)
                                ]
                                if not clean_values:
                                    continue
                                changes = sum(
                                    1
                                    for prev, curr in zip(clean_values, clean_values[1:])
                                    if abs(curr - prev) > 1e-9
                                )
                                distinct_values = len({round(v, 6) for v in clean_values})
                                score = _candidate_score(clean_values, changes, distinct_values)
                                if not _passes_sensitivity(score, distinct_values, clean_values, sensitivity):
                                    continue
                                results.append(
                                    CandidateItem(
                                        label=(
                                            f"ID: {can_id} LEN: {frame_len} MUX: {mux_label} "
                                            f"startBit: {start_bit} sigLen: {signal_length} "
                                            f"{type_label} {byte_order}"
                                        ),
                                        can_id=can_id,
                                        frame_len=frame_len,
                                        mux_label=mux_label,
                                        mux_start=min(mux_bytes) if mux_bytes else 0,
                                        mux_bytes=len(mux_bytes),
                                        mux_value=_parse_mux_case_value(mux_label, mux_bytes),
                                        start_bit=start_bit,
                                        signal_length=signal_length,
                                        byte_order=byte_order,
                                        value_type=type_label,
                                        frames=len(clean_values),
                                        changes=changes,
                                        distinct_values=distinct_values,
                                        score=score,
                                        min_value=min(clean_values),
                                        max_value=max(clean_values),
                                        sample_values=tuple(_format_number(v) for v in clean_values[:6]),
                                        timestamps=tuple(clean_timestamps),
                                        values=tuple(clean_values),
                                    )
                                )
    return results


def _iter_signal_lengths(min_length: int, max_length: int, granularity: int):
    current = min_length
    seen: set[int] = set()
    while current <= max_length:
        if current not in seen:
            seen.add(current)
            yield current
        current += max(1, granularity)
    if max_length not in seen:
        yield max_length


def _mux_bytes_for_group(configs: list[MuxConfigEntry], can_id: str, frame_len: int) -> tuple[int, ...]:
    for cfg in configs:
        if cfg.can_id == can_id and cfg.length == frame_len:
            return cfg.mux_bytes
    for cfg in configs:
        if cfg.can_id == can_id and cfg.length is None:
            return cfg.mux_bytes
    return ()


def _split_by_mux_case(df: pl.DataFrame, mux_bytes: tuple[int, ...]) -> list[tuple[str, pl.DataFrame]]:
    if df.is_empty():
        return []
    if not mux_bytes:
        return [("None", df)]

    buckets: dict[str, list[int]] = {}
    for idx, row in enumerate(df.iter_rows(named=True)):
        label = " ".join(str(row.get(f"B{i}") or "").upper() for i in mux_bytes)
        buckets.setdefault(label or "None", []).append(idx)

    results: list[tuple[str, pl.DataFrame]] = []
    for label, indexes in buckets.items():
        grouped_df = (
            df.with_row_index("_row_index")
            .filter(pl.col("_row_index").is_in(indexes))
            .drop("_row_index")
        )
        results.append((label, grouped_df))
    return results


def _iter_start_bits(*, available_bits: int, signal_length: int, granularity: int, is_little: bool):
    step = max(1, granularity)
    if is_little:
        max_start = max(0, available_bits - signal_length)
        yield from range(0, max_start + 1, step)
        return

    offset = max(0, step - 1)
    seen: set[int] = set()
    for start_bit in range(offset, available_bits, step):
        positions = _bit_positions(
            start_bit=start_bit,
            signal_length=signal_length,
            is_little=is_little,
            available_bits=available_bits,
        )
        if positions is None or start_bit in seen:
            continue
        seen.add(start_bit)
        yield start_bit


def _bit_positions(*, start_bit: int, signal_length: int, is_little: bool, available_bits: int) -> list[int] | None:
    if start_bit < 0 or start_bit >= available_bits or signal_length <= 0:
        return None

    positions: list[int] = []
    if is_little:
        end_bit = start_bit + signal_length - 1
        if end_bit >= available_bits:
            return None
        return list(range(start_bit, end_bit + 1))

    byte = start_bit // 8
    bit_in_byte = start_bit % 8
    for _ in range(signal_length):
        bit_index = byte * 8 + bit_in_byte
        if bit_index < 0 or bit_index >= available_bits:
            return None
        positions.append(bit_index)
        if bit_in_byte > 0:
            bit_in_byte -= 1
        else:
            byte += 1
            bit_in_byte = 7
    return positions


def _overlaps_mux_bytes(
    *,
    start_bit: int,
    signal_length: int,
    mux_bytes: tuple[int, ...],
    is_little: bool,
    available_bits: int,
) -> bool:
    if not mux_bytes:
        return False
    positions = _bit_positions(
        start_bit=start_bit,
        signal_length=signal_length,
        is_little=is_little,
        available_bits=available_bits,
    )
    if positions is None:
        return True
    covered_bits = set(positions)
    for mux_byte in mux_bytes:
        mux_bit_range = set(range(mux_byte * 8, mux_byte * 8 + 8))
        if covered_bits & mux_bit_range:
            return True
    return False


def _parse_mux_case_value(mux_label: str, mux_bytes: tuple[int, ...]) -> int | None:
    if not mux_bytes:
        return None

    parts = [part.strip() for part in str(mux_label or "").split() if part.strip()]
    if len(parts) != len(mux_bytes):
        return None

    try:
        values = bytes(int(part, 16) for part in parts)
    except ValueError:
        return None

    return DbcPayload.mux_value(values, 0, len(values))


def _byte_order_options(mode: str) -> list[tuple[str, bool]]:
    if mode == "Little Endian":
        return [("LittleEndian", True)]
    if mode == "Big Endian":
        return [("BigEndian", False)]
    return [("LittleEndian", True), ("BigEndian", False)]


def _value_type_options(mode: str, bit_length: int) -> list[tuple[str, str]]:
    if mode == "Unsigned":
        return [("Unsigned", "uint")]
    if mode == "Signed":
        return [("Signed", "int")]
    if mode == "Float32":
        return [("Float32", "float32")] if bit_length == 32 else []
    result = [("Unsigned", "uint"), ("Signed", "int")]
    if bit_length == 32:
        result.append(("Float32", "float32"))
    return result


def _format_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _is_finite_number(value) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and number not in (float("inf"), float("-inf"))


def _candidate_score(values: list[float], changes: int, distinct_values: int) -> float:
    if len(values) < 2:
        return 0.0
    change_ratio = changes / max(1, len(values) - 1)
    distinct_ratio = min(1.0, (distinct_values - 1) / max(1, min(len(values) - 1, 16)))
    span_ratio = 1.0 if abs(max(values) - min(values)) > 1e-9 else 0.0
    score = (0.5 * change_ratio) + (0.35 * distinct_ratio) + (0.15 * span_ratio)
    return max(0.0, min(score, 1.0))


def _passes_sensitivity(score: float, distinct_values: int, values: list[float], sensitivity: int) -> bool:
    if len(values) < 2 or distinct_values < 2:
        return False
    strictness = max(0, min(int(sensitivity), 100)) / 100.0
    threshold = 0.1 + (0.7 * strictness)
    return score >= threshold


def _raise_if_canceled(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel is not None and should_cancel():
        raise CandidateInterpretationsCanceled()
