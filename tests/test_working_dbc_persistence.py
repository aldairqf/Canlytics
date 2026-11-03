from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication

from services.session_state import SessionStateStore
from services.working_dbc import WorkingDbc
from viewmodels.main_window_viewmodel import MainWindowViewModel


class WorkingDbcPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="canlytics-working-dbc-")
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _new_viewmodel(self) -> MainWindowViewModel:
        store = SessionStateStore(root=self.root)
        with patch("viewmodels.main_window_viewmodel.SessionStateStore", return_value=store):
            return MainWindowViewModel()

    def _wait_for_restore(self, view_model: MainWindowViewModel) -> bool:
        restored: list[bool] = []
        view_model.dbc_restore_finished.connect(restored.append)
        view_model.start_restore_dbcs()
        deadline = time.monotonic() + 5.0
        while not restored and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertTrue(restored, "DBC restore did not finish")
        return restored[0]

    def test_working_dbc_is_saved_registered_and_restored(self) -> None:
        first = self._new_viewmodel()
        try:
            external_dbc = Path(__file__).resolve().parent / "fixtures" / "dbc" / "j1939_test.dbc"
            if external_dbc.exists():
                first.dbc_manager.load_dbc(str(external_dbc))
            self.assertIsNone(first.dbc_manager.resolve_message_name("321"))
            message = first.working_dbc.create_message("Powertrain", 0x321, length=8)
            first.working_dbc.create_signal(message.frame_id, "Speed", start=0, length=16, scale=0.5)
            self.assertIsNone(first.dbc_manager.resolve_message_name("321"))
            output = first.save_working_dbc()
            self.assertEqual(output, self.root / "working.dbc")
            self.assertTrue(output.exists())
            self.assertEqual(first.dbc_manager.resolve_message_name("321"), "Powertrain")
            self.assertTrue(first.dbc_manager.get_entry(first._working_dbc_entry_name).active)
            self.assertTrue(all(
                Path(item["path"]).resolve() != output.resolve()
                for item in first.session_state.get_saved_dbcs()
            ))
        finally:
            first.shutdown()

        second = self._new_viewmodel()
        try:
            self.assertTrue(self._wait_for_restore(second))
            entry = second.dbc_manager.get_entry(second._working_dbc_entry_name)
            self.assertIsNotNone(entry)
            self.assertTrue(entry.active)
            self.assertEqual(second.dbc_manager.list_entries()[0].name, second._working_dbc_entry_name)
            self.assertEqual(second.dbc_manager.resolve_message_name("321"), "Powertrain")
            encoded = entry.db.encode_message("Powertrain", {"Speed": 12.0})
            self.assertEqual(entry.db.decode_message(0x321, encoded)["Speed"], 12.0)
        finally:
            second.shutdown()

    def test_loaded_working_dbc_does_not_change_external_source(self) -> None:
        source = self.root / "external.dbc"
        source.write_text(
            'VERSION ""\n\nNS_ :\n\nBS_:\n\nBU_: ECU\n\nBO_ 256 External: 8 ECU\n '
            'SG_ Value : 0|8@1+ (1,0) [0|255] "" ECU\n',
            encoding="utf-8",
        )
        original = source.read_bytes()
        view_model = self._new_viewmodel()
        try:
            view_model.dbc_manager.load_dbc(str(source))
            view_model.working_dbc.create_message("Local", 0x400)
            view_model.save_working_dbc()
            with self.assertRaisesRegex(ValueError, "Cannot overwrite"):
                view_model.export_working_dbc(source)
            self.assertEqual(source.read_bytes(), original)
        finally:
            view_model.shutdown()

    def test_restoring_only_working_dbc_reports_success(self) -> None:
        first = self._new_viewmodel()
        try:
            message = first.working_dbc.create_message("OnlyWorking", 0x456)
            first.working_dbc.create_signal(message.frame_id, "Value", start=0, length=8)
            first.save_working_dbc()
        finally:
            first.shutdown()

        second = self._new_viewmodel()
        try:
            self.assertTrue(self._wait_for_restore(second))
            self.assertEqual(second.dbc_manager.resolve_message_name("456"), "OnlyWorking")
        finally:
            second.shutdown()

    def test_signal_dialog_defaults_reuse_working_message_and_mux_selector(self) -> None:
        view_model = self._new_viewmodel()
        try:
            view_model.working_dbc.create_message("Status", 0x567, length=8)
            view_model.working_dbc.create_signal(
                0x567, "Mode", start=0, length=2, is_multiplexer=True,
            )

            defaults = view_model.working_signal_dialog_defaults("567")

            self.assertEqual(defaults["message_name"], "Status")
            self.assertEqual(defaults["message_length"], 8)
            self.assertEqual(defaults["multiplexer_signals"], ["Mode"])
            self.assertTrue(defaults["working_message"])
        finally:
            view_model.shutdown()

    def test_working_dbc_management_viewmodel_persists_each_edit_and_exports_copy(self) -> None:
        view_model = self._new_viewmodel()
        try:
            output = view_model.add_working_message("Engine", 0x321, 8)
            self.assertTrue(output.exists())
            output = view_model.add_working_signal(
                0x321, "Speed", start=0, length=16, scale=0.5, unit="kmh",
            )
            self.assertTrue(output.exists())
            self.assertEqual(len(view_model.list_working_messages()[0].signals), 1)
            view_model.edit_working_signal(0x321, "Speed", new_name="VehicleSpeed", offset=1.0)
            self.assertEqual(view_model.list_working_messages()[0].signals[0].name, "VehicleSpeed")
            view_model.edit_working_message(0x321, name="Powertrain", new_frame_id=0x322)
            self.assertEqual(view_model.list_working_messages()[0].name, "Powertrain")
            exported = view_model.export_working_dbc(self.root / "exported.dbc")
            self.assertEqual(exported.name, "exported.dbc")
            view_model.delete_working_signal(0x322, "VehicleSpeed")
            self.assertEqual(view_model.list_working_messages()[0].signals, [])
            view_model.delete_working_message(0x322)
            self.assertEqual(view_model.list_working_messages(), [])
            view_model.add_working_message("Extended", 0x1800, 8, True)
            view_model.edit_working_message(0x1800, new_frame_id=0x400, is_extended_frame=False)
            self.assertFalse(view_model.list_working_messages()[0].is_extended_frame)
            view_model.delete_working_message(0x400)
        finally:
            view_model.shutdown()

    def test_failed_working_dbc_save_rolls_back_memory_and_decode_cache(self) -> None:
        view_model = self._new_viewmodel()
        try:
            view_model.add_working_message("Engine", 0x321)
            canonical_bytes = view_model.session_state.working_dbc_path.read_bytes()
            with patch.object(WorkingDbc, "export", side_effect=OSError("disk unavailable")):
                with self.assertRaisesRegex(OSError, "disk unavailable"):
                    view_model.edit_working_message(0x321, name="Changed")
            self.assertEqual(view_model.list_working_messages()[0].name, "Engine")
            self.assertEqual(view_model.dbc_manager.resolve_message_name("321"), "Engine")
            self.assertEqual(view_model.session_state.working_dbc_path.read_bytes(), canonical_bytes)
            view_model.dbc_manager.remove_entry(view_model._working_dbc_entry_name)
            duplicate = view_model.dbc_manager.load_dbc(str(view_model.session_state.working_dbc_path))
            self.assertNotEqual(duplicate.name, view_model._working_dbc_entry_name)
            view_model.edit_working_message(0x321, name="Recovered")
            self.assertEqual(view_model.dbc_manager.resolve_message_name("321"), "Recovered")
            self.assertEqual(
                sum(entry.name == view_model._working_dbc_entry_name for entry in view_model.dbc_manager.list_entries()),
                1,
            )
        finally:
            view_model.shutdown()


if __name__ == "__main__":
    unittest.main()
