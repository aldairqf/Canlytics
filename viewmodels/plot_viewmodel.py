from PySide6.QtCore import QObject, Signal as QtSignal
import copy
import json
import numpy as np
from PySide6.QtGui import QColor
import polars as pl

from core.signal import Signal
from core.filters import apply_filter
from core.can_decoder import decode_signal
from core.plot_sampling import downsample_series
from views.signal.signal_view import ViewSignal


class PlotViewModel(QObject):
    data_changed = QtSignal()

    def __init__(self, df: pl.DataFrame | None = None, max_points: int = 20000):
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
            ts, y = self._decode_cached(vs.signal)
            y = apply_filter(y, vs.filter_type, vs.filter_params)
            ts, y = downsample_series(ts, y, self._max_points)
            plots.append({
                "x": ts.tolist() if isinstance(ts, np.ndarray) else ts,
                "y": y.tolist() if isinstance(y, np.ndarray) else y,
                "label": vs.signal.name,
                "style": {
                    "color": vs.color,
                    "width": vs.line_width,
                    "style": vs.line_style,
                },
            })
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
        data = {"version": 1, "signals": []}
        for vs in self.signals.values():
            s = vs.signal
            data["signals"].append({
                "name": s.name,
                "can_id": s.can_id,
                "id_match": s.id_match,
                "pgn": s.pgn,
                "start_bit": s.start_bit,
                "length": s.length,
                "le": s.le,
                "scale": s.scale,
                "offset": s.offset,
                "mux_start": s.mux_start,
                "mux_bytes": s.mux_bytes,
                "mux_value": s.mux_value,
                "type_data": s.type_data,
                "color": vs.color.name(),
                "line_style": vs.line_style,
                "line_width": vs.line_width,
                "filter_type": vs.filter_type,
                "filter_params": vs.filter_params,
            })
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load_config(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.signals.clear()
        for item in data.get("signals", []):
            s = Signal(
                name=item["name"],
                can_id=item["can_id"],
                id_match=item.get("id_match", "exact"),
                pgn=item.get("pgn"),
                start_bit=item["start_bit"],
                length=item["length"],
                le=item["le"],
                scale=item["scale"],
                offset=item["offset"],
                mux_start=item["mux_start"],
                mux_bytes=item["mux_bytes"],
                mux_value=item["mux_value"],
                type_data=item["type_data"],
            )
            vs = ViewSignal(
                signal=s,
                color=QColor(item["color"]),
                line_style=item["line_style"],
                line_width=item["line_width"],
                filter_type=item.get("filter_type"),
                filter_params=item.get("filter_params", {}),
            )
            self.signals[s.name] = vs
        self.data_changed.emit()

    def parse_signal_data(self, data: dict) -> dict:
        mux_text = (data.get("mux_value") or "").strip()
        mux_bytes = data.get("mux_bytes", 0)
        data.setdefault("id_match", "exact")
        data.setdefault("pgn", None)

        try:
            mux_value = int(mux_text, 0) if mux_text else None
        except ValueError:
            mux_value = None

        if mux_value is not None and mux_bytes > 0:
            max_value = (1 << (mux_bytes * 8)) - 1
            if mux_value > max_value:
                raise ValueError(f"MUX value {mux_value} no cabe en {mux_bytes} bytes")

        data["mux_value"] = mux_value
        return data

    def _decode_cached(self, signal: Signal):
        cache_key = (self._df_version, self._signal_signature(signal))
        if cache_key in self._decoded_cache:
            return self._decoded_cache[cache_key]

        ts, y = decode_signal(self.df, signal)
        ts = np.array(ts)
        y = np.array(y)
        self._decoded_cache[cache_key] = (ts, y)
        return ts, y

    @staticmethod
    def _signal_signature(signal: Signal) -> tuple:
        return (
            signal.name,
            signal.can_id,
            signal.id_match,
            signal.pgn,
            signal.start_bit,
            signal.length,
            signal.le,
            signal.scale,
            signal.offset,
            signal.mux_start,
            signal.mux_bytes,
            signal.mux_value,
            signal.type_data,
        )
