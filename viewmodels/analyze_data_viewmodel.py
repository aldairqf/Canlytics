from __future__ import annotations

from dataclasses import dataclass
from math import log2

import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal

from models.mux_config import MuxConfigEntry
from utils.can_id import can_id_sort_key


@dataclass(frozen=True)
class ByteSeries:
    label: str
    x: list[float]
    y: list[int]
    color: str


class AnalyzeDataViewModel(QObject):
    can_ids_changed = QtSignal(list)
    mux_cases_changed = QtSignal(list)
    summary_changed = QtSignal(dict)
    plot_changed = QtSignal(object)
    selected_id_changed = QtSignal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._df = pl.DataFrame()
        self._selected_id: str | None = None
        self._selected_bytes: set[int] = set(range(8))
        self._mux_configs: list[MuxConfigEntry] = []
        self._selected_mux_case = "All"
        self._ts_min: float | None = None
        self._ts_max: float | None = None

    @property
    def selected_id(self) -> str | None:
        return self._selected_id

    @property
    def mux_configs(self) -> list[MuxConfigEntry]:
        return list(self._mux_configs)

    def set_dataframe(self, df: pl.DataFrame | None) -> None:
        self._df = df if df is not None else pl.DataFrame()
        ids = _sorted_can_ids(self._df)
        self.can_ids_changed.emit(ids)
        if self._selected_id not in ids:
            self._selected_id = ids[0] if ids else None
            self.selected_id_changed.emit(self._selected_id or "")
        self._refresh()

    def set_selected_id(self, can_id: str | None) -> None:
        can_id = (can_id or "").strip().upper() or None
        if self._selected_id == can_id:
            return
        self._selected_id = can_id
        self.selected_id_changed.emit(self._selected_id or "")
        self._selected_mux_case = "All"
        self._refresh()

    def set_selected_bytes(self, indexes: set[int]) -> None:
        self._selected_bytes = set(sorted(i for i in indexes if 0 <= i <= 7))
        self._refresh()

    def set_mux_configuration(self, configs: list[MuxConfigEntry]) -> None:
        self._mux_configs = list(configs)
        self._selected_mux_case = "All"
        self._refresh()

    def set_selected_mux_case(self, case_label: str) -> None:
        new_case = (case_label or "All").strip() or "All"
        if new_case == self._selected_mux_case:
            return
        self._selected_mux_case = new_case
        self._refresh()

    def set_time_range(self, ts_min: float | None, ts_max: float | None) -> None:
        self._ts_min = ts_min
        self._ts_max = ts_max
        self._refresh()

    def _refresh(self) -> None:
        filtered = self._filtered_df()
        mux_cases = ["All"] + _detect_mux_cases(self._filtered_df(raw_id_only=True), self._mux_bytes_for_selected_id())
        if self._selected_mux_case not in mux_cases:
            self._selected_mux_case = "All"
        self.mux_cases_changed.emit(mux_cases)

        active = self._apply_mux_case(filtered)
        self.summary_changed.emit(_build_summary(active, self._selected_id, self._mux_bytes_for_selected_id(), self._selected_mux_case))
        self.plot_changed.emit(_build_plot_series(active, self._selected_bytes))

    def _filtered_df(self, raw_id_only: bool = False) -> pl.DataFrame:
        if self._df is None or self._df.is_empty() or not self._selected_id or "ID" not in self._df.columns:
            return pl.DataFrame()
        predicate = pl.col("ID") == self._selected_id
        if "TS" in self._df.columns:
            if self._ts_min is not None:
                predicate = predicate & (pl.col("TS") >= float(self._ts_min))
            if self._ts_max is not None:
                predicate = predicate & (pl.col("TS") <= float(self._ts_max))
        return self._df.filter(predicate)

    def _apply_mux_case(self, df: pl.DataFrame) -> pl.DataFrame:
        if df.is_empty():
            return df
        mux_bytes = self._mux_bytes_for_selected_id()
        if not mux_bytes or self._selected_mux_case == "All":
            return df
        return df.filter(_mux_label_expr(mux_bytes) == self._selected_mux_case)

    def _mux_bytes_for_selected_id(self) -> tuple[int, ...]:
        can_id = (self._selected_id or "").upper()
        for cfg in self._mux_configs:
            if cfg.can_id == can_id and cfg.length is None:
                return cfg.mux_bytes
        for cfg in self._mux_configs:
            if cfg.can_id == can_id:
                return cfg.mux_bytes
        return ()


def _sorted_can_ids(df: pl.DataFrame) -> list[str]:
    if df is None or df.is_empty() or "ID" not in df.columns:
        return []
    ids = df["ID"].unique().to_list()
    return sorted(ids, key=can_id_sort_key)


def _mux_label_expr(mux_bytes: tuple[int, ...]) -> pl.Expr:
    parts = [pl.col(f"B{i}").fill_null("") for i in mux_bytes]
    return parts[0] if len(parts) == 1 else pl.concat_str(parts, separator=" ")


def _detect_mux_cases(df: pl.DataFrame, mux_bytes: tuple[int, ...]) -> list[str]:
    if df.is_empty() or not mux_bytes:
        return []
    return (
        df.select(_mux_label_expr(mux_bytes).alias("_lbl"))["_lbl"]
        .unique(maintain_order=True)
        .to_list()
    )


def _build_summary(df: pl.DataFrame, can_id: str | None, mux_bytes: tuple[int, ...], mux_case: str) -> dict:
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
    periods = [round(float(ts_values[i]) - float(ts_values[i - 1]), 6) for i in range(1, len(ts_values))]
    payloads = df["DATA"].to_list() if "DATA" in df.columns else []
    payload_changes = (
        (pl.Series(payloads) != pl.Series(payloads).shift(1)).sum()
        if len(payloads) > 1 else 0
    )
    observed_len = (
        ",".join(str(x) for x in sorted(df["LEN"].unique().to_list()))
        if "LEN" in df.columns else ""
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
        column = f"B{i}"
        if column not in df.columns:
            continue
        byte_change_parts.append(f"B{i}:{polars_stats[f'{column}_ch']}")
        byte_unique_parts.append(f"B{i}:{polars_stats[f'{column}_nu']}")
        values = df[column].to_list()
        byte_entropy_parts.append(f"B{i}:{_shannon_entropy(values):.3f}")
        update_periods = _update_periods(ts_values, values)
        if update_periods:
            byte_update_mean_parts.append(f"B{i}:{sum(update_periods) / len(update_periods):.6f}")
            byte_update_min_parts.append(f"B{i}:{min(update_periods):.6f}")
            byte_update_max_parts.append(f"B{i}:{max(update_periods):.6f}")
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
        "Payload Changes": int(payload_changes),
        "Mean Period": f"{(sum(periods) / len(periods)):.6f}" if periods else "",
        "Min Period": f"{min(periods):.6f}" if periods else "",
        "Max Period": f"{max(periods):.6f}" if periods else "",
        "Byte Changes": "  ".join(byte_change_parts),
        "Byte Uniques": "  ".join(byte_unique_parts),
        "Byte Entropy": "  ".join(byte_entropy_parts),
        "Byte Update Mean": "  ".join(byte_update_mean_parts),
        "Byte Update Min": "  ".join(byte_update_min_parts),
        "Byte Update Max": "  ".join(byte_update_max_parts),
    }


def _build_plot_series(df: pl.DataFrame, selected_bytes: set[int]) -> list[ByteSeries]:
    if df.is_empty() or not selected_bytes or "TS" not in df.columns:
        return []
    colors = ["#00d1ff", "#ffd400", "#00ff88", "#ff6b6b", "#c77dff", "#ff9f1c", "#4cc9f0", "#b8f200"]
    ts = [float(x) for x in df["TS"].to_list()]
    result: list[ByteSeries] = []
    for idx in sorted(selected_bytes):
        col = f"D{idx}"
        if col not in df.columns:
            continue
        ys = [int(v) for v in df[col].to_list()]
        result.append(ByteSeries(label=f"B{idx}", x=ts, y=ys, color=colors[idx % len(colors)]))
    return result


def _shannon_entropy(values: list) -> float:
    if not values:
        return 0.0
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    total = len(values)
    entropy = 0.0
    for count in counts.values():
        probability = count / total
        entropy -= probability * log2(probability)
    return entropy


def _update_periods(ts_values: list, values: list) -> list[float]:
    if len(ts_values) != len(values) or len(values) < 2:
        return []
    updates: list[float] = []
    last_change_ts = None
    for idx in range(1, len(values)):
        if values[idx] == values[idx - 1]:
            continue
        current_ts = float(ts_values[idx])
        if last_change_ts is not None:
            updates.append(round(current_ts - last_change_ts, 6))
        last_change_ts = current_ts
    return updates
