"""Pure analysis helpers for the Analyze Data feature.

All functions are stateless and Qt-free so they can be tested without a
running application. The AnalyzeDataViewModel thin-wraps these for the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import log2

import polars as pl

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
        int((pl.Series(df["DATA"].to_list()) != pl.Series(df["DATA"].to_list()).shift(1)).sum())
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
    colors = ["#00d1ff", "#ffd400", "#00ff88", "#ff6b6b", "#c77dff", "#ff9f1c", "#4cc9f0", "#b8f200"]
    ts = df["TS"].cast(pl.Float64).to_list()
    result: list[ByteSeries] = []
    for idx in sorted(selected_bytes):
        col = f"D{idx}"
        if col not in df.columns:
            continue
        ys = df[col].cast(pl.Int64).to_list()
        result.append(ByteSeries(label=f"B{idx}", x=ts, y=ys, color=colors[idx % len(colors)]))
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
