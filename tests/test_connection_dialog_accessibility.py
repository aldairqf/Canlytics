from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from config.app_config import get_text
from views.settings.connection_dialog import ConnectionDialog


class _ConnectionVm(QObject):
    running_changed = Signal(bool)
    status_changed = Signal(str)
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.running = False

    @staticmethod
    def bitrate_probe_order(values: list[int]) -> list[int]:
        return values


class ConnectionDialogAccessibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def setUp(self) -> None:
        self.dialog = ConnectionDialog(
            _ConnectionVm(),
            replay_offset_getter=lambda: 0.0,
            normalize_getter=lambda: False,
        )
        self.dialog.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.dialog.reject()
        self.app.processEvents()

    def test_ssh_label_has_mnemonic_and_focus_buddy(self) -> None:
        label = self.dialog._ssh_form.labelForField(self.dialog.host)
        self.assertIsNotNone(label)
        self.assertIn("&", label.text())
        self.assertIs(label.buddy(), self.dialog.host)

    def test_missing_ssh_host_shows_inline_accessible_error_and_clears_on_edit(self) -> None:
        self.dialog._start_ssh(False)
        error = get_text("ssh_host_required")
        self.assertEqual(self.dialog._ssh_host_error.text(), error)
        self.assertFalse(self.dialog._ssh_host_error.isHidden())
        self.assertEqual(self.dialog.host.accessibleDescription(), error)
        self.assertTrue(self.dialog.host.property("invalid"))
        self.assertEqual(self.dialog.status.text(), error)

        self.dialog.host.setText("can-gateway")
        self.assertTrue(self.dialog._ssh_host_error.isHidden())
        self.assertFalse(self.dialog.host.property("invalid"))
        self.assertEqual(self.dialog.status.text(), get_text("connection_status_idle"))


    def test_replay_file_and_speed_errors_are_inline_and_clear_after_edit(self) -> None:
        self.dialog.connection_type.setCurrentIndex(2)
        self.dialog._start_replay()
        self.assertEqual(self.dialog._replay_file_error.text(), get_text("replay_file_required"))
        self.assertEqual(self.dialog.replay_file.accessibleDescription(), get_text("replay_file_required"))

        self.dialog.replay_file.setText("capture.log")
        self.dialog.replay_speed.setCurrentText("fast")
        self.dialog._start_replay()
        self.assertEqual(self.dialog._replay_speed_error.text(), get_text("replay_speed_invalid"))
        self.assertTrue(self.dialog.replay_speed.property("invalid"))
        self.assertTrue(self.dialog.replay_speed.hasFocus())

    def test_technical_choices_have_explanatory_tooltips(self) -> None:
        self.assertIn("adapter timestamps", self.dialog._ssh_ts_device.toolTip())
        self.assertIn("backend", self.dialog._kvaser_form.labelForField(self.dialog.kvaser_interface).toolTip())
        self.dialog.connection_type.setCurrentIndex(2)
        self.assertIn("multiplier", self.dialog._replay_form.labelForField(self.dialog.replay_speed).toolTip())

    def test_invalid_kvaser_bitrate_is_attached_to_its_input(self) -> None:
        self.dialog.connection_type.setCurrentIndex(1)
        self.dialog.kvaser_bitrate.setCurrentText("fast")
        self.dialog._start_kvaser(False)
        error = get_text("kvaser_bitrate_invalid")
        self.assertEqual(self.dialog._kvaser_bitrate_error.text(), error)
        self.assertEqual(self.dialog.kvaser_bitrate.accessibleDescription(), error)
        self.assertTrue(self.dialog.kvaser_bitrate.property("invalid"))


if __name__ == "__main__":
    unittest.main()
