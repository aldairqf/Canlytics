from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from models.analysis_context import AnalysisMarker

SDK_API_VERSION = 1


@dataclass(frozen=True)
class DbcSignalInfo:
    name: str
    start: int
    length: int
    scale: float
    offset: float
    unit: str


@dataclass(frozen=True)
class DbcMessageInfo:
    frame_id: int
    name: str
    length: int
    signals: tuple[DbcSignalInfo, ...]


class AnalysisServices(Protocol):
    def summarize(self, dataframe: Any, can_id: str | None = None) -> dict[str, Any]: ...

    def candidates(self, dataframe: Any, can_ids: set[str], **options: Any) -> list[Any]: ...

    def compare_ranges(self, dataframe: Any, start_a: float, end_a: float, start_b: float, end_b: float) -> Any: ...


class PluginContext(Protocol):
    @property
    def frame_schema(self) -> dict[str, str]: ...

    def get_frames(self) -> Any: ...

    def list_dbc_names(self) -> tuple[str, ...]: ...

    def decode_frame(self, can_id: str, data_hex: str) -> tuple[dict[str, Any], ...]: ...

    def get_working_dbc_messages(self) -> tuple[DbcMessageInfo, ...]: ...

    @property
    def analysis(self) -> AnalysisServices: ...

    def export_log(self, dataframe: Any, path: str) -> str: ...

    def list_session_markers(self) -> tuple[dict[str, Any], ...]: ...

    def send_frame(self, can_id: int | str, data: bytes | str, *, extended: bool = False) -> str: ...

    def subscribe_live_chunks(
        self, callback: Callable[[Any], None], *, lifetime: Any
    ) -> Callable[[], None]: ...


@dataclass(frozen=True)
class PluginDescriptor:
    id: str
    name: str
    version: str
    api_version: int
    register: Callable[["PluginAPI", PluginContext], None]


class PluginAPI:
    """Registration surface provided to trusted third-party plugins."""

    def __init__(self, plugin_id: str):
        self.plugin_id = plugin_id
        self.dbc_sources: dict[str, Callable[..., Any]] = {}
        self.log_importers: dict[str, Callable[..., Any]] = {}
        self.log_exporters: dict[str, Callable[..., Any]] = {}
        self.windows: dict[str, Callable[[PluginContext], Any]] = {}
        self.live_chunk_listeners: list[Callable[[Any], None]] = []
        self.send_to_actions: dict[str, Callable[[Any], None]] = {}
        self.context_actions: dict[str, Callable[[Any], None]] = {}

    def register_dbc_source(self, name: str, loader: Callable[..., Any]) -> None:
        self._register(self.dbc_sources, name, loader)

    def register_log_importer(self, name: str, importer: Callable[..., Any]) -> None:
        self._register(self.log_importers, name, importer)

    def register_log_exporter(self, name: str, exporter: Callable[..., Any]) -> None:
        self._register(self.log_exporters, name, exporter)

    def register_window(self, name: str, factory: Callable[[PluginContext], Any]) -> None:
        self._register(self.windows, name, factory)

    def register_live_chunk_listener(self, listener: Callable[[Any], None]) -> None:
        if not callable(listener):
            raise ValueError("A live chunk listener must be callable")
        self.live_chunk_listeners.append(listener)

    def register_send_to_action(self, name: str, callback: Callable[[Any], None]) -> None:
        self._register(self.send_to_actions, name, callback)

    def register_context_action(self, name: str, callback: Callable[[Any], None]) -> None:
        self._register(self.context_actions, name, callback)

    @staticmethod
    def _register(target: dict[str, Callable[..., Any]], name: str, callback: Callable[..., Any]) -> None:
        key = str(name).strip()
        if not key or not callable(callback):
            raise ValueError("An extension needs a name and a callable")
        if key in target:
            raise ValueError(f"Extension already registered: {key}")
        target[key] = callback

    def clear(self) -> None:
        self.dbc_sources.clear()
        self.log_importers.clear()
        self.log_exporters.clear()
        self.windows.clear()
        self.live_chunk_listeners.clear()
        self.send_to_actions.clear()
        self.context_actions.clear()


__all__ = [
    "AnalysisServices",
    "AnalysisMarker",
    "DbcMessageInfo",
    "DbcSignalInfo",
    "PluginAPI",
    "PluginContext",
    "PluginDescriptor",
    "SDK_API_VERSION",
]
