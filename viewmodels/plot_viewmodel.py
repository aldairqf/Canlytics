from __future__ import annotations

import copy
import json

import numpy as np
import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal
from PySide6.QtGui import QColor

from models.frame_selector import FrameSelector
from models.signal import Signal
from services.can_decoder import decode_signal
from utils.filters import apply_filter
from utils.plot_sampling import downsample_series
from viewmodels.view_signal import ViewSignal


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
        self._df_version = 0
        self._decoded_cache: dict[tuple[int, tuple], tuple[np.ndarray, np.ndarray]] = {}
        self._max_points = max_points

    def set_dataframe(self, df: pl.DataFrame):
        self.df = df
        self._df_version += 1
        self._decoded_cache.clear()
        self.data_changed.emit()

    def upsert_signal(self, view_signal: ViewSignal):
        self.signals[view_signal.signal.name] = view_signal
        self.data_changed.emit()

    def remove_signal(self, name: str):
        if name in self.signals:
            del self.signals[name]
            self.data_changed.emit()

    def duplicate_signal(self, name: str) -> str | None:
        if name not in self.signals:
            return None
        original = self.signals[name]
        new_vs = copy.deepcopy(original)
        base_name = original.signal.name
        i = 1
        new_name = base_name
        while new_name in self.signals:
            new_name = f"{base_name}_{i}"
            i += 1
        new_vs.signal.name = new_name
        self.signals[new_name] = new_vs
        self.data_changed.emit()
        return new_name

    def get_signals(self):
        return list(self.signals.values())

    def get_plot_data(self, normalize_time: bool = False):
        plots = []
        for vs in self.signals.values():
            ts, y = self._decode_cached(vs.signal, vs.selector)
            y = apply_filter(y, vs.filter_type, vs.filter_params)
            ts, y = downsample_series(ts, y, self._max_points)
            plots.append(
                {
                    "x": ts.tolist() if isinstance(ts, np.ndarray) else ts,
                    "y": y.tolist() if isinstance(y, np.ndarray) else y,
                    "label": vs.signal.name,
                    "style": {
                        "color": vs.color,
                        "width": vs.line_width,
                        "style": vs.line_style,
                    },
                }
            )
        if normalize_time:
            min_t0 = min((s["x"][0] for s in plots if len(s["x"]) > 0), default=None)
            if min_t0 is not None:
                for s in plots:
                    s["x"] = (np.array(s["x"]) - min_t0).tolist()
        return plots

    def clear(self):
        self.signals.clear()
        self.data_changed.emit()

    def save_config(self, path: str):
        data = {"version": 2, "signals": []}
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
                    "filter_type": vs.filter_type,
                    "filter_params": vs.filter_params,
                }
            )
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load_config(self, path: str):
        self._load_config_file(path, replace_existing=True)

    def append_config(self, path: str):
        self._load_config_file(path, replace_existing=False)

    def _load_config_file(self, path: str, *, replace_existing: bool):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if replace_existing:
            self.signals.clear()
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
                )
                self.signals[s.name] = vs

            self.data_changed.emit()
            return

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
            )
            self.signals[s.name] = vs

        self.data_changed.emit()

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

    def parse_signal_data(self, data: dict) -> dict:
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
