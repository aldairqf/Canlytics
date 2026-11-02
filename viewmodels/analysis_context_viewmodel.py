from __future__ import annotations

from PySide6.QtCore import QObject, Signal as QtSignal

from models.analysis_context import AnalysisContext


class AnalysisContextViewModel(QObject):
    """Stores and publishes the current analysis handoff context."""

    context_changed = QtSignal(object)
    send_requested = QtSignal(str, object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._context: AnalysisContext | None = None

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
