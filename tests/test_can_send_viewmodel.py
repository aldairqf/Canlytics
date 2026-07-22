"""Characterization tests for CanSendViewModel's thin Qt-adapter behavior:
entry CRUD, periodic-send QTimer lifecycle, tx log bookkeeping, persistence
via SessionStateStore, and reacting to the connection's running/send signals.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QObject, Signal as QtSignal
from PySide6.QtWidgets import QApplication

from models.can_send import DbcFrameSource, TransmitEntry
from services.session_state import SessionStateStore
from viewmodels.can_send_viewmodel import CanSendViewModel

_app: QApplication | None = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


class _FakeConnectionViewModel(QObject):
    running_changed = QtSignal(bool)
    send_succeeded = QtSignal(str)
    send_failed = QtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.requested: list = []
        self.fail_message: str | None = None

    def request_send(self, frame) -> None:
        self.requested.append(frame)
        if self.fail_message is not None:
            self.send_failed.emit(frame.entry_id, self.fail_message)
        else:
            self.send_succeeded.emit(frame.entry_id)

    def set_running(self, running: bool) -> None:
        self.running = running
        self.running_changed.emit(running)


class CanSendViewModelTests(unittest.TestCase):
    def setUp(self):
        self.connection_vm = _FakeConnectionViewModel()
        self.vm = CanSendViewModel(dbc_manager=None, connection_vm=self.connection_vm, session_state=None)

    def tearDown(self):
        self.vm.shutdown()

    def _entry(self, **overrides) -> TransmitEntry:
        defaults = dict(entry_id=self.vm.new_entry_id(), can_id="100", dlc=2, data_hex="0102")
        defaults.update(overrides)
        return TransmitEntry(**defaults)

    def test_add_entry_emits_entries_changed(self):
        seen = []
        self.vm.entries_changed.connect(lambda: seen.append(True))
        entry = self._entry()
        self.vm.add_entry(entry)
        self.assertEqual(self.vm.entries(), [entry])
        self.assertEqual(seen, [True])

    def test_remove_entry_drops_it_and_stops_its_periodic_timer(self):
        entry = self._entry(mode="periodic", interval_ms=1000)
        self.vm.add_entry(entry)
        self.vm.set_periodic_active(entry.entry_id, True)
        self.assertTrue(self.vm.is_periodic_active(entry.entry_id))

        self.vm.remove_entry(entry.entry_id)

        self.assertEqual(self.vm.entries(), [])
        self.assertFalse(self.vm.is_periodic_active(entry.entry_id))

    def test_update_entry_replaces_it_and_retunes_active_timer_interval(self):
        entry = self._entry(mode="periodic", interval_ms=1000)
        self.vm.add_entry(entry)
        self.vm.set_periodic_active(entry.entry_id, True)

        updated = self._entry(entry_id=entry.entry_id, mode="periodic", interval_ms=50, label="renamed")
        self.vm.update_entry(updated)

        self.assertEqual(self.vm.entries()[0].label, "renamed")
        self.assertEqual(self.vm._periodic_timers[entry.entry_id].interval(), 50)

    def test_set_enabled_false_also_stops_periodic(self):
        entry = self._entry(mode="periodic", interval_ms=1000)
        self.vm.add_entry(entry)
        self.vm.set_periodic_active(entry.entry_id, True)

        self.vm.set_enabled(entry.entry_id, False)

        self.assertFalse(self.vm.is_periodic_active(entry.entry_id))
        self.assertFalse(self.vm.entries()[0].enabled)

    def test_send_now_success_appends_ok_log_record(self):
        entry = self._entry(label="Beacon")
        self.vm.add_entry(entry)
        logs = []
        self.vm.tx_log_appended.connect(lambda rec: logs.append(rec))

        self.vm.send_now(entry.entry_id)

        self.assertEqual(len(self.connection_vm.requested), 1)
        self.assertEqual(self.connection_vm.requested[0].can_id, 0x100)
        self.assertEqual(len(logs), 1)
        self.assertTrue(logs[0].success)
        self.assertEqual(logs[0].label, "Beacon")

    def test_send_now_failure_from_connection_appends_failed_log_record(self):
        entry = self._entry()
        self.vm.add_entry(entry)
        self.connection_vm.fail_message = "Not connected."
        logs = []
        self.vm.tx_log_appended.connect(lambda rec: logs.append(rec))

        self.vm.send_now(entry.entry_id)

        self.assertEqual(len(logs), 1)
        self.assertFalse(logs[0].success)
        self.assertEqual(logs[0].message, "Not connected.")

    def test_send_now_invalid_entry_never_reaches_connection(self):
        entry = self._entry(dlc=4, data_hex="0102")  # DLC/byte-count mismatch
        self.vm.add_entry(entry)
        logs = []
        self.vm.tx_log_appended.connect(lambda rec: logs.append(rec))

        self.vm.send_now(entry.entry_id)

        self.assertEqual(self.connection_vm.requested, [])
        self.assertEqual(len(logs), 1)
        self.assertFalse(logs[0].success)

    def test_set_periodic_active_starts_and_stops_a_timer(self):
        entry = self._entry(mode="periodic", interval_ms=25)
        self.vm.add_entry(entry)
        states = []
        self.vm.periodic_state_changed.connect(lambda eid, active: states.append((eid, active)))

        self.vm.set_periodic_active(entry.entry_id, True)
        self.assertTrue(self.vm.is_periodic_active(entry.entry_id))
        self.assertTrue(self.vm._periodic_timers[entry.entry_id].isActive())

        self.vm.set_periodic_active(entry.entry_id, False)
        self.assertFalse(self.vm.is_periodic_active(entry.entry_id))
        self.assertEqual(states, [(entry.entry_id, True), (entry.entry_id, False)])

    def test_set_periodic_active_twice_does_not_create_a_second_timer(self):
        entry = self._entry(mode="periodic", interval_ms=25)
        self.vm.add_entry(entry)
        self.vm.set_periodic_active(entry.entry_id, True)
        first_timer = self.vm._periodic_timers[entry.entry_id]
        self.vm.set_periodic_active(entry.entry_id, True)
        self.assertIs(self.vm._periodic_timers[entry.entry_id], first_timer)

    def test_tick_periodic_invokes_request_send(self):
        entry = self._entry(mode="periodic", interval_ms=25)
        self.vm.add_entry(entry)
        self.vm._tick_periodic(entry.entry_id)
        self.assertEqual(len(self.connection_vm.requested), 1)

    def test_tick_periodic_on_disabled_entry_stops_its_own_timer(self):
        entry = self._entry(mode="periodic", interval_ms=25)
        self.vm.add_entry(entry)
        self.vm.set_periodic_active(entry.entry_id, True)
        entry.enabled = False  # simulate disable without going through set_enabled

        self.vm._tick_periodic(entry.entry_id)

        self.assertFalse(self.vm.is_periodic_active(entry.entry_id))
        self.assertEqual(self.connection_vm.requested, [])

    def test_running_changed_false_stops_all_active_periodic_timers(self):
        a = self._entry(mode="periodic", interval_ms=1000)
        b = self._entry(mode="periodic", interval_ms=1000)
        self.vm.add_entry(a)
        self.vm.add_entry(b)
        self.vm.set_periodic_active(a.entry_id, True)
        self.vm.set_periodic_active(b.entry_id, True)

        self.connection_vm.set_running(False)

        self.assertFalse(self.vm.is_periodic_active(a.entry_id))
        self.assertFalse(self.vm.is_periodic_active(b.entry_id))

    def test_send_enabled_changed_mirrors_connection_running(self):
        seen = []
        self.vm.send_enabled_changed.connect(lambda running: seen.append(running))
        self.connection_vm.set_running(False)
        self.assertEqual(seen, [False])

    def test_shutdown_stops_every_periodic_timer(self):
        entry = self._entry(mode="periodic", interval_ms=1000)
        self.vm.add_entry(entry)
        self.vm.set_periodic_active(entry.entry_id, True)

        self.vm.shutdown()

        self.assertEqual(self.vm._periodic_timers, {})

    def test_tx_log_trims_to_max_length(self):
        entry = self._entry()
        self.vm.add_entry(entry)
        for _ in range(510):
            self.vm.send_now(entry.entry_id)
        self.assertEqual(len(self.vm.tx_log()), 500)


class CanSendViewModelPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.session_state = SessionStateStore(root=Path(self.tmpdir.name))
        self.connection_vm = _FakeConnectionViewModel()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_added_entry_survives_a_new_viewmodel_instance(self):
        vm1 = CanSendViewModel(dbc_manager=None, connection_vm=self.connection_vm, session_state=self.session_state)
        entry = TransmitEntry(
            entry_id=vm1.new_entry_id(), label="Persisted", can_id="7FF", dlc=3, data_hex="AABBCC",
            mode="periodic", interval_ms=250,
        )
        vm1.add_entry(entry)
        vm1.shutdown()

        vm2 = CanSendViewModel(dbc_manager=None, connection_vm=self.connection_vm, session_state=self.session_state)
        restored = vm2.entries()
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0].label, "Persisted")
        self.assertEqual(restored[0].data_hex, "AABBCC")
        self.assertEqual(restored[0].interval_ms, 250)
        vm2.shutdown()

    def test_dbc_source_round_trips_through_persistence(self):
        vm1 = CanSendViewModel(dbc_manager=None, connection_vm=self.connection_vm, session_state=self.session_state)
        entry = TransmitEntry(
            entry_id=vm1.new_entry_id(), can_id="100", dlc=8, data_hex="0102030405060708",
            source="dbc", dbc_source=DbcFrameSource(dbc_name="my.dbc", message_name="Msg", signal_values={"S": 1.0}),
        )
        vm1.add_entry(entry)
        vm1.shutdown()

        vm2 = CanSendViewModel(dbc_manager=None, connection_vm=self.connection_vm, session_state=self.session_state)
        restored = vm2.entries()[0]
        self.assertEqual(restored.source, "dbc")
        self.assertEqual(restored.dbc_source, DbcFrameSource(dbc_name="my.dbc", message_name="Msg", signal_values={"S": 1.0}))
        vm2.shutdown()

    def test_removed_entry_does_not_reappear_after_restore(self):
        vm1 = CanSendViewModel(dbc_manager=None, connection_vm=self.connection_vm, session_state=self.session_state)
        entry = TransmitEntry(entry_id=vm1.new_entry_id(), can_id="100", dlc=1, data_hex="01")
        vm1.add_entry(entry)
        vm1.remove_entry(entry.entry_id)
        vm1.shutdown()

        vm2 = CanSendViewModel(dbc_manager=None, connection_vm=self.connection_vm, session_state=self.session_state)
        self.assertEqual(vm2.entries(), [])
        vm2.shutdown()


if __name__ == "__main__":
    unittest.main()
