from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal

from canlytics_sdk import DbcMessageInfo, DbcSignalInfo
from models.plugin import PluginRecord
from services.analyze_data import build_summary
from services.can_data_parser import FRAME_SCHEMA
from services.log_export import export_dataframe
from services.plugin_manager import PluginManager
from services.range_diff import TimeRange, build_range_diff_report
from services.candidate_interpretations import build_candidate_items


class _PluginAnalysis:
    def summarize(self, dataframe: pl.DataFrame, can_id: str | None = None) -> dict[str, Any]:
        selected = dataframe
        if can_id is not None:
            if "ID" not in dataframe.columns:
                raise ValueError("The frame table does not contain an ID column")
            selected = dataframe.filter(pl.col("ID") == str(can_id))
        return build_summary(selected, can_id, (), "")

    def candidates(
        self,
        dataframe: pl.DataFrame,
        can_ids: set[str],
        *,
        min_length: int = 8,
        max_length: int = 8,
        granularity: int = 8,
        endianness: str = "Little Endian",
        value_type: str = "Unsigned",
        include_constant: bool = False,
        mux_configs: list | None = None,
        byte_indices: set[int] | None = None,
    ) -> list[Any]:
        return build_candidate_items(
            dataframe,
            checked_ids=set(can_ids),
            mux_configs=list(mux_configs or []),
            min_length=min_length,
            max_length=max_length,
            granularity=granularity,
            endianness=endianness,
            value_type=value_type,
            include_constant=include_constant,
            byte_indices=byte_indices,
        )

    def compare_ranges(
        self,
        dataframe: pl.DataFrame,
        start_a: float,
        end_a: float,
        start_b: float,
        end_b: float,
    ) -> Any:
        return build_range_diff_report(dataframe, TimeRange(start_a, end_a), TimeRange(start_b, end_b))


class _PluginContext:
    def __init__(self, host: Any):
        self._host = host
        self._analysis = _PluginAnalysis()

    @property
    def frame_schema(self) -> dict[str, str]:
        return {name: str(dtype) for name, dtype in FRAME_SCHEMA.items()}

    def get_frames(self) -> pl.DataFrame:
        return self._host.data_vm.df.clone()

    def list_dbc_names(self) -> tuple[str, ...]:
        return tuple(entry.name for entry in self._host.dbc_manager.list_entries())

    def decode_frame(self, can_id: str, data_hex: str) -> tuple[dict[str, Any], ...]:
        return tuple(self._host.dbc_manager.decode_frame(can_id, data_hex))

    def get_working_dbc_messages(self) -> tuple[DbcMessageInfo, ...]:
        messages = []
        for message in self._host.working_dbc.list_messages():
            signals = tuple(
                DbcSignalInfo(
                    name=signal.name,
                    start=signal.start,
                    length=signal.length,
                    scale=signal.scale,
                    offset=signal.offset,
                    unit=signal.unit or "",
                )
                for signal in message.signals
            )
            messages.append(DbcMessageInfo(message.frame_id, message.name, message.length, signals))
        return tuple(messages)

    @property
    def analysis(self) -> _PluginAnalysis:
        return self._analysis

    def export_log(self, dataframe: pl.DataFrame, path: str) -> str:
        protected = [*self._host.data_vm.source_paths, self._host.session_state.working_dbc_path]
        protected.extend(entry.path for entry in self._host.dbc_manager.list_entries())
        return str(export_dataframe(dataframe, path, protected_paths=protected))


class PluginViewModel(QObject):
    plugins_changed = QtSignal(object)

    def __init__(self, host: Any, parent: QObject | None = None):
        super().__init__(parent)
        self._host = host
        self._context = _PluginContext(host)
        self._manager = PluginManager(host.session_state.root / "plugins.json")

    def refresh(self) -> tuple[PluginRecord, ...]:
        records = self._manager.discover()
        for record in records:
            if record.enabled and not record.loaded:
                self._manager.set_enabled(record.id, True, self._context)
        records = self._manager.records()
        self.plugins_changed.emit(records)
        return records

    def set_enabled(self, plugin_id: str, enabled: bool) -> tuple[PluginRecord, ...]:
        self._manager.set_enabled(plugin_id, enabled, self._context if enabled else None)
        records = self._manager.records()
        self.plugins_changed.emit(records)
        return records

    def plugin_directories(self) -> tuple[Path, ...]:
        return self._manager.plugin_dirs

    def shutdown(self) -> None:
        self._manager.shutdown()
