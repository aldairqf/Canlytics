from __future__ import annotations

import copy
import json
from uuid import uuid4

import numpy as np
import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal
from PySide6.QtGui import QColor

from models.derived_signal import DerivedSignal
from models.derived_view_signal import DerivedViewSignal
from models.frame_selector import FrameSelector
from models.signal import Signal
from services.can_decoder import decode_signal
from services.formula_context import build_formula_context
from services.formula_evaluator import FormulaError, evaluate
from utils.filters import apply_filter
from utils.plot_sampling import downsample_series
from viewmodels.view_signal import ViewSignal


_COLOR_PALETTE = [
    "#00ffff", "#ff6b6b", "#ffd93d", "#6bcb77", "#4d96ff",
    "#ff922b", "#cc5de8", "#f06595", "#74c0fc", "#a9e34b",
]


class PlotViewModel(QObject):
    data_changed = QtSignal()

    def __init__(
        self,
        df: pl.DataFrame | None = None,
        max_points: int = 20000,
    ):
        super().__init__()
        self.df = df if df is not None else pl.DataFrame()
        self.signals: dict[str, ViewSignal] = {}
        self.derived: dict[str, DerivedViewSignal] = {}
        self._df_version = 0
        self._decoded_cache: dict[tuple[int, tuple], tuple[np.ndarray, np.ndarray]] = {}
        self._max_points = max_points

    def set_dataframe(self, df: pl.DataFrame):
        self.df = df
        self._df_version += 1
        self._decoded_cache.clear()
        self.data_changed.emit()

    # ------------------------------------------------------------------
    # Derived signal CRUD
    # ------------------------------------------------------------------

    def upsert_derived(self, dvs: DerivedViewSignal):
        self._ensure_derived_internal_id(dvs, ignore_name=dvs.name)
        self.derived[dvs.name] = dvs
        self.data_changed.emit()

    def rename_derived(self, old_name: str, new_dvs: DerivedViewSignal) -> str:
        old_name = str(old_name or "").strip()
        if not old_name or old_name not in self.derived:
            raise KeyError(f"Derived signal not found: {old_name}")
        target = str(new_dvs.name or "").strip() or "Derived"
        if target != old_name and target in self.derived:
            raise ValueError(f"Derived signal name already exists: {target}")
        self._ensure_derived_internal_id(new_dvs, ignore_name=old_name)
        self.derived.pop(old_name, None)
        new_dvs.derived.name = target
        self.derived[target] = new_dvs
        self.data_changed.emit()
        return target

    def remove_derived(self, name: str):
        if name in self.derived:
            del self.derived[name]
            self.data_changed.emit()

    def upsert_signal(self, view_signal: ViewSignal):
        self._ensure_internal_id(view_signal, ignore_name=view_signal.signal.name)
        self.signals[view_signal.signal.name] = view_signal
        self.data_changed.emit()

    def rename_signal(self, old_name: str, new_view_signal: ViewSignal) -> str:
        old_name = str(old_name or "").strip()
        if not old_name or old_name not in self.signals:
            raise KeyError(f"Signal not found: {old_name}")

        target_name = str(new_view_signal.signal.name or "").strip() or "Signal"
        if target_name != old_name and target_name in self.signals:
            raise ValueError(f"Signal name already exists: {target_name}")

        self._ensure_internal_id(new_view_signal, ignore_name=old_name)
        # Remove old key first to avoid temporary duplicates in any observers.
        self.signals.pop(old_name, None)
        self.signals[target_name] = new_view_signal
        self.data_changed.emit()
        return target_name

    def remove_signal(self, name: str):
        if name in self.signals:
            del self.signals[name]
            self.data_changed.emit()

    def duplicate_signal(self, name: str) -> str | None:
        if name in self.signals:
            original = self.signals[name]
            new_vs = copy.deepcopy(original)
            base_name = original.signal.name
            i = 1
            new_name = base_name
            taken = set(self.signals) | set(self.derived)
            while new_name in taken:
                new_name = f"{base_name}_{i}"
                i += 1
            new_vs.signal.name = new_name
            new_vs.internal_id = self._new_internal_id()
            new_color = self.next_color()
            new_vs.color = new_color
            new_vs.marker_color = QColor(new_color)
            new_vs.marker_border_color = QColor(new_color)
            self.signals[new_name] = new_vs
            self.data_changed.emit()
            return new_name
        if name in self.derived:
            original_dvs = self.derived[name]
            new_dvs = copy.deepcopy(original_dvs)
            base_name = original_dvs.derived.name
            i = 1
            new_name = base_name
            taken = set(self.signals) | set(self.derived)
            while new_name in taken:
                new_name = f"{base_name}_{i}"
                i += 1
            new_dvs.derived.name = new_name
            new_dvs.internal_id = self._new_internal_id()
            new_color = self.next_color()
            new_dvs.color = new_color
            new_dvs.marker_color = QColor(new_color)
            new_dvs.marker_border_color = QColor(new_color)
            self.derived[new_name] = new_dvs
            self.data_changed.emit()
            return new_name
        return None

    def next_color(self) -> QColor:
        # Pick the first palette color not already in use by a raw or derived
        # signal so every series in a plot stays visually distinct, regardless
        # of the entry route or of signals having been removed. Only once the
        # whole palette is taken do we wrap around by total count.
        used = {
            c.name().lower()
            for c in [vs.color for vs in self.signals.values()]
            + [dvs.color for dvs in self.derived.values()]
            if isinstance(c, QColor)
        }
        for hex_color in _COLOR_PALETTE:
            if QColor(hex_color).name().lower() not in used:
                return QColor(hex_color)
        total = len(self.signals) + len(self.derived)
        return QColor(_COLOR_PALETTE[total % len(_COLOR_PALETTE)])

    def get_signals(self):
        return list(self.signals.values())

    def get_plot_data(self, normalize_time: bool = False):
        plots = []

        # ---- raw / DBC signals ----
        decoded_cache: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for vs in self.signals.values():
            ts, y = self._decode_cached(vs.signal, vs.selector)
            decoded_cache[vs.signal.name] = (ts, y)
            y = apply_filter(y, vs.filter_type, vs.filter_params)
            ts, y = downsample_series(ts, y, self._max_points)
            plots.append(self._make_plot_entry(vs.internal_id, vs.signal.name, ts, y, vs))

        # ---- derived signals ----
        if self.derived:
            context = build_formula_context(self.df, decoded_cache)
            for dvs in self.derived.values():
                try:
                    ts, y = evaluate(dvs.derived.formula, context)
                except FormulaError as exc:
                    ts = np.array([])
                    y = np.array([])
                    label = f"[error] {dvs.name}"
                    plots.append(self._make_plot_entry(dvs.internal_id, label, ts, y, dvs))
                    continue
                y = apply_filter(y, dvs.filter_type, dvs.filter_params)
                ts, y = downsample_series(ts, y, self._max_points)
                plots.append(self._make_plot_entry(dvs.internal_id, dvs.name, ts, y, dvs))

        if normalize_time:
            min_t0 = min((s["x"][0] for s in plots if len(s["x"]) > 0), default=None)
            if min_t0 is not None:
                for s in plots:
                    s["x"] = (np.array(s["x"]) - min_t0).tolist()
        return plots

    @staticmethod
    def _make_plot_entry(internal_id, label, ts, y, vs) -> dict:
        return {
            "id": internal_id,
            "x": ts.tolist() if isinstance(ts, np.ndarray) else ts,
            "y": y.tolist() if isinstance(y, np.ndarray) else y,
            "label": label,
            "style": {
                "color": vs.color,
                "width": vs.line_width,
                "style": vs.line_style,
                "step_mode": vs.step_mode,
                "value_format": vs.value_format,
                "value_decimals": vs.value_decimals,
                "value_unit": vs.value_unit,
                "marker_enabled": vs.marker_enabled,
                "marker_shape": vs.marker_shape,
                "marker_size": vs.marker_size,
                "marker_color": vs.marker_color,
                "marker_border_color": vs.marker_border_color,
                "marker_border_width": vs.marker_border_width,
                "visible": vs.visible,
            },
        }

    def clear(self):
        self.signals.clear()
        self.derived.clear()
        self.data_changed.emit()

    def set_signal_visible(self, internal_id: str, visible: bool) -> None:
        for vs in self.signals.values():
            if vs.internal_id == internal_id:
                vs.visible = visible
                return
        for dvs in self.derived.values():
            if dvs.internal_id == internal_id:
                dvs.visible = visible
                return

    def save_config(self, path: str, view_config: dict | None = None):
        data: dict = {"version": 4, "signals": [], "derived_signals": []}
        if view_config:
            data["view"] = view_config
        for dvs in self.derived.values():
            data["derived_signals"].append(
                {
                    "name": dvs.derived.name,
                    "formula": dvs.derived.formula,
                    "inputs": dvs.derived.inputs,
                    "simple_config": dvs.derived.simple_config,
                    "color": dvs.color.name(),
                    "line_style": dvs.line_style,
                    "line_width": dvs.line_width,
                    "step_mode": dvs.step_mode,
                    "value_formatter": {
                        "mode": dvs.value_format,
                        "decimals": dvs.value_decimals,
                        "unit": dvs.value_unit,
                    },
                    "filter_type": dvs.filter_type,
                    "filter_params": dvs.filter_params,
                    "internal_id": dvs.internal_id,
                    "marker": {
                        "enabled": dvs.marker_enabled,
                        "shape": dvs.marker_shape,
                        "size": dvs.marker_size,
                        "color": dvs.marker_color.name(),
                        "border_color": dvs.marker_border_color.name(),
                        "border_width": dvs.marker_border_width,
                    },
                    "visible": dvs.visible,
                }
            )
        for vs in self.signals.values():
            s = vs.signal
            sel = vs.selector
            data["signals"].append(
                {
                    "signal": {
                        "name": s.name,
                        "can_id": s.can_id,
                        "start_bit": s.start_bit,
                        "length": s.length,
                        "le": s.le,
                        "scale": s.scale,
                        "offset": s.offset,
                        "mux_start": s.mux_start,
                        "mux_bytes": s.mux_bytes,
                        "mux_value": s.mux_value,
                        "type_data": s.type_data,
                    },
                    "selector": {
                        "selected_id": sel.selected_id,
                        "mode": sel.mode,
                        "pgn": sel.pgn,
                        "target_id": sel.target_id,
                    },
                    "color": vs.color.name(),
                    "line_style": vs.line_style,
                    "line_width": vs.line_width,
                    "step_mode": vs.step_mode,
                    "value_formatter": {
                        "mode": vs.value_format,
                        "decimals": vs.value_decimals,
                        "unit": vs.value_unit,
                    },
                    "filter_type": vs.filter_type,
                    "filter_params": vs.filter_params,
                    "internal_id": vs.internal_id,
                    "marker": {
                        "enabled": vs.marker_enabled,
                        "shape": vs.marker_shape,
                        "size": vs.marker_size,
                        "color": vs.marker_color.name(),
                        "border_color": vs.marker_border_color.name(),
                        "border_width": vs.marker_border_width,
                    },
                    "visible": vs.visible,
                }
            )
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load_config(self, path: str) -> dict | None:
        return self._load_config_file(path, replace_existing=True)

    def append_config(self, path: str) -> dict | None:
        return self._load_config_file(path, replace_existing=False)

    def _load_config_file(self, path: str, *, replace_existing: bool) -> dict | None:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if replace_existing:
            self.signals.clear()
            self.derived.clear()
        version = int(data.get("version", 1))

        if version >= 2:
            for item in data.get("signals", []):
                s_data = item.get("signal", {})
                sel_data = item.get("selector", {})

                s = Signal(
                    name=self._unique_signal_name(s_data.get("name", "")),
                    can_id=s_data.get("can_id"),
                    start_bit=int(s_data.get("start_bit", 0)),
                    length=int(s_data.get("length", 8)),
                    le=bool(s_data.get("le", True)),
                    scale=float(s_data.get("scale", 1.0)),
                    offset=float(s_data.get("offset", 0.0)),
                    mux_start=int(s_data.get("mux_start", 0)),
                    mux_bytes=int(s_data.get("mux_bytes", 0)),
                    mux_value=self._maybe_int(s_data.get("mux_value", None)),
                    type_data=str(s_data.get("type_data", "uint")),
                )
                sel = FrameSelector(
                    selected_id=sel_data.get("selected_id") or s.can_id,
                    mode=sel_data.get("mode", "exact"),
                    pgn=sel_data.get("pgn"),
                    target_id=sel_data.get("target_id"),
                )
                vs = ViewSignal(
                    signal=s,
                    selector=sel,
                    color=QColor(item["color"]),
                    line_style=item["line_style"],
                    line_width=item["line_width"],
                    filter_type=item.get("filter_type"),
                    filter_params=item.get("filter_params", {}),
                    internal_id=item.get("internal_id"),
                    marker_enabled=bool(item.get("marker", {}).get("enabled", False)),
                    marker_shape=str(item.get("marker", {}).get("shape", "Circle")),
                    marker_size=int(item.get("marker", {}).get("size", 8)),
                    marker_color=QColor(item.get("marker", {}).get("color", item["color"])),
                    marker_border_color=QColor(item.get("marker", {}).get("border_color", item["color"])),
                    marker_border_width=int(item.get("marker", {}).get("border_width", 1)),
                    value_format=str(item.get("value_formatter", {}).get("mode", "auto")),
                    value_decimals=int(item.get("value_formatter", {}).get("decimals", 6)),
                    value_unit=str(item.get("value_formatter", {}).get("unit", "")),
                    step_mode=bool(item.get("step_mode", False)),
                    visible=bool(item.get("visible", True)),
                )
                self._ensure_internal_id(vs)
                self.signals[s.name] = vs

            # version 3+: load derived signals
            if version >= 3:
                for item in data.get("derived_signals", []):
                    ds = DerivedSignal(
                        name=self._unique_derived_name(item.get("name", "")),
                        formula=item.get("formula", ""),
                        inputs=list(item.get("inputs", [])),
                        simple_config=item.get("simple_config"),
                    )
                    dvs = DerivedViewSignal(
                        derived=ds,
                        color=QColor(item["color"]),
                        line_style=item["line_style"],
                        line_width=item["line_width"],
                        filter_type=item.get("filter_type"),
                        filter_params=item.get("filter_params", {}),
                        internal_id=item.get("internal_id"),
                        marker_enabled=bool(item.get("marker", {}).get("enabled", False)),
                        marker_shape=str(item.get("marker", {}).get("shape", "Circle")),
                        marker_size=int(item.get("marker", {}).get("size", 8)),
                        marker_color=QColor(item.get("marker", {}).get("color", item["color"])),
                        marker_border_color=QColor(item.get("marker", {}).get("border_color", item["color"])),
                        marker_border_width=int(item.get("marker", {}).get("border_width", 1)),
                        value_format=str(item.get("value_formatter", {}).get("mode", "auto")),
                        value_decimals=int(item.get("value_formatter", {}).get("decimals", 6)),
                        value_unit=str(item.get("value_formatter", {}).get("unit", "")),
                        step_mode=bool(item.get("step_mode", False)),
                        visible=bool(item.get("visible", True)),
                    )
                    self._ensure_derived_internal_id(dvs)
                    self.derived[ds.name] = dvs

            self.data_changed.emit()
            return data.get("view") if version >= 4 else None

        for item in data.get("signals", []):
            can_id = item.get("can_id")
            s = Signal(
                name=self._unique_signal_name(item.get("name", "")),
                can_id=can_id,
                start_bit=int(item.get("start_bit", 0)),
                length=int(item.get("length", 8)),
                le=bool(item.get("le", True)),
                scale=float(item.get("scale", 1.0)),
                offset=float(item.get("offset", 0.0)),
                mux_start=int(item.get("mux_start", 0)),
                mux_bytes=int(item.get("mux_bytes", 0)),
                mux_value=self._maybe_int(item.get("mux_value", None)),
                type_data=str(item.get("type_data", "uint")),
            )
            mode = item.get("id_match", "exact")
            sel = FrameSelector(
                selected_id=can_id,
                mode=mode if mode in ("exact", "j1939", "bam") else "exact",
                pgn=item.get("pgn"),
                target_id=None,
            )
            vs = ViewSignal(
                signal=s,
                selector=sel,
                color=QColor(item["color"]),
                line_style=item["line_style"],
                line_width=item["line_width"],
                filter_type=item.get("filter_type"),
                filter_params=item.get("filter_params", {}),
                marker_enabled=bool(item.get("marker_enabled", False)),
                marker_shape=str(item.get("marker_shape", "Circle")),
                marker_size=int(item.get("marker_size", 8)),
                marker_color=QColor(item.get("marker_color", item["color"])),
                marker_border_color=QColor(item.get("marker_border_color", item["color"])),
                marker_border_width=int(item.get("marker_border_width", 1)),
                value_format=str(item.get("value_format", "auto")),
                value_decimals=int(item.get("value_decimals", 6)),
                value_unit=str(item.get("value_unit", "")),
                step_mode=bool(item.get("step_mode", False)),
            )
            self._ensure_internal_id(vs)
            self.signals[s.name] = vs

        self.data_changed.emit()
        return None

    def _unique_signal_name(self, base_name: str) -> str:
        base_name = str(base_name or "").strip() or "Signal"
        name = base_name
        index = 1
        while name in self.signals:
            name = f"{base_name}_{index}"
            index += 1
        return name

    @staticmethod
    def _maybe_int(value):
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def parse_signal_data(data: dict) -> dict:
        if "signal" in data or "selector" in data:
            signal_data = dict(data.get("signal") or {})
            selector_data = dict(data.get("selector") or {})
        else:
            signal_data = {
                "name": data.get("name", ""),
                "can_id": data.get("can_id") or data.get("can_id"),
                "start_bit": data.get("start_bit", 0),
                "length": data.get("length", 8),
                "le": data.get("le", True),
                "scale": data.get("scale", 1.0),
                "offset": data.get("offset", 0.0),
                "mux_start": data.get("mux_start", 0),
                "mux_bytes": data.get("mux_bytes", 0),
                "mux_value": data.get("mux_value", None),
                "type_data": data.get("type_data", "uint"),
            }
            selector_data = {
                "selected_id": data.get("can_id"),
                "mode": data.get("id_match", "exact"),
                "pgn": data.get("pgn"),
                "target_id": None,
            }

        mux_text = str(signal_data.get("mux_value") or "").strip()
        mux_bytes = int(signal_data.get("mux_bytes", 0))

        try:
            mux_value = int(mux_text, 0) if mux_text else None
        except ValueError:
            mux_value = None

        if mux_value is not None and mux_bytes > 0:
            max_value = (1 << (mux_bytes * 8)) - 1
            if mux_value > max_value:
                raise ValueError(f"MUX value {mux_value} no cabe en {mux_bytes} bytes")

        signal_data["mux_value"] = mux_value
        signal_data.setdefault("type_data", "uint")
        signal_data.setdefault("can_id", None)

        selector_data.setdefault("selected_id", signal_data.get("can_id"))
        selector_data.setdefault("mode", "exact")
        selector_data.setdefault("pgn", None)
        selector_data.setdefault("target_id", None)

        return {"signal": signal_data, "selector": selector_data}

    def _decode_cached(self, signal: Signal, selector: FrameSelector):
        cache_key = (self._df_version, self._decode_signature(signal, selector))
        if cache_key in self._decoded_cache:
            return self._decoded_cache[cache_key]

        ts, y = decode_signal(self.df, signal, selector)
        ts = np.array(ts)
        y = np.array(y)
        self._decoded_cache[cache_key] = (ts, y)
        return ts, y

    @staticmethod
    def _decode_signature(signal: Signal, selector: FrameSelector) -> tuple:
        return (
            signal.name,
            signal.can_id,
            signal.start_bit,
            signal.length,
            signal.le,
            signal.scale,
            signal.offset,
            signal.mux_start,
            signal.mux_bytes,
            signal.mux_value,
            signal.type_data,
            selector.selected_id,
            selector.mode,
            selector.pgn,
            selector.target_id,
        )

    @staticmethod
    def _new_internal_id() -> str:
        return uuid4().hex

    def _ensure_internal_id(self, vs: ViewSignal, ignore_name: str | None = None) -> None:
        existing = {
            x.internal_id
            for name, x in self.signals.items()
            if hasattr(x, "internal_id") and name != ignore_name
        }
        candidate = str(getattr(vs, "internal_id", "") or "")
        if not candidate or candidate in existing:
            vs.internal_id = self._new_internal_id()

    def _ensure_derived_internal_id(
        self, dvs: DerivedViewSignal, ignore_name: str | None = None
    ) -> None:
        existing = {
            x.internal_id
            for name, x in self.derived.items()
            if name != ignore_name
        }
        candidate = str(getattr(dvs, "internal_id", "") or "")
        if not candidate or candidate in existing:
            dvs.internal_id = self._new_internal_id()

    def _unique_derived_name(self, base_name: str) -> str:
        base_name = str(base_name or "").strip() or "Derived"
        name = base_name
        index = 1
        while name in self.derived:
            name = f"{base_name}_{index}"
            index += 1
        return name
