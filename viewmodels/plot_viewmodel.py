from __future__ import annotations

import ast
import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import numpy as np
import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal
from PySide6.QtGui import QColor

from config.defaults import SIGNAL_COLOR_PALETTE
from models.frame_selector import FrameSelector
from models.signal import Signal
from services.can_decoder import decode_signal
from services.decoded_signal_cache import DecodedSignalCache
from services.formula_context import build_formula_context
from services.formula_evaluator import FormulaError, evaluate
from services.signal_aligner import align as align_full
from services.signal_aligner import align_incremental
from services.xy_plot import align_xy_series, export_xy_csv
from services.plot_config import (
    build_derived_signal_from_dict,
    build_selector_from_v1_dict,
    build_selector_from_v2_dict,
    build_signal_from_dict,
)
from utils.filters import apply_filter
from utils.plot_sampling import MARKER_MAX_PTS, downsample_series
from viewmodels.derived_view_signal import DerivedViewSignal
from viewmodels.view_signal import ViewSignal


@dataclass
class _DerivedIncrementalState:
    formula: str
    incremental: bool
    ts_chunks: list[np.ndarray] = field(default_factory=list)
    y_chunks: list[np.ndarray] = field(default_factory=list)
    align_last_known: dict[int, list[float | None]] = field(default_factory=dict)
    align_last_ts: dict[int, float] = field(default_factory=dict)

    def materialize(self) -> tuple[np.ndarray, np.ndarray]:
        ts = np.concatenate(self.ts_chunks) if len(self.ts_chunks) > 1 else (
            self.ts_chunks[0] if self.ts_chunks else np.array([], dtype=float)
        )
        values = np.concatenate(self.y_chunks) if len(self.y_chunks) > 1 else (
            self.y_chunks[0] if self.y_chunks else np.array([], dtype=float)
        )
        return ts, values


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
        self._decoded_cache = DecodedSignalCache()
        # Height of self.df already folded into _decoded_cache.
        self._watermark_height = self.df.height
        self._max_points = max_points
        self._derived_cache: dict[str, _DerivedIncrementalState] = {}

    def set_dataframe(self, df: pl.DataFrame):
        df = df if df is not None else pl.DataFrame()
        structural_change = df.height != self._watermark_height
        self.df = df
        if structural_change:
            # Growth ingest_raw_chunk() didn't already account for (file append, etc).
            self._decoded_cache.clear()
            self._watermark_height = df.height
            self._invalidate_derived_cache()
            self.data_changed.emit()

    def reset_dataframe(self, df: pl.DataFrame | None) -> None:
        """Reset incremental decode and derived state after a source replacement."""
        self.df = df if df is not None else pl.DataFrame()
        self._decoded_cache.clear()
        self._watermark_height = self.df.height
        self._invalidate_derived_cache()
        self.data_changed.emit()

    def _invalidate_derived_cache(self) -> None:
        self._derived_cache.clear()

    # ------------------------------------------------------------------
    # Derived signal CRUD
    # ------------------------------------------------------------------

    def upsert_derived(self, dvs: DerivedViewSignal):
        self._ensure_unique_internal_id(self.derived, dvs, ignore_name=dvs.name)
        self.derived[dvs.name] = dvs
        self._invalidate_derived_cache()
        self.data_changed.emit()

    def rename_derived(self, old_name: str, new_dvs: DerivedViewSignal) -> str:
        old_name = str(old_name or "").strip()
        if not old_name or old_name not in self.derived:
            raise KeyError(f"Derived signal not found: {old_name}")
        target = str(new_dvs.name or "").strip() or "Derived"
        if target != old_name and target in self.derived:
            raise ValueError(f"Derived signal name already exists: {target}")
        self._ensure_unique_internal_id(self.derived, new_dvs, ignore_name=old_name)
        self.derived.pop(old_name, None)
        new_dvs.derived.name = target
        self.derived[target] = new_dvs
        self._invalidate_derived_cache()
        self.data_changed.emit()
        return target

    def remove_derived(self, name: str):
        if name in self.derived:
            del self.derived[name]
            self._invalidate_derived_cache()
            self.data_changed.emit()

    def upsert_signal(self, view_signal: ViewSignal):
        self._ensure_unique_internal_id(self.signals, view_signal, ignore_name=view_signal.signal.name)
        self.signals[view_signal.signal.name] = view_signal
        self._invalidate_derived_cache()
        self.data_changed.emit()

    def rename_signal(self, old_name: str, new_view_signal: ViewSignal) -> str:
        old_name = str(old_name or "").strip()
        if not old_name or old_name not in self.signals:
            raise KeyError(f"Signal not found: {old_name}")

        target_name = str(new_view_signal.signal.name or "").strip() or "Signal"
        if target_name != old_name and target_name in self.signals:
            raise ValueError(f"Signal name already exists: {target_name}")

        self._ensure_unique_internal_id(self.signals, new_view_signal, ignore_name=old_name)
        # Remove old key first to avoid temporary duplicates in any observers.
        self.signals.pop(old_name, None)
        self.signals[target_name] = new_view_signal
        self._invalidate_derived_cache()
        self.data_changed.emit()
        return target_name

    def remove_signal(self, name: str):
        if name in self.signals:
            del self.signals[name]
            self._invalidate_derived_cache()
            self.data_changed.emit()

    def duplicate_signal(self, name: str) -> str | None:
        if name in self.signals:
            new_name = self._duplicate_into(
                self.signals, self.signals[name],
                get_name=lambda vs: vs.signal.name,
                set_name=lambda vs, n: setattr(vs.signal, "name", n),
            )
            self._invalidate_derived_cache()
            self.data_changed.emit()
            return new_name
        if name in self.derived:
            new_name = self._duplicate_into(
                self.derived, self.derived[name],
                get_name=lambda dvs: dvs.derived.name,
                set_name=lambda dvs, n: setattr(dvs.derived, "name", n),
            )
            self._invalidate_derived_cache()
            self.data_changed.emit()
            return new_name
        return None

    def _duplicate_into(self, store: dict, original, *, get_name, set_name) -> str:
        new_obj = copy.deepcopy(original)
        base_name = get_name(original)
        i = 1
        new_name = base_name
        taken = set(self.signals) | set(self.derived)
        while new_name in taken:
            new_name = f"{base_name}_{i}"
            i += 1
        set_name(new_obj, new_name)
        new_obj.internal_id = self._new_internal_id()
        new_color = self.next_color()
        new_obj.color = new_color
        new_obj.marker_color = QColor(new_color)
        new_obj.marker_border_color = QColor(new_color)
        store[new_name] = new_obj
        return new_name

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
        for hex_color in SIGNAL_COLOR_PALETTE:
            if QColor(hex_color).name().lower() not in used:
                return QColor(hex_color)
        total = len(self.signals) + len(self.derived)
        return QColor(SIGNAL_COLOR_PALETTE[total % len(SIGNAL_COLOR_PALETTE)])

    def get_signals(self):
        return list(self.signals.values())

    def series_choices(self) -> list[tuple[str, str, str]]:
        """List the raw and derived series currently available to XY."""
        return [
            ("signal", name, name) for name in self.signals
        ] + [
            ("derived", name, f"{name} (Derived)") for name in self.derived
        ]

    def align_xy(
        self,
        x_choice: tuple[str, str],
        y_choice: tuple[str, str],
        *,
        start: float | None = None,
        end: float | None = None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Decode and align two plotted series for a user-requested XY refresh."""
        try:
            x_ts, x_values = self.get_series(*x_choice)
            y_ts, y_values = self.get_series(*y_choice)
        except FormulaError as exc:
            raise ValueError(str(exc)) from exc
        return align_xy_series(x_ts, x_values, y_ts, y_values, start=start, end=end)

    @staticmethod
    def export_xy(
        path: str | Path,
        timestamps: np.ndarray,
        x_values: np.ndarray,
        y_values: np.ndarray,
        *,
        x_name: str,
        y_name: str,
    ) -> None:
        """Export aligned XY values without coupling the view to the service."""
        export_xy_csv(path, timestamps, x_values, y_values, x_name=x_name, y_name=y_name)

    def get_series(self, kind: str, name: str) -> tuple[np.ndarray, np.ndarray]:
        """Return the full timestamp/value arrays for a plotted signal."""
        decoded = {
            signal_name: self._decode_cached(view_signal.signal, view_signal.selector)
            for signal_name, view_signal in self.signals.items()
        }
        if kind == "signal":
            view_signal = self.signals[name]
            timestamps, values = decoded[name]
            return timestamps.copy(), apply_filter(values, view_signal.filter_type, view_signal.filter_params)
        if kind != "derived":
            raise ValueError(f"Unsupported plot series kind: {kind}")
        derived_signal = self.derived[name]
        state = self._derived_cache.get(name)
        if state is not None and state.formula == derived_signal.derived.formula and state.incremental:
            timestamps, values = state.materialize()
        else:
            timestamps, values, _ = self._evaluate_derived(
                derived_signal,
                self.df,
                decoded,
                state=_DerivedIncrementalState(derived_signal.derived.formula, False),
                incremental=False,
            )
        return timestamps.copy(), apply_filter(
            values, derived_signal.filter_type, derived_signal.filter_params,
        )

    def ingest_raw_chunk(self, df_new: pl.DataFrame) -> None:
        """Fed by chunk_ready's raw pre-merge chunk -- merge_frames() can
        resort self.df, so a watermark against it would be unsafe."""
        if df_new is None or df_new.is_empty():
            return
        self._watermark_height += df_new.height
        decoded_new: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        changed = False
        for vs in self.signals.values():
            key = self._decode_signature(vs.signal, vs.selector)
            if key not in self._decoded_cache:
                decoded_new[vs.signal.name] = (
                    np.array([], dtype=float), np.array([], dtype=float),
                )
                continue
            new_ts, new_y = decode_signal(df_new, vs.signal, vs.selector)
            ts_array = np.asarray(new_ts, dtype=float)
            y_array = np.asarray(new_y, dtype=float)
            decoded_new[vs.signal.name] = (ts_array, y_array)
            if not new_ts:
                continue
            self._decoded_cache.extend(key, ts_array, y_array)
            changed = True
        if self.derived:
            changed = self._append_derived_chunk(df_new, decoded_new) or changed
        if changed:
            self.data_changed.emit()

    def _append_derived_chunk(
        self,
        df_new: pl.DataFrame,
        decoded_new: dict[str, tuple[np.ndarray, np.ndarray]],
    ) -> bool:
        changed = False
        for dvs in self.derived.values():
            state = self._derived_cache.get(dvs.name)
            if state is None or not state.incremental or state.formula != dvs.derived.formula:
                continue
            try:
                ts, values, align_overlap = self._evaluate_derived(
                    dvs, df_new, decoded_new, state=state, incremental=True,
                )
            except FormulaError:
                self._derived_cache.pop(dvs.name, None)
                continue
            if align_overlap and ts.size and state.ts_chunks:
                prior_ts = state.ts_chunks[-1]
                if prior_ts.size and float(prior_ts[-1]) == float(ts[0]):
                    prior_values = state.y_chunks[-1]
                    state.ts_chunks[-1] = prior_ts[:-1]
                    state.y_chunks[-1] = prior_values[:-1]
            if ts.size:
                state.ts_chunks.append(ts)
                state.y_chunks.append(values)
                changed = True
        return changed

    @staticmethod
    def _formula_is_incremental(formula: str) -> bool:
        try:
            tree = ast.parse(formula)
        except SyntaxError:
            return False
        dynamic_helpers = {"signal", "raw_bits", "raw_extract", "raw_frames"}
        context_helpers = dynamic_helpers | {"align"}
        numpy_pointwise = {
            "abs", "ceil", "clip", "exp", "floor", "log", "log10", "maximum",
            "minimum", "nan_to_num", "round", "sign", "sin", "sqrt", "where",
        }
        array_pointwise = {"astype", "view"}
        numpy_dtypes = {"float32", "float64", "int32", "int64", "uint8", "uint16", "uint32", "uint64"}
        call_func_ids = {
            id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)
        }
        calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (
                ast.For,
                ast.While,
                ast.If,
                ast.IfExp,
                ast.Match,
                ast.BoolOp,
                ast.Assert,
                ast.Try,
                getattr(ast, "TryStar", ast.Try),
                ast.ListComp,
                ast.SetComp,
                ast.DictComp,
                ast.GeneratorExp,
                ast.Subscript,
            )):
                return False
            if isinstance(node, ast.Attribute):
                if node.attr in array_pointwise and id(node) in call_func_ids:
                    continue
                if (
                    isinstance(node.value, ast.Name)
                    and node.value.id == "np"
                    and node.attr in numpy_pointwise | numpy_dtypes
                ):
                    continue
                return False
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                name = node.func.id
                if name.startswith("bam_"):
                    return False
                if name not in context_helpers:
                    return False
                calls.add(name)
                continue
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in array_pointwise:
                    continue
                if (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "np"
                    and node.func.attr in numpy_pointwise
                ):
                    continue
                return False
            return False
        return bool(calls & dynamic_helpers)

    def _evaluate_derived(
        self,
        dvs: DerivedViewSignal,
        df: pl.DataFrame,
        decoded: dict[str, tuple[np.ndarray, np.ndarray]],
        *,
        state: _DerivedIncrementalState,
        incremental: bool,
    ) -> tuple[np.ndarray, np.ndarray, bool]:
        call_index = 0
        overlap = False

        def align_formula(*series):
            nonlocal call_index, overlap
            index = call_index
            call_index += 1
            if incremental:
                previous = state.align_last_known.get(index, [None] * len(series))
                ts_union, aligned, last = align_incremental(list(series), previous)
                state.align_last_known[index] = last
                if ts_union.size and state.align_last_ts.get(index) == float(ts_union[0]):
                    overlap = True
                if ts_union.size:
                    state.align_last_ts[index] = float(ts_union[-1])
                return ts_union, aligned
            ts_union, aligned = align_full(*series)
            state.align_last_known[index] = [
                float(values[-1]) if len(values) else None for _, values in series
            ]
            if ts_union.size:
                state.align_last_ts[index] = float(ts_union[-1])
            return ts_union, aligned

        context = build_formula_context(df, decoded, align_func=align_formula)
        ts, values = evaluate(dvs.derived.formula, context)
        return ts, values, overlap

    def evaluate_formula_preview(self, formula: str):
        """Decode the currently loaded signals and evaluate *formula* against
        them, for a derived-signal editor's live preview. Raises FormulaError
        (or whatever the sandbox raises) on a bad formula -- callers display it."""
        decoded = {
            name: self._decode_cached(vs.signal, vs.selector)
            for name, vs in self.signals.items()
        }
        context = build_formula_context(self.df, decoded)
        return evaluate(formula, context)

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
            for dvs in self.derived.values():
                try:
                    state = self._derived_cache.get(dvs.name)
                    if state is not None and state.formula != dvs.derived.formula:
                        state = None
                    if state is not None and state.incremental:
                        ts, y = state.materialize()
                    elif state is not None:
                        ts, y, _ = self._evaluate_derived(
                            dvs, self.df, decoded_cache, state=state, incremental=False,
                        )
                    else:
                        state = _DerivedIncrementalState(
                            formula=dvs.derived.formula,
                            incremental=self._formula_is_incremental(dvs.derived.formula),
                        )
                        ts, y, _ = self._evaluate_derived(
                            dvs, self.df, decoded_cache, state=state, incremental=False,
                        )
                        if state.incremental:
                            if ts.size:
                                state.ts_chunks.append(ts)
                                state.y_chunks.append(y)
                            self._derived_cache[dvs.name] = state
                except FormulaError as exc:
                    self._derived_cache.pop(dvs.name, None)
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
                "marker_max_points": vs.marker_max_points,
                "visible": vs.visible,
            },
        }

    def clear(self):
        self.signals.clear()
        self.derived.clear()
        self._invalidate_derived_cache()
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

    @staticmethod
    def _common_style_dict(vs) -> dict:
        """Style/marker/filter fields shared by saved ViewSignal and DerivedViewSignal entries."""
        return {
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
                "max_points": vs.marker_max_points,
            },
            "visible": vs.visible,
        }

    @staticmethod
    def _common_style_kwargs(item: dict) -> dict:
        """Inverse of _common_style_dict."""
        return dict(
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
            marker_max_points=int(item.get("marker", {}).get("max_points", MARKER_MAX_PTS)),
            value_format=str(item.get("value_formatter", {}).get("mode", "auto")),
            value_decimals=int(item.get("value_formatter", {}).get("decimals", 6)),
            value_unit=str(item.get("value_formatter", {}).get("unit", "")),
            step_mode=bool(item.get("step_mode", False)),
            visible=bool(item.get("visible", True)),
        )

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
                    **self._common_style_dict(dvs),
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
                    **self._common_style_dict(vs),
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

                s = build_signal_from_dict(s_data, name=self._unique_signal_name(s_data.get("name", "")))
                sel = build_selector_from_v2_dict(sel_data, fallback_can_id=s.can_id)
                vs = ViewSignal(signal=s, selector=sel, **self._common_style_kwargs(item))
                self._ensure_unique_internal_id(self.signals, vs)
                self.signals[s.name] = vs

            # version 3+: load derived signals
            if version >= 3:
                for item in data.get("derived_signals", []):
                    ds = build_derived_signal_from_dict(item, name=self._unique_derived_name(item.get("name", "")))
                    dvs = DerivedViewSignal(derived=ds, **self._common_style_kwargs(item))
                    self._ensure_unique_internal_id(self.derived, dvs)
                    self.derived[ds.name] = dvs

            self._invalidate_derived_cache()
            self.data_changed.emit()
            return data.get("view") if version >= 4 else None

        for item in data.get("signals", []):
            can_id = item.get("can_id")
            s = build_signal_from_dict(item, name=self._unique_signal_name(item.get("name", "")))
            sel = build_selector_from_v1_dict(item, can_id=can_id)
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
            self._ensure_unique_internal_id(self.signals, vs)
            self.signals[s.name] = vs

        self._invalidate_derived_cache()
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

    def _decode_cached(self, signal: Signal, selector: FrameSelector):
        key = self._decode_signature(signal, selector)
        cached = self._decoded_cache.get(key)
        if cached is not None:
            return cached

        ts, y = decode_signal(self.df, signal, selector)
        ts = np.array(ts)
        y = np.array(y)
        self._decoded_cache.set_full(key, ts, y)
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

    def _ensure_unique_internal_id(
        self, store: dict, obj: ViewSignal | DerivedViewSignal, ignore_name: str | None = None
    ) -> None:
        existing = {
            x.internal_id
            for name, x in store.items()
            if hasattr(x, "internal_id") and name != ignore_name
        }
        candidate = str(getattr(obj, "internal_id", "") or "")
        if not candidate or candidate in existing:
            obj.internal_id = self._new_internal_id()

    def _unique_derived_name(self, base_name: str) -> str:
        base_name = str(base_name or "").strip() or "Derived"
        name = base_name
        index = 1
        while name in self.derived:
            name = f"{base_name}_{index}"
            index += 1
        return name
