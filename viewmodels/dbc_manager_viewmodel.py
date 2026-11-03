from __future__ import annotations

from PySide6.QtCore import QObject, Signal as QtSignal

from services.dbc_manager import DbcManager


class DbcManagerViewModel(QObject, DbcManager):
    """Qt adapter for DBC catalog changes consumed by the desktop UI."""

    entries_changed = QtSignal()

    def __init__(self, parent: QObject | None = None):
        QObject.__init__(self, parent)
        DbcManager.__init__(self)

    def _emit_entries_changed(self) -> None:
        self.entries_changed.emit()
