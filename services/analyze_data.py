"""Pure analysis helpers for the Analyze Data feature.

All functions are stateless and Qt-free so they can be tested without a
running application. The AnalyzeDataViewModel thin-wraps these for the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import log2

import polars as pl

from config.defaults import SIGNAL_COLOR_PALETTE
from utils.can_id import can_id_sort_key


@dataclass(frozen=True)
class ByteSeries:
    label: str
    x: list[float]
    y: list[int]
    color: str


def sorted_can_ids(df: pl.DataFrame) -> list[str]:
    if df is None or df.is_empty() or "ID" not in df.columns:
        return []
    return sorted(df["ID"].unique().to_list(), key=can_id_sort_key)


def mux_label_expr(mux_bytes: tuple[int, ...]) -> pl.Expr:
    parts = [pl.col(f"B{i}").fill_null("") for i in mux_bytes]
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

    byte_cols = [f"B{i}" for i in range(8) if f"B{i}" in df.columns]
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
        col = f"B{i}"
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
        self._ts_series: list[float] = []
        self._d_series: list[list[int]] = [[] for _ in range(8)]

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

        ts_list = df["TS"].to_list() if has_ts else [None] * n
        len_list = df["LEN"].to_list() if has_len else None
        data_list = df["DATA"].to_list() if has_data else None
        b_lists: list = [None] * 8
        for i in range(8):
            col = f"B{i}"
            if col in df.columns:
                self._byte_present[i] = True
                b_lists[i] = df[col].to_list()
        for i in range(8):
            col = f"D{i}"
            if col in df.columns:
                self._d_present[i] = True
                self._d_series[i].extend(df[col].cast(pl.Int64).to_list())
        if has_ts:
            self._ts_series.extend(df["TS"].cast(pl.Float64).to_list())

        self._frame_count += n

        for row in range(n):
            ts = ts_list[row]
            ts_f = float(ts) if ts is not None else None

            if has_len:
                self._len_values.add(len_list[row])

            if has_data:
                payload = data_list[row]
                self._payload_values.add(payload)
                if self._has_last_payload and payload != self._last_payload:
                    self._payload_changes += 1
                self._last_payload = payload
                self._has_last_payload = True

            if ts_f is not None and (not self._has_last_ts or ts_f >= self._last_ts):
                if self._has_last_ts:
                    delta = round(ts_f - self._last_ts, 6)
                    self._period_count += 1
                    self._period_sum += delta
                    self._period_min = delta if self._period_min is None else min(self._period_min, delta)
                    self._period_max = delta if self._period_max is None else max(self._period_max, delta)
                self._last_ts = ts_f
                self._has_last_ts = True

            for i in range(8):
                if b_lists[i] is None:
                    continue
                value = b_lists[i][row]
                if self._has_last_byte[i] and value != self._last_byte_value[i]:
                    self._byte_changes[i] += 1
                    if ts_f is not None and (
                        self._last_byte_change_ts[i] is None or ts_f >= self._last_byte_change_ts[i]
                    ):
                        if self._last_byte_change_ts[i] is not None:
                            delta = round(ts_f - self._last_byte_change_ts[i], 6)
                            self._byte_update_count[i] += 1
                            self._byte_update_sum[i] += delta
                            self._byte_update_min[i] = (
                                delta if self._byte_update_min[i] is None else min(self._byte_update_min[i], delta)
                            )
                            self._byte_update_max[i] = (
                                delta if self._byte_update_max[i] is None else max(self._byte_update_max[i], delta)
                            )
                        self._last_byte_change_ts[i] = ts_f
                counts = self._byte_counts[i]
                key = str(value)
                counts[key] = counts.get(key, 0) + 1
                self._last_byte_value[i] = value
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
        result: list[ByteSeries] = []
        for idx in sorted(selected_bytes):
            if not self._d_present[idx]:
                continue
            color = SIGNAL_COLOR_PALETTE[idx % len(SIGNAL_COLOR_PALETTE)]
            result.append(ByteSeries(label=f"B{idx}", x=list(self._ts_series), y=list(self._d_series[idx]), color=color))
        return result


def build_accumulator(df: pl.DataFrame) -> AnalyzeDataAccumulator:
    """Fresh accumulator fully seeded from *df* (already filtered) -- the full-recompute path."""
    acc = AnalyzeDataAccumulator()
    acc.feed(df)
    return acc
