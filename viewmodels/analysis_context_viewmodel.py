from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal as QtSignal

from models.analysis_context import AnalysisContext, AnalysisMarker


class AnalysisContextViewModel(QObject):
    """Stores and publishes the current analysis handoff context."""

    context_changed = QtSignal(object)
    send_requested = QtSignal(str, object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._context: AnalysisContext | None = None
        self._plugin_send_actions: dict[str, Callable[[AnalysisContext], None]] = {}
        self._plugin_context_actions: dict[str, Callable[[AnalysisContext], None]] = {}
        self._marker_provider: Callable[[], tuple[dict[str, Any], ...]] | None = None
        self._event_marker_provider: Callable[[], tuple[dict[str, Any], ...]] | None = None

    @property
    def context(self) -> AnalysisContext | None:
        return self._context

    def set_context(self, context: AnalysisContext) -> None:
        if not isinstance(context, AnalysisContext):
            raise TypeError("context must be an AnalysisContext")
        self._context = context
        self.context_changed.emit(context)

    def send_to(self, destination: str, context: AnalysisContext | None = None) -> None:
        selected = context or self._context
        if not destination.strip() or selected is None:
            return
        self._context = selected
        self.context_changed.emit(selected)
        self.send_requested.emit(destination, selected)

    def set_plugin_actions(
        self,
        send_to: dict[str, Callable[[AnalysisContext], None]],
        contextual: dict[str, Callable[[AnalysisContext], None]],
    ) -> None:
        self._plugin_send_actions = dict(send_to)
        self._plugin_context_actions = dict(contextual)

    def set_marker_provider(
        self, provider: Callable[[], tuple[dict[str, Any], ...]] | None
    ) -> None:
        self._marker_provider = provider

    def set_event_marker_provider(
        self, provider: Callable[[], tuple[dict[str, Any], ...]] | None
    ) -> None:
        self._event_marker_provider = provider

    def _context_with_markers(self, context: AnalysisContext) -> AnalysisContext:
        markers = list(context.markers)
        known = {(marker.name, marker.timestamp, marker.state) for marker in markers}
        added = False
        for provider in (self._event_marker_provider, self._marker_provider):
            if provider is None:
                continue
            for value in provider():
                marker = value if isinstance(value, AnalysisMarker) else AnalysisMarker(
                    sequence=int(value["sequence"]),
                    name=str(value["name"]),
                    timestamp=float(value["timestamp"]),
                    state=str(value["state"]) if value.get("state") is not None else None,
                )
                key = (
                    marker.name,
                    marker.timestamp,
                    marker.state,
                )
                if key in known:
                    continue
                markers.append(marker)
                known.add(key)
                added = True
        if not added:
            return context
        markers.sort(key=lambda marker: (marker.timestamp, marker.sequence))
        normalized = tuple(
            replace(marker, sequence=index)
            for index, marker in enumerate(markers, start=1)
        )
        return replace(context, markers=normalized) if normalized != context.markers else context

    def plugin_send_actions(self, context: AnalysisContext) -> dict[str, Callable[[], None]]:
        selected = self._context_with_markers(context)
        return {
            name: lambda callback=callback: callback(selected)
            for name, callback in self._plugin_send_actions.items()
        }

    def plugin_context_actions(self, context: AnalysisContext) -> dict[str, Callable[[], None]]:
        selected = self._context_with_markers(context)
        return {
            name: lambda callback=callback: callback(selected)
            for name, callback in self._plugin_context_actions.items()
        }
