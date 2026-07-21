"""Range Diff: byte-level classification of what changed between two time windows, no DBC required."""

from __future__ import annotations

import csv
import dataclasses
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum

import numpy as np
import polars as pl

from services.multi_byte_detection import detect_carry_alignment, format_multi_byte_hint

_COUNTER_RATIO = 0.85
_PRESENCE_SCORE = 0.3


class RangeDiffCanceled(Exception):
    pass


class ChangeType(str, Enum):
    UNCHANGED = "unchanged"
    SAME_OSCILLATION = "same_oscillation"
    CONST_SHIFT = "const_shift"
    NEW_TERRITORY = "new_territory"
    RANGE_SHIFT = "range_shift"


_BASE_WEIGHT = {
    ChangeType.CONST_SHIFT: 1.0,
    ChangeType.NEW_TERRITORY: 0.8,
    ChangeType.RANGE_SHIFT: 0.5,
    ChangeType.SAME_OSCILLATION: 0.1,
    ChangeType.UNCHANGED: 0.0,
}


@dataclass(frozen=True)
class TimeRange:
    start: float
    end: float


@dataclass(frozen=True)
class ByteObservation:
    """Reduction of one byte's raw values over one window."""

    n_frames: int
    values: tuple[int, ...]  # distinct, sorted
    raw: tuple[int, ...]  # every observed value, in capture order -- feeds classify_byte's significance test
    vmin: int
    vmax: int
    mean: float
    first: int  # first value in TS order
    last: int  # last value in TS order
    change_ratio: float  # fraction of consecutive frames where the byte changed
    looks_counter: bool  # monotonic mod-256 increment, or toggles between 2 values almost always


@dataclass(frozen=True)
class ByteDiff:
    byte_index: int
    change_type: ChangeType
    a: ByteObservation
    b: ByteObservation
    new_values: tuple[int, ...]  # SB - SA (territory gained)
    lost_values: tuple[int, ...]  # SA - SB (values lost)
    delta_mean: float  # b.mean - a.mean
    is_counter: bool  # a.looks_counter and b.looks_counter -- overlay, orthogonal to change_type
    score: float
    p_value: float | None  # Mann-Whitney U two-sided p-value over a.raw/b.raw; None when not computable
    multi_byte_hint: str = ""  # P2.3: non-empty if this byte carry-aligns with the next one


@dataclass(frozen=True)
class IdDiff:
    can_id: str
    presence: str  # "both" | "only_a" | "only_b"
    frames_a: int
    frames_b: int
    len_a: tuple[int, ...]
    len_b: tuple[int, ...]
    len_changed: bool
    byte_diffs: tuple[ByteDiff, ...]  # every byte compared, including UNCHANGED
    score: float
    dbc_hint: str | None  # DBC signal name(s) covering a changed byte, if any DBC is loaded


@dataclass(frozen=True)
class DiffOptions:
    ignore_same_oscillation: bool = True
    ignore_counters: bool = True
    only_new_territory: bool = False
    include_presence: bool = True
    min_frames: int = 3
    require_significance: bool = False  # gate byte-diffs on the Mann-Whitney p_value below
    significance_alpha: float = 0.05


@dataclass(frozen=True)
class RangeDiffReport:
    range_a: TimeRange
    range_b: TimeRange
    ids: tuple[IdDiff, ...]  # full classification, unfiltered

    def visible(self, opts: DiffOptions) -> list[IdDiff]:
        result = [v for v in (_visible_id(id_diff, opts) for id_diff in self.ids) if v is not None]
        result.sort(key=lambda item: item.score, reverse=True)
        return result


def observe_byte(values: Sequence[int]) -> ByteObservation:
    arr = np.asarray(values, dtype=np.int64)
    distinct = tuple(int(v) for v in np.unique(arr))
    diffs = np.diff(arr) if arr.size > 1 else np.array([], dtype=np.int64)
    change_ratio = float(np.count_nonzero(diffs != 0)) / float(diffs.size) if diffs.size else 0.0
    return ByteObservation(
        n_frames=int(arr.size),
        values=distinct,
        raw=tuple(int(v) for v in arr),
        vmin=int(arr.min()),
        vmax=int(arr.max()),
        mean=float(arr.mean()),
        first=int(arr[0]),
        last=int(arr[-1]),
        change_ratio=change_ratio,
        looks_counter=_looks_like_counter(arr, diffs),
    )


def _looks_like_counter(arr: np.ndarray, diffs: np.ndarray) -> bool:
    if diffs.size == 0:
        return False
    increasing_ratio = float(np.count_nonzero((diffs == 1) | (diffs == -255))) / float(diffs.size)
    if increasing_ratio >= _COUNTER_RATIO:
        return True
    if np.unique(arr).size == 2:
        toggle_ratio = float(np.count_nonzero(diffs != 0)) / float(diffs.size)
        return toggle_ratio >= _COUNTER_RATIO
    return False


def classify_byte(a: ByteObservation, b: ByteObservation) -> ByteDiff:
    sa, sb = set(a.values), set(b.values)
    new_values = tuple(sorted(sb - sa))
    lost_values = tuple(sorted(sa - sb))

    if sa == sb:
        change_type = ChangeType.UNCHANGED if len(sa) == 1 else ChangeType.SAME_OSCILLATION
    elif len(sa) == 1 and len(sb) == 1:
        change_type = ChangeType.CONST_SHIFT
    elif new_values:
        change_type = ChangeType.NEW_TERRITORY
    else:
        change_type = ChangeType.RANGE_SHIFT

    is_counter = a.looks_counter and b.looks_counter
    delta_mean = b.mean - a.mean

    return ByteDiff(
        byte_index=-1,  # position is unknown to classify_byte -- the caller fills it in
        change_type=change_type,
        a=a,
        b=b,
        new_values=new_values,
        lost_values=lost_values,
        delta_mean=delta_mean,
        is_counter=is_counter,
        score=_byte_score(change_type, delta_mean, is_counter),
        p_value=_mann_whitney_p(a.raw, b.raw),
    )


def _byte_score(change_type: ChangeType, delta_mean: float, is_counter: bool) -> float:
    magnitude = min(1.0, abs(delta_mean) / 255.0)
    score = _BASE_WEIGHT[change_type] * (0.5 + 0.5 * magnitude)
    return score * (0.2 if is_counter else 1.0)


def _mann_whitney_p(a_raw: Sequence[int], b_raw: Sequence[int]) -> float | None:
    """Two-sided Mann-Whitney U p-value over the raw a/b sequences; None if not computable."""
    if len(a_raw) < 2 or len(b_raw) < 2:
        return None
    if len(set(a_raw) | set(b_raw)) < 2:
        return None
    try:
        from scipy.stats import mannwhitneyu
    except ImportError:
        return None
    try:
        _, p_value = mannwhitneyu(a_raw, b_raw, alternative="two-sided")
    except ValueError:
        return None
    return float(p_value)


def slice_window(df: pl.DataFrame, r: TimeRange) -> pl.DataFrame:
    return df.filter((pl.col("TS") >= r.start) & (pl.col("TS") <= r.end))


def frame_density(df: pl.DataFrame, *, buckets: int) -> tuple[list[float], list[int]]:
    if df is None or df.is_empty() or buckets <= 0:
        return [], []
    ts = df.get_column("TS").to_numpy()
    tmin, tmax = float(ts.min()), float(ts.max())
    if tmax <= tmin:
        return [tmin, tmin + 1.0], [int(ts.size)]
    counts, edges = np.histogram(ts, bins=buckets, range=(tmin, tmax))
    return edges.tolist(), counts.tolist()


def build_range_diff_report(
    df: pl.DataFrame,
    range_a: TimeRange,
    range_b: TimeRange,
    *,
    dbc_manager=None,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> RangeDiffReport:
    if df is None or df.is_empty():
        return RangeDiffReport(range_a=range_a, range_b=range_b, ids=())

    parts_a = _partition_by_id(slice_window(df, range_a))
    parts_b = _partition_by_id(slice_window(df, range_b))
    all_ids = sorted(set(parts_a) | set(parts_b))
    total = len(all_ids)

    ids: list[IdDiff] = []
    for done, can_id in enumerate(all_ids, start=1):
        if should_cancel is not None and should_cancel():
            raise RangeDiffCanceled()
        ids.append(_diff_for_id(can_id, parts_a.get(can_id), parts_b.get(can_id), dbc_manager))
        if on_progress is not None:
            on_progress(done, total)

    ids.sort(key=lambda item: item.score, reverse=True)
    return RangeDiffReport(range_a=range_a, range_b=range_b, ids=tuple(ids))


def _partition_by_id(df: pl.DataFrame) -> dict[str, pl.DataFrame]:
    if df.is_empty():
        return {}
    groups = df.partition_by("ID", as_dict=True)
    return {(key[0] if isinstance(key, tuple) else key): group for key, group in groups.items()}


def _unique_lens(df: pl.DataFrame) -> tuple[int, ...]:
    return tuple(sorted(set(df.get_column("LEN").to_list())))


def _byte_values(df: pl.DataFrame, byte_idx: int) -> list[int]:
    # A byte only counts where the frame's declared LEN actually covers it.
    present = df.filter(pl.col("LEN") > byte_idx)
    return present.get_column(f"D{byte_idx}").to_list() if not present.is_empty() else []


def _observe_byte_or_none(df: pl.DataFrame, byte_idx: int) -> ByteObservation | None:
    values = _byte_values(df, byte_idx)
    return observe_byte(values) if values else None


def _multi_byte_hint(
    obs_a: Sequence[ByteObservation | None], obs_b: Sequence[ByteObservation | None], byte_idx: int
) -> str:
    """P2.3: same carry-alignment check as Candidate Interpretations (P2.2), fed from
    the raw sequences already captured in both windows -- A and B are concatenated
    (not cross-correlated) so a short B window doesn't lose evidence A already has."""
    high_idx = byte_idx + 1
    if high_idx >= 8:
        return ""
    low_a, low_b = obs_a[byte_idx], obs_b[byte_idx]
    high_a, high_b = obs_a[high_idx], obs_b[high_idx]
    low_raw = (low_a.raw if low_a is not None else ()) + (low_b.raw if low_b is not None else ())
    high_raw = (high_a.raw if high_a is not None else ()) + (high_b.raw if high_b is not None else ())
    hint = detect_carry_alignment(list(low_raw), list(high_raw), low_byte_index=byte_idx, high_byte_index=high_idx)
    return format_multi_byte_hint(hint)


def _diff_bytes(
    obs_a: Sequence[ByteObservation | None],
    obs_b: Sequence[ByteObservation | None],
) -> list[ByteDiff]:
    """Classify every byte index where both sides have data -- shared by the batch
    (_diff_for_id) and live (build_live_diff_report) paths so both stay in sync."""
    byte_diffs: list[ByteDiff] = []
    for byte_idx in range(8):
        a, b = obs_a[byte_idx], obs_b[byte_idx]
        if a is None or b is None:
            continue
        diff = classify_byte(a, b)
        hint = _multi_byte_hint(obs_a, obs_b, byte_idx)
        byte_diffs.append(dataclasses.replace(diff, byte_index=byte_idx, multi_byte_hint=hint))
    return byte_diffs


def _diff_for_id(
    can_id: str,
    group_a: pl.DataFrame | None,
    group_b: pl.DataFrame | None,
    dbc_manager,
) -> IdDiff:
    if group_a is None:
        return IdDiff(
            can_id=can_id, presence="only_b", frames_a=0, frames_b=group_b.height,
            len_a=(), len_b=_unique_lens(group_b), len_changed=False,
            byte_diffs=(), score=_PRESENCE_SCORE, dbc_hint=None,
        )
    if group_b is None:
        return IdDiff(
            can_id=can_id, presence="only_a", frames_a=group_a.height, frames_b=0,
            len_a=_unique_lens(group_a), len_b=(), len_changed=False,
            byte_diffs=(), score=_PRESENCE_SCORE, dbc_hint=None,
        )

    len_a, len_b = _unique_lens(group_a), _unique_lens(group_b)
    len_changed = set(len_a) != set(len_b)

    obs_a = [_observe_byte_or_none(group_a, i) for i in range(8)]
    obs_b = [_observe_byte_or_none(group_b, i) for i in range(8)]
    byte_diffs = _diff_bytes(obs_a, obs_b)

    changed_indexes = {d.byte_index for d in byte_diffs if d.change_type != ChangeType.UNCHANGED}
    dbc_hint = _dbc_hint_for_id(dbc_manager, can_id, changed_indexes)

    return IdDiff(
        can_id=can_id,
        presence="both",
        frames_a=group_a.height,
        frames_b=group_b.height,
        len_a=len_a,
        len_b=len_b,
        len_changed=len_changed,
        byte_diffs=tuple(byte_diffs),
        score=_id_score(byte_diffs, extra_bonus=len_changed),
        dbc_hint=dbc_hint,
    )


def _id_score(byte_diffs: Sequence[ByteDiff], *, extra_bonus: bool) -> float:
    changed = [d for d in byte_diffs if d.change_type != ChangeType.UNCHANGED]
    score = max((d.score for d in changed), default=0.0) + 0.05 * len(changed)
    return score + 0.3 if extra_bonus else score


@dataclass
class LiveByteAccumulator:
    """Incremental mirror of observe_byte for Diff Analyzer's Live mode: feed() is
    O(1) per value, snapshot() freezes the running state into a ByteObservation
    identical to observe_byte(all_fed_values). Invariant pinned by
    tests/test_range_diff_live.py."""

    n_frames: int = 0
    _values: set[int] = dataclasses.field(default_factory=set)
    _raw: list[int] = dataclasses.field(default_factory=list)
    _sum: float = 0.0
    _vmin: int | None = None
    _vmax: int | None = None
    _first: int | None = None
    _last: int | None = None
    _changes: int = 0
    _increasing_or_wrap: int = 0

    def feed(self, value: int) -> None:
        value = int(value)
        if self.n_frames > 0:
            diff = value - self._last
            if diff != 0:
                self._changes += 1
            if diff == 1 or diff == -255:
                self._increasing_or_wrap += 1
        else:
            self._first = value
        self._last = value
        self.n_frames += 1
        self._values.add(value)
        self._raw.append(value)
        self._sum += value
        self._vmin = value if self._vmin is None else min(self._vmin, value)
        self._vmax = value if self._vmax is None else max(self._vmax, value)

    def snapshot(self) -> ByteObservation:
        n_diffs = max(0, self.n_frames - 1)
        change_ratio = (self._changes / n_diffs) if n_diffs else 0.0
        return ByteObservation(
            n_frames=self.n_frames,
            values=tuple(sorted(self._values)),
            raw=tuple(self._raw),
            vmin=self._vmin if self._vmin is not None else 0,
            vmax=self._vmax if self._vmax is not None else 0,
            mean=(self._sum / self.n_frames) if self.n_frames else 0.0,
            first=self._first if self._first is not None else 0,
            last=self._last if self._last is not None else 0,
            change_ratio=change_ratio,
            looks_counter=self._looks_counter(n_diffs),
        )

    def _looks_counter(self, n_diffs: int) -> bool:
        if n_diffs == 0:
            return False
        if (self._increasing_or_wrap / n_diffs) >= _COUNTER_RATIO:
            return True
        if len(self._values) == 2:
            return (self._changes / n_diffs) >= _COUNTER_RATIO
        return False


def build_live_diff_report(
    baseline: dict[str, list[ByteObservation | None]],
    live_acc: dict[str, list[LiveByteAccumulator | None]],
    *,
    range_a: TimeRange,
    now: float,
    dbc_manager=None,
) -> RangeDiffReport:
    """Live counterpart to build_range_diff_report: `baseline` is a one-time frozen
    per-(can_id, byte_index) snapshot taken when the user captures it; `live_acc`
    keeps accumulating from that instant forward. Reuses _diff_bytes/_id_score so the
    result is the same RangeDiffReport shape the view already renders in batch mode."""
    all_ids = sorted(set(baseline) | set(live_acc))
    ids: list[IdDiff] = []
    for can_id in all_ids:
        obs_a = baseline.get(can_id, [None] * 8)
        obs_b = [acc.snapshot() if acc is not None and acc.n_frames else None for acc in live_acc.get(can_id, [None] * 8)]
        has_a = any(o is not None for o in obs_a)
        has_b = any(o is not None for o in obs_b)
        if not has_a and not has_b:
            continue
        frames_a = max((o.n_frames for o in obs_a if o is not None), default=0)
        frames_b = max((o.n_frames for o in obs_b if o is not None), default=0)
        if not has_a:
            ids.append(IdDiff(
                can_id=can_id, presence="only_b", frames_a=0, frames_b=frames_b,
                len_a=(), len_b=(), len_changed=False,
                byte_diffs=(), score=_PRESENCE_SCORE, dbc_hint=None,
            ))
            continue
        if not has_b:
            ids.append(IdDiff(
                can_id=can_id, presence="only_a", frames_a=frames_a, frames_b=0,
                len_a=(), len_b=(), len_changed=False,
                byte_diffs=(), score=_PRESENCE_SCORE, dbc_hint=None,
            ))
            continue
        byte_diffs = _diff_bytes(obs_a, obs_b)
        changed_indexes = {d.byte_index for d in byte_diffs if d.change_type != ChangeType.UNCHANGED}
        dbc_hint = _dbc_hint_for_id(dbc_manager, can_id, changed_indexes)
        ids.append(IdDiff(
            can_id=can_id,
            presence="both",
            frames_a=frames_a,
            frames_b=frames_b,
            len_a=(),
            len_b=(),
            len_changed=False,
            byte_diffs=tuple(byte_diffs),
            score=_id_score(byte_diffs, extra_bonus=False),
            dbc_hint=dbc_hint,
        ))

    ids.sort(key=lambda item: item.score, reverse=True)
    return RangeDiffReport(range_a=range_a, range_b=TimeRange(start=range_a.end, end=now), ids=tuple(ids))


def observe_dataframe_bytes(df: pl.DataFrame) -> dict[str, list[ByteObservation | None]]:
    """Per-(can_id, byte_index) snapshot of df -- used to capture a Live-mode baseline."""
    if df is None or df.is_empty():
        return {}
    parts = _partition_by_id(df)
    return {can_id: [_observe_byte_or_none(group, i) for i in range(8)] for can_id, group in parts.items()}


def extract_byte_series(df: pl.DataFrame, can_id: str, byte_idx: int) -> tuple[list[float], list[int]]:
    """Raw (timestamp, value) series for one CAN ID's byte across the whole df --
    feeds Diff Analyzer's Plot tab so a selected byte-diff can be shown in context."""
    if df is None or df.is_empty():
        return [], []
    subset = df.filter((pl.col("ID") == can_id) & (pl.col("LEN") > byte_idx))
    if subset.is_empty():
        return [], []
    return subset.get_column("TS").to_list(), subset.get_column(f"D{byte_idx}").to_list()


def feed_live_accumulators(live_acc: dict[str, list[LiveByteAccumulator]], new_df: pl.DataFrame) -> None:
    """Feed a new chunk of frames into live_acc in place -- creates fresh per-byte
    accumulators for any CAN ID not seen yet. Never re-scans anything already fed."""
    if new_df is None or new_df.is_empty():
        return
    for key, group in new_df.partition_by("ID", as_dict=True).items():
        can_id = key[0] if isinstance(key, tuple) else key
        accs = live_acc.setdefault(can_id, [LiveByteAccumulator() for _ in range(8)])
        for byte_idx in range(8):
            for value in _byte_values(group, byte_idx):
                accs[byte_idx].feed(value)


def _dbc_hint_for_id(dbc_manager, can_id: str, changed_byte_indexes: set[int]) -> str | None:
    if dbc_manager is None or not changed_byte_indexes:
        return None
    changed_bits = {bit for idx in changed_byte_indexes for bit in range(idx * 8, idx * 8 + 8)}

    names: set[str] = set()
    for entry in dbc_manager.active_entries():
        for message in entry.db.messages:
            for signal in message.signals:
                try:
                    sig_def = dbc_manager.get_signal_definition(entry.name, message.name, signal.name)
                except KeyError:
                    continue
                if sig_def["id_match"] != "exact" or sig_def["can_id"] != can_id:
                    continue
                sig_bits = range(sig_def["start_bit"], sig_def["start_bit"] + sig_def["length"])
                if changed_bits.intersection(sig_bits):
                    names.add(signal.name)
    return ", ".join(sorted(names)) if names else None


def dbc_hint_for_byte(dbc_manager, can_id: str, byte_index: int) -> str | None:
    """B-17: same lookup as _dbc_hint_for_id, scoped to a single byte -- lets the UI
    show a per-byte DBC signal hint instead of only one combined string per id."""
    return _dbc_hint_for_id(dbc_manager, can_id, {byte_index})


def _visible_id(id_diff: IdDiff, opts: DiffOptions) -> IdDiff | None:
    if id_diff.presence != "both":
        return id_diff if opts.include_presence else None

    if id_diff.frames_a < opts.min_frames or id_diff.frames_b < opts.min_frames:
        # Too few frames to trust the byte classifications.
        return dataclasses.replace(id_diff, byte_diffs=()) if id_diff.len_changed else None

    visible_bytes = tuple(d for d in id_diff.byte_diffs if _byte_visible(d, opts))
    if visible_bytes or id_diff.len_changed:
        return dataclasses.replace(id_diff, byte_diffs=visible_bytes)
    return None


def format_byte_values(obs: ByteObservation) -> str:
    if len(obs.values) == 1:
        return str(obs.values[0])
    return f"{obs.vmin}..{obs.vmax}"


def export_range_diff_csv(items: Sequence[IdDiff], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["can_id", "byte_index", "change_type", "presence", "a", "b", "delta_mean", "p_value", "frames_a", "frames_b", "dbc_hint", "multi_byte_hint"]
        )
        for id_diff in items:
            _write_csv_rows(writer, id_diff)


def _write_csv_rows(writer, id_diff: IdDiff) -> None:
    if not id_diff.byte_diffs:
        writer.writerow(
            [id_diff.can_id, "", "", id_diff.presence, "", "", "", "", id_diff.frames_a, id_diff.frames_b, id_diff.dbc_hint or "", ""]
        )
        return
    for byte_diff in id_diff.byte_diffs:
        writer.writerow(
            [
                id_diff.can_id,
                byte_diff.byte_index,
                byte_diff.change_type.value,
                id_diff.presence,
                format_byte_values(byte_diff.a),
                format_byte_values(byte_diff.b),
                f"{byte_diff.delta_mean:.4f}",
                f"{byte_diff.p_value:.4g}" if byte_diff.p_value is not None else "",
                byte_diff.a.n_frames,
                byte_diff.b.n_frames,
                id_diff.dbc_hint or "",
                byte_diff.multi_byte_hint,
            ]
        )


def _byte_visible(diff: ByteDiff, opts: DiffOptions) -> bool:
    if diff.change_type == ChangeType.UNCHANGED:
        return False
    if diff.change_type == ChangeType.SAME_OSCILLATION and opts.ignore_same_oscillation:
        return False
    if diff.is_counter and opts.ignore_counters:
        return False
    if opts.only_new_territory and diff.change_type != ChangeType.NEW_TERRITORY:
        return False
    if opts.require_significance and (diff.p_value is None or diff.p_value >= opts.significance_alpha):
        return False
    return True
