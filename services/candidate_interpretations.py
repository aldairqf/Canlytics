"""Pure logic for candidate signal interpretation.

The brute-force search over (frame length, mux case, signal length, byte order,
start bit, value type) lives here, Qt-free and testable. The ViewModel only drives
this from a worker thread and turns the results into signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np
import polars as pl

from models.frame_selector import FrameSelector
from models.mux_config import MuxConfigEntry
from models.signal import Signal as DecodedSignal
from services.analyze_data import mux_label_expr
from services.can_decoder import decode_signal, with_data_int, with_id_columns
from services.multi_byte_detection import MultiByteHint, detect_carry_alignment, format_multi_byte_hint
from services.range_diff import observe_byte
from utils.can_id import can_id_sort_key
from utils.dbc_payload import DbcPayload
from utils.plot_sampling import minmax_downsample


@dataclass(frozen=True)
class CandidateSeries:
    label: str
    x: list[float]
    y: list[float]
    color: str


class SignalCategory:
    """Behavioral bucket for the Matrix view and the Category filter -- derived
    display-time from stats already computed per candidate, never a search input."""
    COUNTER = "counter"
    BINARY = "binary"
    ENUM = "enum"
    ANALOG = "analog"
    CONSTANT = "constant"
    OTHER = "other"


_ENUM_MAX_DISTINCT = 16  # discrete states rarely exceed this many values
_ENUM_MAX_CHANGE_RATIO = 0.5  # a real enum holds steady between jumps
_ANALOG_MIN_AUTOCORRELATION = 0.5  # smooth/continuous vs. noisy/checksum-like -- folds into Other


def classify_signal_type(
    *, distinct_values: int, changes: int, values: Sequence[float], signal_length: int, value_type: str,
) -> str:
    if distinct_values <= 1:
        return SignalCategory.CONSTANT
    if distinct_values == 2:
        return SignalCategory.BINARY
    if signal_length == 8 and value_type == "Unsigned" and observe_byte([int(v) for v in values]).looks_counter:
        return SignalCategory.COUNTER
    change_ratio = changes / max(1, len(values) - 1)
    if distinct_values <= _ENUM_MAX_DISTINCT and change_ratio < _ENUM_MAX_CHANGE_RATIO:
        return SignalCategory.ENUM
    if _autocorrelation(list(values)) >= _ANALOG_MIN_AUTOCORRELATION:
        return SignalCategory.ANALOG
    return SignalCategory.OTHER


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
    multi_byte_hint: str = ""  # P2.2: non-empty if this whole-byte candidate carry-aligns with a neighbor
    is_multi_byte_fragment: bool = False  # this byte is one half of a flagged carry pair
    signal_category: str = SignalCategory.OTHER


class CandidateInterpretationsCanceled(Exception):
    pass


@dataclass(frozen=True)
class CandidateMatrixEntry:
    """One Matrix cell: an already-found candidate's own decoded series, not a raw byte scan."""
    label: str  # CandidateItem.label -- identity for click-through to the results list
    can_id: str
    title: str  # compact cell caption
    score: float
    series: CandidateSeries
    signal_category: str


_MATRIX_COLOR = "#1E74E6"


def build_candidate_matrix_entries(
    items: Sequence[CandidateItem], *, max_points: int = 150
) -> list[CandidateMatrixEntry]:
    """Cheap and synchronous -- every CandidateItem already carries its own decoded
    (timestamps, values), so this is just a decimation pass, not a recompute."""
    entries: list[CandidateMatrixEntry] = []
    for item in items:
        if not item.timestamps or not item.values:
            continue
        x = np.asarray(item.timestamps, dtype=float)
        y = np.asarray(item.values, dtype=float)
        dx, dy = minmax_downsample(x, y, max_points)
        title = f"{item.can_id}  b{item.start_bit}/{item.signal_length} {item.value_type}"
        entries.append(
            CandidateMatrixEntry(
                label=item.label,
                can_id=item.can_id,
                title=title,
                score=item.score,
                series=CandidateSeries(label=item.label, x=dx, y=dy, color=_MATRIX_COLOR),
                signal_category=item.signal_category,
            )
        )
    return entries


def _iter_signal_specs(
    *,
    available_bits: int,
    mux_bytes: tuple[int, ...],
    min_length: int,
    max_length: int,
    granularity: int,
    endianness: str,
    value_type: str,
):
    """Every spec this search would try -- pure parameter enumeration, no dataframe access."""
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
                    yield signal_length, byte_order, is_little, start_bit, type_label, type_name


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
    include_constant: bool = False,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[CandidateItem]:
    if df is None or df.is_empty() or not checked_ids:
        return []

    # Planning pass: count specs per group cheaply, regenerate them (don't store) in the pass below.
    groups: list[tuple[str, int, str, tuple[int, ...], pl.DataFrame, int]] = []
    total = 0
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
            available_bits = int(frame_len) * 8
            for mux_label, mux_df in _split_by_mux_case(len_df, mux_bytes):
                _raise_if_canceled(should_cancel)
                spec_count = sum(
                    1
                    for _ in _iter_signal_specs(
                        available_bits=available_bits,
                        mux_bytes=mux_bytes,
                        min_length=min_length,
                        max_length=max_length,
                        granularity=granularity,
                        endianness=endianness,
                        value_type=value_type,
                    )
                )
                if not spec_count:
                    continue
                groups.append((can_id, frame_len, mux_label, mux_bytes, mux_df, available_bits))
                total += spec_count

    results: list[CandidateItem] = []
    done = 0
    for can_id, frame_len, mux_label, mux_bytes, mux_df, available_bits in groups:
        # Precompute once per group instead of once per spec (BUGS.md B-30): both
        # helpers are idempotent (a no-op if their columns already exist), so every
        # decode_signal() call below for this group reuses this instead of
        # re-parsing the DATA hex string / rebuilding _ID_INT from scratch --
        # measured ~5.32ms/call of pure waste eliminated per redundant call.
        mux_df = with_data_int(with_id_columns(mux_df))
        byte_hints = _multi_byte_hints_for_group(mux_df, available_bits)
        fragment_bytes = _fragment_byte_indices(byte_hints)
        specs = _iter_signal_specs(
            available_bits=available_bits,
            mux_bytes=mux_bytes,
            min_length=min_length,
            max_length=max_length,
            granularity=granularity,
            endianness=endianness,
            value_type=value_type,
        )
        for signal_length, byte_order, is_little, start_bit, type_label, type_name in specs:
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
            done += 1
            if on_progress is not None:
                on_progress(done, total)
            if not timestamps or not values:
                continue
            # Vectorized finite-filter/distinct-count/change-count; converted back to
            # plain lists right after so downstream scoring/formatting is untouched.
            values_arr = np.asarray(values, dtype=np.float64)
            finite_mask = np.isfinite(values_arr)
            if not finite_mask.any():
                continue
            clean_values_arr = values_arr[finite_mask]
            clean_timestamps_arr = np.asarray(timestamps, dtype=np.float64)[finite_mask]
            changes = (
                int(np.count_nonzero(np.abs(np.diff(clean_values_arr)) > 1e-9))
                if clean_values_arr.size > 1
                else 0
            )
            distinct_values = int(np.unique(np.round(clean_values_arr, 6)).size)
            clean_values = clean_values_arr.tolist()
            clean_timestamps = clean_timestamps_arr.tolist()
            score = _candidate_score(clean_values, changes, distinct_values)
            if not _passes_minimum_requirements(clean_values, distinct_values, include_constant=include_constant):
                continue

            multi_byte_hint = ""
            is_multi_byte_fragment = False
            if signal_length == 8 and start_bit % 8 == 0:
                byte_idx = start_bit // 8
                multi_byte_hint = format_multi_byte_hint(byte_hints.get(byte_idx))
                is_multi_byte_fragment = byte_idx in fragment_bytes

            signal_category = classify_signal_type(
                distinct_values=distinct_values,
                changes=changes,
                values=clean_values,
                signal_length=signal_length,
                value_type=type_label,
            )

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
                    multi_byte_hint=multi_byte_hint,
                    is_multi_byte_fragment=is_multi_byte_fragment,
                    signal_category=signal_category,
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
    """Vectorized (was a Python iter_rows() loop that then re-filtered the whole
    df once per distinct label -- O(n * distinct labels). Measured 1.6s on a real
    ~484K-row MUX-configured group; this is the same group_by-based label pass
    services.analyze_data.mux_label_expr() already uses for the Matrix/MUX-case UI."""
    if df.is_empty():
        return []
    if not mux_bytes:
        return [("None", df)]

    label_expr = mux_label_expr(mux_bytes)
    labeled = df.with_columns(
        pl.when(label_expr == "").then(pl.lit("None")).otherwise(label_expr).alias("_mux_label")
    )
    return [
        (label[0], group.drop("_mux_label"))
        for label, group in labeled.group_by("_mux_label", maintain_order=True)
    ]


def _multi_byte_hints_for_group(mux_df: pl.DataFrame, available_bits: int) -> dict[int, MultiByteHint]:
    """One carry-alignment check per adjacent byte pair in the frame, computed once
    for the whole group -- independent of decode_signal()/value_type/scale."""
    hints: dict[int, MultiByteHint] = {}
    for byte_idx in range(available_bits // 8 - 1):
        high_idx = byte_idx + 1
        low_col, high_col = f"D{byte_idx}", f"D{high_idx}"
        if low_col not in mux_df.columns or high_col not in mux_df.columns:
            continue
        pair = mux_df.select([low_col, high_col]).drop_nulls()
        if pair.height < 2:
            continue
        hint = detect_carry_alignment(
            pair[low_col].to_list(), pair[high_col].to_list(),
            low_byte_index=byte_idx, high_byte_index=high_idx,
        )
        if hint is not None:
            hints[byte_idx] = hint
    return hints


def _fragment_byte_indices(hints: dict[int, MultiByteHint]) -> set[int]:
    """Byte indices that are one half of a flagged (likely 16-bit) carry pair --
    both the low and high byte are fragments of the same real, wider signal."""
    fragments: set[int] = set()
    for low_idx, hint in hints.items():
        if hint.is_multi_byte:
            fragments.add(low_idx)
            fragments.add(hint.high_byte_index)
    return fragments


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


_SIZE_SCALE_REFERENCE_N = 30  # frame count at/above which sample size stops discounting confidence


def _autocorrelation(values: list[float]) -> float:
    """Lag-1 Pearson correlation -- abs() so a clean alternation counts as structure too."""
    if len(values) < 3:
        return 0.0
    a = np.asarray(values[:-1], dtype=np.float64)
    b = np.asarray(values[1:], dtype=np.float64)
    if a.std() < 1e-12 or b.std() < 1e-12:
        return 0.0
    return abs(float(np.corrcoef(a, b)[0, 1]))


def _size_scale(n: int) -> float:
    """Confidence discount for small samples."""
    return min(1.0, (n / _SIZE_SCALE_REFERENCE_N) ** 0.5)


def _candidate_score(values: list[float], changes: int, distinct_values: int) -> float:
    if len(values) < 2:
        return 0.0
    change_ratio = changes / max(1, len(values) - 1)
    distinct_ratio = min(1.0, (distinct_values - 1) / max(1, min(len(values) - 1, 16)))
    span_ratio = 1.0 if abs(max(values) - min(values)) > 1e-9 else 0.0
    shape_score = (0.5 * change_ratio) + (0.3 * distinct_ratio) + (0.2 * span_ratio)
    # Multiplicative gate -- additive would let noise's maxed-out ratios drown it out.
    smoothness_factor = 0.3 + 0.7 * _autocorrelation(values)
    raw_score = shape_score * smoothness_factor
    return max(0.0, min(raw_score, 1.0)) * _size_scale(len(values))


def _passes_minimum_requirements(
    values: list[float],
    distinct_values: int,
    *,
    include_constant: bool = False,
) -> bool:
    """Structural gate only -- no score threshold. The search is always exhaustive;
    ranking/filtering by score is display-time (CI1/CI2), not a recompute knob."""
    if len(values) < 2:
        return False
    if distinct_values < 2:
        return include_constant
    return True


def _raise_if_canceled(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel is not None and should_cancel():
        raise CandidateInterpretationsCanceled()


@dataclass(frozen=True)
class CandidateGroup:
    representative: CandidateItem  # highest score in the group
    members: tuple[CandidateItem, ...]  # sorted by score desc; members[0] is representative


def group_overlapping_candidates(items: Sequence[CandidateItem]) -> list[CandidateGroup]:
    """CI5: collapse every interpretation of the same bit range (e.g. "all the ways
    to read bytes 2-3") into one group, keeping the highest-scoring member as the
    representative. Display-time only -- operates on already-computed CandidateItems,
    never re-scans. Two candidates overlap only within the same (can_id, frame_len,
    mux_label): different frame layouts/mux cases don't share a bit-range space."""
    by_key: dict[tuple[str, int, str], list[CandidateItem]] = {}
    for item in items:
        by_key.setdefault((item.can_id, item.frame_len, item.mux_label), []).append(item)

    groups: list[CandidateGroup] = []
    for members_in_key in by_key.values():
        ordered = sorted(members_in_key, key=lambda it: it.start_bit)
        cluster: list[CandidateItem] = []
        cluster_end = None
        for item in ordered:
            item_end = item.start_bit + item.signal_length
            if cluster and item.start_bit < cluster_end:
                cluster.append(item)
                cluster_end = max(cluster_end, item_end)
            else:
                if cluster:
                    groups.append(_finalize_group(cluster))
                cluster = [item]
                cluster_end = item_end
        if cluster:
            groups.append(_finalize_group(cluster))

    groups.sort(key=lambda g: g.representative.score, reverse=True)
    return groups


def _finalize_group(cluster: list[CandidateItem]) -> CandidateGroup:
    ordered_members = tuple(sorted(cluster, key=lambda it: it.score, reverse=True))
    return CandidateGroup(representative=ordered_members[0], members=ordered_members)
