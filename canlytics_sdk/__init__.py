from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

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

    def register_dbc_source(self, name: str, loader: Callable[..., Any]) -> None:
        self._register(self.dbc_sources, name, loader)

    def register_log_importer(self, name: str, importer: Callable[..., Any]) -> None:
        self._register(self.log_importers, name, importer)

    def register_log_exporter(self, name: str, exporter: Callable[..., Any]) -> None:
        self._register(self.log_exporters, name, exporter)

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


__all__ = [
    "AnalysisServices",
    "DbcMessageInfo",
    "DbcSignalInfo",
    "PluginAPI",
    "PluginContext",
    "PluginDescriptor",
    "SDK_API_VERSION",
]
