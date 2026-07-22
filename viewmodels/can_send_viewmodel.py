from __future__ import annotations

import time
import uuid

from PySide6.QtCore import QObject, QTimer, Signal as QtSignal

from models.can_send import DbcFrameSource, TransmitEntry, TxLogRecord
from services.can_send import TransmitEntryError, resolve_transmit_entry

_PREFS_KEY = "can_send"
_MAX_LOG = 500


class CanSendViewModel(QObject):
    entries_changed = QtSignal()
    entry_updated = QtSignal(str)
    periodic_state_changed = QtSignal(str, bool)
    tx_log_appended = QtSignal(object)
    send_enabled_changed = QtSignal(bool)

    def __init__(self, dbc_manager, connection_vm, session_state, parent: QObject | None = None):
        super().__init__(parent)
        self._dbc_manager = dbc_manager
        self._connection_vm = connection_vm
        self._session_state = session_state
        self._entries: list[TransmitEntry] = []
        self._periodic_timers: dict[str, QTimer] = {}
        self._tx_log: list[TxLogRecord] = []

        self._restore_persisted_entries()

        connection_vm.running_changed.connect(self._on_running_changed)
        connection_vm.send_succeeded.connect(self._on_send_succeeded)
        connection_vm.send_failed.connect(self._on_send_failed)

    @property
    def send_enabled(self) -> bool:
        return self._connection_vm.running

    def entries(self) -> list[TransmitEntry]:
        return list(self._entries)

    def tx_log(self) -> list[TxLogRecord]:
        return list(self._tx_log)

    def is_periodic_active(self, entry_id: str) -> bool:
        return entry_id in self._periodic_timers

    def add_entry(self, entry: TransmitEntry) -> None:
        self._entries.append(entry)
        self._persist()
        self.entries_changed.emit()

    def remove_entry(self, entry_id: str) -> None:
        self.set_periodic_active(entry_id, False)
        self._entries = [e for e in self._entries if e.entry_id != entry_id]
        self._persist()
        self.entries_changed.emit()

    def update_entry(self, entry: TransmitEntry) -> None:
        for index, existing in enumerate(self._entries):
            if existing.entry_id == entry.entry_id:
                self._entries[index] = entry
                break
        if entry.entry_id in self._periodic_timers:
            self._periodic_timers[entry.entry_id].setInterval(max(1, int(entry.interval_ms)))
        self._persist()
        self.entry_updated.emit(entry.entry_id)

    def set_enabled(self, entry_id: str, enabled: bool) -> None:
        entry = self._entry_by_id(entry_id)
        if entry is None:
            return
        entry.enabled = enabled
        if not enabled:
            self.set_periodic_active(entry_id, False)
        self._persist()
        self.entry_updated.emit(entry_id)

    def send_now(self, entry_id: str) -> None:
        entry = self._entry_by_id(entry_id)
        if entry is None:
            return
        try:
            frame = resolve_transmit_entry(entry)
        except TransmitEntryError as exc:
            self._append_log(entry, mode="single", success=False, message=str(exc))
            return
        self._connection_vm.request_send(frame)

    def set_periodic_active(self, entry_id: str, active: bool) -> None:
        entry = self._entry_by_id(entry_id)
        if entry is None:
            return
        if active:
            if entry_id in self._periodic_timers:
                return
            timer = QTimer(self)
            timer.setInterval(max(1, int(entry.interval_ms)))
            timer.timeout.connect(lambda eid=entry_id: self._tick_periodic(eid))
            self._periodic_timers[entry_id] = timer
            timer.start()
        else:
            timer = self._periodic_timers.pop(entry_id, None)
            if timer is not None:
                timer.stop()
                timer.deleteLater()
        self.periodic_state_changed.emit(entry_id, active)

    def shutdown(self) -> None:
        for entry_id in list(self._periodic_timers.keys()):
            self.set_periodic_active(entry_id, False)

    def new_entry_id(self) -> str:
        return uuid.uuid4().hex

    def _entry_by_id(self, entry_id: str) -> TransmitEntry | None:
        for entry in self._entries:
            if entry.entry_id == entry_id:
                return entry
        return None

    def _tick_periodic(self, entry_id: str) -> None:
        entry = self._entry_by_id(entry_id)
        if entry is None or not entry.enabled:
            self.set_periodic_active(entry_id, False)
            return
        try:
            frame = resolve_transmit_entry(entry)
        except TransmitEntryError as exc:
            self.set_periodic_active(entry_id, False)
            self._append_log(entry, mode="periodic", success=False, message=str(exc))
            return
        self._connection_vm.request_send(frame)

    def _on_running_changed(self, running: bool) -> None:
        if not running:
            for entry_id in list(self._periodic_timers.keys()):
                self.set_periodic_active(entry_id, False)
        self.send_enabled_changed.emit(running)

    def _on_send_succeeded(self, entry_id: str) -> None:
        entry = self._entry_by_id(entry_id)
        if entry is None:
            return
        mode = "periodic" if entry_id in self._periodic_timers else "single"
        self._append_log(entry, mode=mode, success=True)

    def _on_send_failed(self, entry_id: str, message: str) -> None:
        entry = self._entry_by_id(entry_id)
        if entry is None:
            return
        mode = "periodic" if entry_id in self._periodic_timers else "single"
        self._append_log(entry, mode=mode, success=False, message=message)

    def _append_log(self, entry: TransmitEntry, *, mode: str, success: bool, message: str = "") -> None:
        record = TxLogRecord(
            ts=time.time(),
            entry_id=entry.entry_id,
            label=entry.label,
            can_id=entry.can_id,
            data_hex=entry.data_hex,
            mode=mode,
            success=success,
            message=message,
        )
        self._tx_log.append(record)
        if len(self._tx_log) > _MAX_LOG:
            self._tx_log = self._tx_log[-_MAX_LOG:]
        self.tx_log_appended.emit(record)

    def _persist(self) -> None:
        if self._session_state is None:
            return
        entries_data = []
        for entry in self._entries:
            data = {
                "entry_id": entry.entry_id,
                "label": entry.label,
                "can_id": entry.can_id,
                "extended": entry.extended,
                "dlc": entry.dlc,
                "data_hex": entry.data_hex,
                "source": entry.source,
                "mode": entry.mode,
                "interval_ms": entry.interval_ms,
                "enabled": entry.enabled,
            }
            if entry.dbc_source is not None:
                data["dbc_name"] = entry.dbc_source.dbc_name
                data["message_name"] = entry.dbc_source.message_name
                data["signal_values"] = entry.dbc_source.signal_values
            entries_data.append(data)
        self._session_state.set_window_prefs(_PREFS_KEY, {"entries": entries_data})

    def _restore_persisted_entries(self) -> None:
        if self._session_state is None:
            return
        prefs = self._session_state.get_window_prefs(_PREFS_KEY)
        for data in prefs.get("entries", []):
            dbc_source = None
            if data.get("source") == "dbc" and data.get("dbc_name") and data.get("message_name"):
                dbc_source = DbcFrameSource(
                    dbc_name=data["dbc_name"],
                    message_name=data["message_name"],
                    signal_values=dict(data.get("signal_values") or {}),
                )
            try:
                entry = TransmitEntry(
                    entry_id=data.get("entry_id") or self.new_entry_id(),
                    label=data.get("label", ""),
                    can_id=data.get("can_id", "000"),
                    extended=bool(data.get("extended", False)),
                    dlc=int(data.get("dlc", 8)),
                    data_hex=data.get("data_hex", "0000000000000000"),
                    source=data.get("source", "raw"),
                    dbc_source=dbc_source,
                    mode=data.get("mode", "single"),
                    interval_ms=int(data.get("interval_ms", 100)),
                    enabled=bool(data.get("enabled", True)),
                )
            except (TypeError, ValueError):
                continue
            self._entries.append(entry)
