from __future__ import annotations

from dataclasses import dataclass

import polars as pl
from PySide6.QtCore import QObject, Signal

from viewmodels.real_time_analysis_viewmodel import MuxConfigEntry


@dataclass(frozen=True)
class ByteSeries:
    label: str
    x: list[float]
    y: list[int]
    color: str


class AnalyzeDataViewModel(QObject):
    can_ids_changed = Signal(list)
    mux_cases_changed = Signal(list)
    summary_changed = Signal(dict)
    plot_changed = Signal(object)
    selected_id_changed = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._df = pl.DataFrame()
        self._selected_id: str | None = None
        self._selected_bytes: set[int] = set(range(8))
        self._mux_configs: list[MuxConfigEntry] = []
        self._selected_mux_case = "All"

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
        self._selected_mux_case = (case_label or "All").strip() or "All"
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
        df = self._df.filter(pl.col("ID") == self._selected_id)
        if raw_id_only:
            return df
        return df

    def _apply_mux_case(self, df: pl.DataFrame) -> pl.DataFrame:
        if df.is_empty():
            return df
        mux_bytes = self._mux_bytes_for_selected_id()
        if not mux_bytes or self._selected_mux_case == "All":
            return df
        labels = [_mux_case_label_for_row(row, mux_bytes) for row in df.iter_rows(named=True)]
        if not labels:
            return df
        mask = [label == self._selected_mux_case for label in labels]
        return df.filter(pl.Series(mask))

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
    return sorted(ids, key=_can_id_sort_key)


def _can_id_sort_key(value: str) -> tuple[int, int | str]:
    text = str(value or "").strip().upper()
    try:
        return (0, int(text, 16))
    except ValueError:
        return (1, text)


def _mux_case_label_for_row(row: dict, mux_bytes: tuple[int, ...]) -> str:
    if not mux_bytes:
        return "No MUX"
    return " ".join(str(row.get(f"B{i}") or "").upper() for i in mux_bytes)


def _detect_mux_cases(df: pl.DataFrame, mux_bytes: tuple[int, ...]) -> list[str]:
    if df.is_empty() or not mux_bytes:
        return []
    seen: dict[str, None] = {}
    for row in df.iter_rows(named=True):
        seen.setdefault(_mux_case_label_for_row(row, mux_bytes), None)
    return list(seen.keys())


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
        }

    ts_values = df["TS"].to_list() if "TS" in df.columns else []
    periods = [round(float(ts_values[i]) - float(ts_values[i - 1]), 6) for i in range(1, len(ts_values))]
    payloads = df["DATA"].to_list() if "DATA" in df.columns else []
    payload_changes = sum(1 for i in range(1, len(payloads)) if payloads[i] != payloads[i - 1])
    observed_len = ",".join(str(x) for x in sorted(set(df["LEN"].to_list()))) if "LEN" in df.columns else ""

    byte_change_parts: list[str] = []
    for i in range(8):
        column = f"B{i}"
        if column not in df.columns:
            continue
        values = df[column].to_list()
        changes = sum(1 for idx in range(1, len(values)) if values[idx] != values[idx - 1])
        byte_change_parts.append(f"B{i}:{changes}")

    return {
        "CAN ID": can_id or "",
        "Frames": int(df.height),
        "MUX Bytes": ",".join(str(i) for i in mux_bytes) or "None",
        "MUX Case": mux_case,
        "Observed LEN": observed_len,
        "Distinct Payloads": len(set(payloads)),
        "Payload Changes": payload_changes,
        "Mean Period": f"{(sum(periods) / len(periods)):.6f}" if periods else "",
        "Min Period": f"{min(periods):.6f}" if periods else "",
        "Max Period": f"{max(periods):.6f}" if periods else "",
        "Byte Changes": "  ".join(byte_change_parts),
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
