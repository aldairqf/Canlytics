from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal, Slot

from canlytics_sdk import DbcMessageInfo, DbcSignalInfo
from models.analysis_context import AnalysisContext
from models.plugin import PluginRecord
from services.analyze_data import build_summary
from services.can_data_parser import FRAME_SCHEMA
from services.log_export import export_dataframe
from services.plugin_manager import PluginManager
from services.range_diff import TimeRange, build_range_diff_report
from services.candidate_interpretations import build_candidate_items

logger = logging.getLogger(__name__)


class _PluginChunkBridge(QObject):
    chunk_received = QtSignal(object)

    def __init__(self, callback: Callable[[pl.DataFrame], None], plugin_id: str, parent: QObject) -> None:
        super().__init__(parent)
        self._callback = callback
        self._plugin_id = plugin_id
        self.chunk_received.connect(self._deliver)

    @Slot(object)
    def receive(self, chunk: pl.DataFrame) -> None:
        self.chunk_received.emit(chunk)

    @Slot(object)
    def _deliver(self, chunk: pl.DataFrame) -> None:
        try:
            self._callback(chunk.clone())
        except Exception:
            logger.exception("Plugin %s live chunk listener failed", self._plugin_id)


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
    def __init__(self, host: Any) -> None:
        self._host = host
        self._analysis = _PluginAnalysis()
        self._subscriptions: dict[str, list[Any]] = {}

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

    def list_session_markers(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._host.mcp_session_vm.snapshot.list_session_markers())

    def send_frame(self, can_id: int | str, data: bytes | str, *, extended: bool = False) -> str:
        return self._host.can_send_vm.send_plugin_frame(can_id, data, extended=extended)

    def scoped(self, plugin_id: str) -> _PluginContextScope:
        return _PluginContextScope(self, plugin_id)

    def subscribe_live_chunks(
        self,
        callback: Callable[[pl.DataFrame], None],
        *,
        lifetime: QObject,
        plugin_id: str = "",
    ) -> Callable[[], None]:
        if not callable(callback) or lifetime is None or not hasattr(lifetime, "destroyed"):
            raise ValueError("A chunk subscription needs a callback and a QWidget lifetime")

        bridge = _PluginChunkBridge(callback, plugin_id, self._host)
        connection = self._host.connection_vm.chunk_ready
        connection.connect(bridge.receive)
        active = True

        def unsubscribe(*_args: object) -> None:
            nonlocal active
            if not active:
                return
            active = False
            try:
                connection.disconnect(bridge.receive)
            except (RuntimeError, TypeError):
                pass
            bridge.deleteLater()
            subscriptions = self._subscriptions.get(plugin_id, [])
            if unsubscribe in subscriptions:
                subscriptions.remove(unsubscribe)

        self._subscriptions.setdefault(plugin_id, []).append(unsubscribe)
        lifetime.destroyed.connect(unsubscribe)
        return unsubscribe

    def unsubscribe_owner(self, plugin_id: str) -> None:
        for unsubscribe in tuple(self._subscriptions.get(plugin_id, ())):
            unsubscribe()


class _PluginContextScope:
    def __init__(self, context: _PluginContext, plugin_id: str) -> None:
        self._context = context
        self._plugin_id = plugin_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._context, name)

    def subscribe_live_chunks(
        self, callback: Callable[[pl.DataFrame], None], *, lifetime: QObject
    ) -> Callable[[], None]:
        return self._context.subscribe_live_chunks(callback, lifetime=lifetime, plugin_id=self._plugin_id)


class PluginViewModel(QObject):
    plugins_changed = QtSignal(object)

    def __init__(self, host: Any, parent: QObject | None = None):
        super().__init__(parent)
        self._host = host
        self._context = _PluginContext(host)
        self._manager = PluginManager(host.session_state.root / "plugins.json")
        self._chunk_connections: dict[str, list[tuple[Any, Any]]] = {}

    def refresh(self) -> tuple[PluginRecord, ...]:
        records = self._manager.discover()
        for record in records:
            if record.enabled and not record.loaded:
                self._manager.set_enabled(record.id, True, self._context)
        self._connect_live_listeners()
        records = self._manager.records()
        self._sync_analysis_actions()
        self.plugins_changed.emit(records)
        return records

    def set_enabled(self, plugin_id: str, enabled: bool) -> tuple[PluginRecord, ...]:
        if not enabled:
            self._disconnect_plugin(plugin_id)
            self._context.unsubscribe_owner(plugin_id)
        self._manager.set_enabled(plugin_id, enabled, self._context if enabled else None)
        if enabled:
            self._connect_live_listeners(plugin_id)
        records = self._manager.records()
        self._sync_analysis_actions()
        self.plugins_changed.emit(records)
        return records

    def import_plugin(self, source: str | Path) -> PluginRecord:
        source_path = Path(source).expanduser()
        record = (
            self._manager.import_archive(source_path)
            if source_path.suffix.lower() == ".zip"
            else self._manager.import_folder(source_path)
        )
        self.refresh()
        return record

    def plugin_directories(self) -> tuple[Path, ...]:
        return self._manager.plugin_dirs

    def ui_extensions(self, kind: str) -> dict[str, tuple[str, Any]]:
        return self._manager.ui_extensions(kind)

    @property
    def context(self) -> _PluginContext:
        return self._context

    def context_for_plugin(self, plugin_id: str) -> _PluginContextScope:
        return self._context.scoped(plugin_id)

    def _sync_analysis_actions(self) -> None:
        self._host.analysis_context_vm.set_marker_provider(self._context.list_session_markers)
        send_to = {
            f"{self._display_extension_name(name)} [{owner}]": self._guarded(callback, owner, name)
            for name, (owner, callback) in self._manager.ui_extensions("send_to_actions").items()
        }
        contextual = {
            f"{self._display_extension_name(name)} [{owner}]": self._guarded(callback, owner, name)
            for name, (owner, callback) in self._manager.ui_extensions("context_actions").items()
        }
        self._host.analysis_context_vm.set_plugin_actions(send_to, contextual)

    @staticmethod
    def _display_extension_name(name: str) -> str:
        return name.split(":", 1)[1].replace("_", " ").strip().title()

    @staticmethod
    def _guarded(
        callback: Callable[[AnalysisContext], None], owner: str, name: str
    ) -> Callable[[AnalysisContext], None]:
        def invoke(context: AnalysisContext) -> None:
            try:
                callback(context)
            except Exception:
                logger.exception("Plugin %s action %s failed", owner, name)
        return invoke

    def _connect_live_listeners(self, plugin_id: str | None = None) -> None:
        connected = {id(callback) for slots in self._chunk_connections.values() for callback, _ in slots}
        for owner, callback in self._manager.live_chunk_listeners():
            if (plugin_id is not None and owner != plugin_id) or id(callback) in connected:
                continue

            def deliver(chunk, *, listener=callback, owner_id=owner):
                try:
                    listener(chunk.clone())
                except Exception:
                    logger.exception("Plugin %s live chunk listener failed", owner_id)

            bridge = _PluginChunkBridge(callback, owner, self)
            self._host.connection_vm.chunk_ready.connect(bridge.receive)
            self._chunk_connections.setdefault(owner, []).append((callback, bridge))
            connected.add(id(callback))

    def _disconnect_plugin(self, plugin_id: str) -> None:
        for _callback, bridge in self._chunk_connections.pop(plugin_id, []):
            try:
                self._host.connection_vm.chunk_ready.disconnect(bridge.receive)
            except (RuntimeError, TypeError):
                pass
            bridge.deleteLater()

    def shutdown(self) -> None:
        for plugin_id in tuple(self._chunk_connections):
            self._disconnect_plugin(plugin_id)
        for plugin_id in tuple(self._context._subscriptions):
            self._context.unsubscribe_owner(plugin_id)
        self._manager.shutdown()
        self._host.analysis_context_vm.set_plugin_actions({}, {})
        self._host.analysis_context_vm.set_marker_provider(None)
