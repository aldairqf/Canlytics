from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from views.widgets.can_id_jump_dialog import CanIdJumpDialog
from views.widgets.can_id_panel import CanIdPanelWidget


class CanIdJumpDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def test_search_accepts_hex_prefix_case_insensitively(self):
        dialog = CanIdJumpDialog(["0x18FF50E5", "123"])
        dialog.search.setText("0X18ff")
        self.assertEqual(dialog.results.count(), 1)
        self.assertEqual(dialog.selected_can_id, "0x18FF50E5")
        self.assertTrue(dialog.buttons.button(QDialogButtonBox.Ok).isEnabled())

    def test_empty_and_unknown_search_have_no_selectable_result(self):
        empty_dialog = CanIdJumpDialog([])
        self.assertEqual(empty_dialog.results.count(), 0)
        self.assertFalse(empty_dialog.buttons.button(QDialogButtonBox.Ok).isEnabled())

        dialog = CanIdJumpDialog(["123"])
        dialog.search.setText("0x999")
        self.assertEqual(dialog.results.count(), 0)
        self.assertIsNone(dialog.selected_can_id)
        self.assertFalse(dialog.buttons.button(QDialogButtonBox.Ok).isEnabled())
        dialog.search.clear()
        self.assertEqual(dialog.results.count(), 1)

    def test_shared_panel_preserves_checks_and_uses_id_as_item_data(self):
        panel = CanIdPanelWidget(show_interpret_controls=False)
        panel.set_can_ids(["200", "100"])
        self.assertEqual([panel.can_list.item(i).data(Qt.UserRole) for i in range(2)], ["100", "200"])
        self.assertEqual(panel.selected_ids(), {"100", "200"})
        panel.can_list.item(0).setCheckState(Qt.Unchecked)
        panel.set_can_ids(["100", "200", "300"])
        self.assertEqual(panel.selected_ids(), {"200"})

    def test_selector_only_panel_does_not_show_checkboxes(self):
        panel = CanIdPanelWidget(show_interpret_controls=False, checkable=False)
        panel.set_can_ids(["100"])
        item = panel.can_list.item(0)
        self.assertFalse(item.flags() & Qt.ItemIsUserCheckable)
        self.assertFalse(panel.btn_all.isVisible())


if __name__ == "__main__":
    unittest.main()
