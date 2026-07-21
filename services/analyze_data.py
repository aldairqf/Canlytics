"""Pure analysis helpers for the Analyze Data feature.

All functions are stateless and Qt-free so they can be tested without a
running application. The AnalyzeDataViewModel thin-wraps these for the UI.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import log2
from typing import Callable

import numpy as np
import polars as pl

from config.defaults import SIGNAL_COLOR_PALETTE
from utils.can_id import can_id_sort_key
from utils.plot_sampling import minmax_downsample


@dataclass(frozen=True, eq=False)
class ByteSeries:
    # x/y may be plain lists (build_plot_series) or numpy arrays (the accumulator's
    # cached path) -- custom __eq__ below so np.array_equal handles both uniformly
    # (a dataclass-generated __eq__ would raise on numpy's elementwise comparison).
    label: str
    x: list[float]
    y: list[int]
    color: str

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ByteSeries):
            return NotImplemented
        return (
            self.label == other.label
            and self.color == other.color
            and np.array_equal(self.x, other.x)
            and np.array_equal(self.y, other.y)
        )


def sorted_can_ids(df: pl.DataFrame) -> list[str]:
    if df is None or df.is_empty() or "ID" not in df.columns:
        return []
    return sorted(df["ID"].unique().to_list(), key=can_id_sort_key)


_HEX_DIGITS = [str(d) for d in range(10)] + ["A", "B", "C", "D", "E", "F"]


def _byte_hex_expr(byte_index: int) -> pl.Expr:
    """Render D{byte_index} (int 0-255) as a zero-padded 2-digit uppercase hex string; null -> ''."""
    d = pl.col(f"D{byte_index}")
    hi = (d // 16).replace_strict(list(range(16)), _HEX_DIGITS, default=None, return_dtype=pl.Utf8)
    lo = (d % 16).replace_strict(list(range(16)), _HEX_DIGITS, default=None, return_dtype=pl.Utf8)
    return pl.when(d.is_null()).then(pl.lit("")).otherwise(hi + lo)


def mux_label_expr(mux_bytes: tuple[int, ...]) -> pl.Expr:
    parts = [_byte_hex_expr(i) for i in mux_bytes]
    return parts[0] if len(parts) == 1 else pl.concat_str(parts, separator=" ")


def detect_mux_cases(df: pl.DataFrame, mux_bytes: tuple[int, ...]) -> list[str]:
    """Return ordered list of distinct mux-case labels found in *df*."""
    if df.is_empty() or not mux_bytes:
        return []
    return (
        df.select(mux_label_expr(mux_bytes).alias("_lbl"))["_lbl"]
        .unique(maintain_order=True)
        .to_list()
    )


def build_summary(
    df: pl.DataFrame,
    can_id: str | None,
    mux_bytes: tuple[int, ...],
    mux_case: str,
) -> dict:
    """Compute per-frame and per-byte statistics for the Analyze Data panel."""
    if df.is_empty():
        return {
            "CAN ID": can_id or "",
            "Frames": 0,
            "MUX Bytes": ",".join(str(i) for i in mux_bytes) or "None",
            "MUX Case": mux_case,
            "Observed LEN": "",
            "Distinct Payloads": 0,
            "Payload Changes": 0,
            "Mean Period": "",
            "Min Period": "",
            "Max Period": "",
            "Byte Changes": "",
            "Byte Uniques": "",
            "Byte Entropy": "",
            "Byte Update Mean": "",
            "Byte Update Min": "",
            "Byte Update Max": "",
        }

    ts_values = df["TS"].to_list() if "TS" in df.columns else []
    periods = [
        round(float(ts_values[i]) - float(ts_values[i - 1]), 6)
        for i in range(1, len(ts_values))
    ]
    payload_changes = (
        int(df.select((pl.col("DATA") != pl.col("DATA").shift(1)).sum()).item())
        if "DATA" in df.columns and df.height > 1
        else 0
    )
    observed_len = (
        ",".join(str(x) for x in sorted(df["LEN"].unique().to_list()))
        if "LEN" in df.columns
        else ""
    )

    byte_cols = [f"D{i}" for i in range(8) if f"D{i}" in df.columns]
    polars_stats: dict = {}
    if byte_cols:
        polars_stats = df.select(
            [pl.col(c).n_unique().alias(f"{c}_nu") for c in byte_cols]
            + [(pl.col(c) != pl.col(c).shift(1)).sum().alias(f"{c}_ch") for c in byte_cols]
        ).row(0, named=True)

    byte_change_parts: list[str] = []
    byte_unique_parts: list[str] = []
    byte_entropy_parts: list[str] = []
    byte_update_mean_parts: list[str] = []
    byte_update_min_parts: list[str] = []
    byte_update_max_parts: list[str] = []
    for i in range(8):
        col = f"D{i}"
        if col not in df.columns:
            continue
        byte_change_parts.append(f"B{i}:{polars_stats[f'{col}_ch']}")
        byte_unique_parts.append(f"B{i}:{polars_stats[f'{col}_nu']}")
        values = df[col].to_list()
        byte_entropy_parts.append(f"B{i}:{shannon_entropy(values):.3f}")
        upd = update_periods(ts_values, values)
        if upd:
            byte_update_mean_parts.append(f"B{i}:{sum(upd) / len(upd):.6f}")
            byte_update_min_parts.append(f"B{i}:{min(upd):.6f}")
            byte_update_max_parts.append(f"B{i}:{max(upd):.6f}")
        else:
            byte_update_mean_parts.append(f"B{i}:")
            byte_update_min_parts.append(f"B{i}:")
            byte_update_max_parts.append(f"B{i}:")

    return {
        "CAN ID": can_id or "",
        "Frames": int(df.height),
        "MUX Bytes": ",".join(str(i) for i in mux_bytes) or "None",
        "MUX Case": mux_case,
        "Observed LEN": observed_len,
        "Distinct Payloads": df["DATA"].n_unique() if "DATA" in df.columns else 0,
        "Payload Changes": payload_changes,
        "Mean Period": f"{sum(periods) / len(periods):.6f}" if periods else "",
        "Min Period": f"{min(periods):.6f}" if periods else "",
        "Max Period": f"{max(periods):.6f}" if periods else "",
        "Byte Changes": "  ".join(byte_change_parts),
        "Byte Uniques": "  ".join(byte_unique_parts),
        "Byte Entropy": "  ".join(byte_entropy_parts),
        "Byte Update Mean": "  ".join(byte_update_mean_parts),
        "Byte Update Min": "  ".join(byte_update_min_parts),
        "Byte Update Max": "  ".join(byte_update_max_parts),
    }


def build_plot_series(df: pl.DataFrame, selected_bytes: set[int]) -> list[ByteSeries]:
    if df.is_empty() or not selected_bytes or "TS" not in df.columns:
        return []
    ts = df["TS"].cast(pl.Float64).to_list()
    result: list[ByteSeries] = []
    for idx in sorted(selected_bytes):
        col = f"D{idx}"
        if col not in df.columns:
            continue
        ys = df[col].cast(pl.Int64).to_list()
        color = SIGNAL_COLOR_PALETTE[idx % len(SIGNAL_COLOR_PALETTE)]
        result.append(ByteSeries(label=f"B{idx}", x=ts, y=ys, color=color))
    return result


def shannon_entropy(values: list) -> float:
    if not values:
        return 0.0
    counts: dict[str, int] = {}
    for v in values:
        k = str(v)
        counts[k] = counts.get(k, 0) + 1
    total = len(values)
    return -sum((c / total) * log2(c / total) for c in counts.values())


def update_periods(ts_values: list, values: list) -> list[float]:
    if len(ts_values) != len(values) or len(values) < 2:
        return []
    result: list[float] = []
    last_change_ts = None
    for i in range(1, len(values)):
        if values[i] == values[i - 1]:
            continue
        ts = float(ts_values[i])
        if last_change_ts is not None:
            result.append(round(ts - last_change_ts, 6))
        last_change_ts = ts
    return result


class AnalyzeDataAccumulator:
    """Incremental build_summary()/build_plot_series() -- feed() only new rows."""

    def __init__(self) -> None:
        self._frame_count = 0
        self._has_len = False
        self._len_values: set = set()
        self._has_data = False
        self._payload_values: set = set()
        self._has_last_payload = False
        self._last_payload = None
        self._payload_changes = 0
        self._has_ts = False
        self._has_last_ts = False
        self._last_ts: float | None = None
        self._period_count = 0
        self._period_sum = 0.0
        self._period_min: float | None = None
        self._period_max: float | None = None
        self._byte_present = [False] * 8
        self._byte_counts: list[dict] = [dict() for _ in range(8)]
        self._byte_changes = [0] * 8
        self._has_last_byte = [False] * 8
        self._last_byte_value: list = [None] * 8
        self._last_byte_change_ts: list = [None] * 8
        self._byte_update_count = [0] * 8
        self._byte_update_sum = [0.0] * 8
        self._byte_update_min: list = [None] * 8
        self._byte_update_max: list = [None] * 8
        self._d_present = [False] * 8
        # Stored as one numpy array per feed() call (a plain Python list of Python
        # float/int objects here would multiply memory ~10-20x over Polars' native
        # columnar D0..D7 for a large log, once every CAN ID gets precomputed and
        # cached at once -- see ROADMAP.md/BUGS.md, found via a real ~2.5GB session).
        self._ts_chunks: list[np.ndarray] = []
        self._d_chunks: list[list[np.ndarray]] = [[] for _ in range(8)]
        # plot_series() is called on every CAN-ID switch (not just once per feed) --
        # cache the concatenated view so revisiting an id already fed this session is
        # O(1) instead of re-concatenating every switch. feed() invalidates these;
        # plot_series() rebuilds them lazily.
        self._ts_series_arr: np.ndarray | None = None
        self._d_series_arr: list[np.ndarray | None] = [None] * 8

    @staticmethod
    def _concat_chunks(chunks: list[np.ndarray], dtype) -> np.ndarray:
        if not chunks:
            return np.array([], dtype=dtype)
        if len(chunks) == 1:
            return chunks[0]  # avoid a needless copy for the common single-feed case
        return np.concatenate(chunks)

    @staticmethod
    def _guarded_deltas(ts_sorted: np.ndarray, carried: float | None):
        """Periods for the accepted (non-decreasing, non-NaN) tail of *ts_sorted*.

        Vectorized twin of the per-row `ts_f >= last_accepted` guard: because the
        chunk is already TS-sorted, the rejected out-of-order rows are a prefix, so a
        single searchsorted split replaces the per-row branch. Returns
        (rounded deltas in feed order, new last-accepted ts, advanced flag).
        """
        if ts_sorted.size == 0:
            return [], carried, False
        if carried is None:
            deltas = [round(float(d), 6) for d in np.diff(ts_sorted)]
            return deltas, float(ts_sorted[-1]), True
        idx = int(np.searchsorted(ts_sorted, carried, side="left"))
        accepted = ts_sorted[idx:]
        if accepted.size == 0:
            return [], carried, False
        seq = np.empty(accepted.size + 1, dtype=np.float64)
        seq[0] = carried
        seq[1:] = accepted
        deltas = [round(float(d), 6) for d in np.diff(seq)]
        return deltas, float(accepted[-1]), True

    def _accumulate_periods(self, ts_sorted: np.ndarray) -> None:
        carried = self._last_ts if self._has_last_ts else None
        deltas, new_last, advanced = self._guarded_deltas(ts_sorted, carried)
        if advanced:
            self._last_ts = new_last
            self._has_last_ts = True
        for d in deltas:  # sequential sum keeps the running total chunking-invariant
            self._period_sum += d
        if deltas:
            self._period_count += len(deltas)
            dmin, dmax = min(deltas), max(deltas)
            self._period_min = dmin if self._period_min is None else min(self._period_min, dmin)
            self._period_max = dmax if self._period_max is None else max(self._period_max, dmax)

    def _accumulate_byte_timing(self, i: int, change_ts: np.ndarray) -> None:
        deltas, new_last, advanced = self._guarded_deltas(change_ts, self._last_byte_change_ts[i])
        if advanced:
            self._last_byte_change_ts[i] = new_last
        for d in deltas:
            self._byte_update_sum[i] += d
        if deltas:
            self._byte_update_count[i] += len(deltas)
            dmin, dmax = min(deltas), max(deltas)
            self._byte_update_min[i] = dmin if self._byte_update_min[i] is None else min(self._byte_update_min[i], dmin)
            self._byte_update_max[i] = dmax if self._byte_update_max[i] is None else max(self._byte_update_max[i], dmax)

    def feed(self, df: pl.DataFrame) -> None:
        if df is None or df.is_empty():
            return
        if "TS" in df.columns:
            df = df.sort("TS")

        n = df.height
        has_ts = "TS" in df.columns
        has_len = "LEN" in df.columns
        has_data = "DATA" in df.columns
        self._has_ts = self._has_ts or has_ts
        self._has_len = self._has_len or has_len
        self._has_data = self._has_data or has_data

        ts_arr: np.ndarray | None = None
        valid_mask: np.ndarray | None = None
        if has_ts:
            ts_arr = df["TS"].cast(pl.Float64).to_numpy()
            self._ts_chunks.append(ts_arr)
            self._ts_series_arr = None
            valid_mask = ~np.isnan(ts_arr)  # null TS rows are skipped for order-guarded stats

        self._frame_count += n

        if has_len:
            self._len_values.update(df["LEN"].to_list())

        if has_data:
            data_list = df["DATA"].to_list()
            data_arr = np.array(data_list, dtype=object)
            self._payload_values.update(data_list)
            within = int((data_arr[1:] != data_arr[:-1]).sum()) if n > 1 else 0
            boundary = 1 if (self._has_last_payload and data_list[0] != self._last_payload) else 0
            self._payload_changes += within + boundary
            self._last_payload = data_list[-1]
            self._has_last_payload = True

        if has_ts:
            self._accumulate_periods(ts_arr[valid_mask])

        for i in range(8):
            col = f"D{i}"
            if col not in df.columns:
                continue
            d_arr = df[col].cast(pl.Int64).to_numpy()
            self._d_present[i] = True
            self._d_chunks[i].append(d_arr)
            self._d_series_arr[i] = None

            self._byte_present[i] = True
            d_list = d_arr.tolist()

            counts = self._byte_counts[i]
            for value, cnt in Counter(d_list).items():  # keys stay str(value), matching the old per-row keying
                key = str(value)
                counts[key] = counts.get(key, 0) + cnt

            change_mask = np.empty(n, dtype=bool)
            change_mask[0] = bool(self._has_last_byte[i] and d_list[0] != self._last_byte_value[i])
            if n > 1:
                change_mask[1:] = d_arr[1:] != d_arr[:-1]
            self._byte_changes[i] += int(change_mask.sum())

            if has_ts:
                self._accumulate_byte_timing(i, ts_arr[change_mask & valid_mask])

            self._last_byte_value[i] = d_list[-1]
            self._has_last_byte[i] = True

    def snapshot(self, can_id: str | None, mux_bytes: tuple[int, ...], mux_case: str) -> dict:
        if self._frame_count == 0:
            return {
                "CAN ID": can_id or "",
                "Frames": 0,
                "MUX Bytes": ",".join(str(i) for i in mux_bytes) or "None",
                "MUX Case": mux_case,
                "Observed LEN": "",
                "Distinct Payloads": 0,
                "Payload Changes": 0,
                "Mean Period": "",
                "Min Period": "",
                "Max Period": "",
                "Byte Changes": "",
                "Byte Uniques": "",
                "Byte Entropy": "",
                "Byte Update Mean": "",
                "Byte Update Min": "",
                "Byte Update Max": "",
            }

        byte_change_parts: list[str] = []
        byte_unique_parts: list[str] = []
        byte_entropy_parts: list[str] = []
        byte_update_mean_parts: list[str] = []
        byte_update_min_parts: list[str] = []
        byte_update_max_parts: list[str] = []
        for i in range(8):
            if not self._byte_present[i]:
                continue
            counts = self._byte_counts[i]
            total = sum(counts.values())
            entropy = -sum((c / total) * log2(c / total) for c in counts.values()) if total else 0.0
            byte_change_parts.append(f"B{i}:{self._byte_changes[i]}")
            byte_unique_parts.append(f"B{i}:{len(counts)}")
            byte_entropy_parts.append(f"B{i}:{entropy:.3f}")
            if self._byte_update_count[i]:
                mean = self._byte_update_sum[i] / self._byte_update_count[i]
                byte_update_mean_parts.append(f"B{i}:{mean:.6f}")
                byte_update_min_parts.append(f"B{i}:{self._byte_update_min[i]:.6f}")
                byte_update_max_parts.append(f"B{i}:{self._byte_update_max[i]:.6f}")
            else:
                byte_update_mean_parts.append(f"B{i}:")
                byte_update_min_parts.append(f"B{i}:")
                byte_update_max_parts.append(f"B{i}:")

        return {
            "CAN ID": can_id or "",
            "Frames": self._frame_count,
            "MUX Bytes": ",".join(str(i) for i in mux_bytes) or "None",
            "MUX Case": mux_case,
            "Observed LEN": ",".join(str(x) for x in sorted(self._len_values)) if self._has_len else "",
            "Distinct Payloads": len(self._payload_values) if self._has_data else 0,
            "Payload Changes": self._payload_changes,
            "Mean Period": f"{self._period_sum / self._period_count:.6f}" if self._period_count else "",
            "Min Period": f"{self._period_min:.6f}" if self._period_min is not None else "",
            "Max Period": f"{self._period_max:.6f}" if self._period_max is not None else "",
            "Byte Changes": "  ".join(byte_change_parts),
            "Byte Uniques": "  ".join(byte_unique_parts),
            "Byte Entropy": "  ".join(byte_entropy_parts),
            "Byte Update Mean": "  ".join(byte_update_mean_parts),
            "Byte Update Min": "  ".join(byte_update_min_parts),
            "Byte Update Max": "  ".join(byte_update_max_parts),
        }

    def plot_series(self, selected_bytes: set[int]) -> list[ByteSeries]:
        if not self._has_ts or not selected_bytes:
            return []
        if self._ts_series_arr is None:
            self._ts_series_arr = self._concat_chunks(self._ts_chunks, np.float64)
        result: list[ByteSeries] = []
        for idx in sorted(selected_bytes):
            if not self._d_present[idx]:
                continue
            if self._d_series_arr[idx] is None:
                self._d_series_arr[idx] = self._concat_chunks(self._d_chunks[idx], np.int64)
            color = SIGNAL_COLOR_PALETTE[idx % len(SIGNAL_COLOR_PALETTE)]
            result.append(ByteSeries(label=f"B{idx}", x=self._ts_series_arr, y=self._d_series_arr[idx], color=color))
        return result

    def warm_plot_series_cache(self) -> None:
        """Pay plot_series()'s one-time numpy conversion up front (called by the
        background precompute pass) so even the *first* switch to an id afterward
        is instant, not just the second."""
        self.plot_series(set(range(8)))

def build_accumulator(df: pl.DataFrame) -> AnalyzeDataAccumulator:
    """Fresh accumulator fully seeded from *df* (already filtered) -- the full-recompute path."""
    acc = AnalyzeDataAccumulator()
    acc.feed(df)
    return acc


@dataclass(frozen=True)
class MatrixEntry:
    can_id: str
    series: ByteSeries
    byte_index: int
    has_movement: bool


def build_matrix_summary(
    df: pl.DataFrame,
    can_ids: list[str],
    *,
    max_points: int = 150,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[MatrixEntry]:
    """Matrix rollup: every byte of every CAN ID gets its own decimated (x, y)
    sample, independent of the per-ID accumulator cache. All bytes are always
    included -- any hiding happens display-side via the "no movement" checkbox."""
    if df is None or df.is_empty() or "ID" not in df.columns or "TS" not in df.columns:
        return []
    byte_cols = [f"D{i}" for i in range(8) if f"D{i}" in df.columns]
    if not byte_cols:
        return []

    # Column-pruned view: sorting only ID/TS/D0..D7 avoids copying LEN/DATA too.
    slim = df.select(["ID", "TS"] + byte_cols)

    # One grouped pass gets every byte's change count per id -- sort_by() inside the
    # aggregation orders each group's own (small) column by TS, so no separate
    # whole-dataframe sort/copy is ever materialized.
    change_exprs = [
        (pl.col(c).sort_by(pl.col("TS")).diff().fill_null(0) != 0).sum().alias(c)
        for c in byte_cols
    ]
    changes = slim.group_by("ID", maintain_order=True).agg(change_exprs)
    present = [i for i in range(8) if f"D{i}" in byte_cols]
    change_counts_by_id: dict[str, dict[int, int]] = {
        row["ID"]: {i: row[f"D{i}"] for i in present} for row in changes.iter_rows(named=True)
    }

    result: list[MatrixEntry] = []
    total = len(can_ids)
    for done, can_id in enumerate(can_ids, start=1):
        if should_cancel is not None and should_cancel():
            raise AnalyzeDataPrecomputeCanceled()
        counts = change_counts_by_id.get(can_id)
        if counts is not None:
            sub = slim.filter(pl.col("ID") == can_id)
            x = sub["TS"].cast(pl.Float64).to_numpy()
            for byte_idx in present:
                y = sub[f"D{byte_idx}"].cast(pl.Int64).to_numpy()
                dx, dy = minmax_downsample(x, y, max_points)
                color = SIGNAL_COLOR_PALETTE[byte_idx % len(SIGNAL_COLOR_PALETTE)]
                series = ByteSeries(label=f"B{byte_idx}", x=dx, y=dy, color=color)
                result.append(MatrixEntry(
                    can_id=can_id, series=series, byte_index=byte_idx,
                    has_movement=counts[byte_idx] > 0,
                ))
        if on_progress is not None:
            on_progress(done, total)
    return result


def build_matrix_entries_for_id(df: pl.DataFrame, can_id: str, *, max_points: int = 150) -> list[MatrixEntry]:
    """Same per-byte rollup as build_matrix_summary(), scoped to a single CAN ID.

    build_matrix_summary()'s group_by pass computes change counts for every ID at
    once -- efficient for a full batch build, wasteful to repeat per touched ID on
    every incoming chunk. This filters to one ID up front instead, cheap enough to
    call synchronously from Matrix Live mode's reactive auto-add (AN3)."""
    if df is None or df.is_empty() or "ID" not in df.columns or "TS" not in df.columns:
        return []
    byte_cols = [f"D{i}" for i in range(8) if f"D{i}" in df.columns]
    if not byte_cols:
        return []
    sub = df.filter(pl.col("ID") == can_id).select(["TS"] + byte_cols).sort("TS")
    if sub.is_empty():
        return []

    x = sub["TS"].cast(pl.Float64).to_numpy()
    result: list[MatrixEntry] = []
    for i in range(8):
        col = f"D{i}"
        if col not in byte_cols:
            continue
        y = sub[col].cast(pl.Int64).to_numpy()
        has_movement = bool(np.any(np.diff(y) != 0)) if y.size > 1 else False
        dx, dy = minmax_downsample(x, y, max_points)
        color = SIGNAL_COLOR_PALETTE[i % len(SIGNAL_COLOR_PALETTE)]
        series = ByteSeries(label=f"B{i}", x=dx, y=dy, color=color)
        result.append(MatrixEntry(can_id=can_id, series=series, byte_index=i, has_movement=has_movement))
    return result


def mux_bytes_for_can_id(mux_configs: list, can_id: str) -> tuple[int, ...]:
    can_id = (can_id or "").upper()
    for cfg in mux_configs:
        if cfg.can_id == can_id and cfg.length is None:
            return cfg.mux_bytes
    for cfg in mux_configs:
        if cfg.can_id == can_id:
            return cfg.mux_bytes
    return ()


class AnalyzeDataPrecomputeCanceled(Exception):
    pass


def build_all_accumulators(
    df: pl.DataFrame,
    can_ids: list[str],
    mux_bytes_for_id: Callable[[str], tuple[int, ...]],
    *,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, tuple[AnalyzeDataAccumulator, list[str]]]:
    """Eagerly build a mux_case=='All' accumulator for every id in *can_ids* -- lets
    the Analyze Data window warm its whole cache once at open time instead of paying
    the first-visit cost per CAN ID when the user switches to it."""
    result: dict[str, tuple[AnalyzeDataAccumulator, list[str]]] = {}
    total = len(can_ids)
    for done, can_id in enumerate(can_ids, start=1):
        if should_cancel is not None and should_cancel():
            raise AnalyzeDataPrecomputeCanceled()
        sub = df.filter(pl.col("ID") == can_id)
        mux_cases = ["All"] + detect_mux_cases(sub, mux_bytes_for_id(can_id))
        acc = build_accumulator(sub)
        acc.warm_plot_series_cache()
        result[can_id] = (acc, mux_cases)
        if on_progress is not None:
            on_progress(done, total)
    return result
