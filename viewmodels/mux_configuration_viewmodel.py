from __future__ import annotations

from PySide6.QtCore import QObject, Signal as QtSignal

from models.mux_config import MuxConfigEntry, normalize_mux_config_entries
from services.session_state import SessionStateStore


class MuxConfigurationViewModel(QObject):
    configuration_changed = QtSignal(object)

    def __init__(self, session_state: SessionStateStore, parent: QObject | None = None):
        super().__init__(parent)
        self._session_state = session_state
        self._configs = session_state.get_mux_configuration()

    @property
    def configs(self) -> list[MuxConfigEntry]:
        return list(self._configs)

    def set_configuration(self, configs: list[MuxConfigEntry]) -> None:
        normalized = normalize_mux_config_entries(configs)
        if normalized == self._configs:
            return
        self._session_state.set_mux_configuration(normalized)
        self._configs = normalized
        self.configuration_changed.emit(self.configs)
