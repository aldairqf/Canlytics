from __future__ import annotations

import sys
import unittest

from PySide6.QtWidgets import QApplication

from views.widgets.eta_progress_dialog import EtaProgressDialog
from viewmodels.log_load_viewmodel import LogLoadViewModel

_app = QApplication.instance() or QApplication(sys.argv)


class EtaProgressDialogTests(unittest.TestCase):
    def test_progress_updates_keep_dialog_visible_until_load_finished(self):
        vm = LogLoadViewModel()
        dialog = EtaProgressDialog("Loading", "Cancel")
        vm.progress.connect(dialog.report_progress)
        vm.load_finished.connect(dialog.close)
        dialog.start()
        for value in (10, 40, 85, 95):
            vm.progress.emit(value, 100)
        self.assertTrue(dialog.isVisible())
        vm.load_finished.emit()
        self.assertFalse(dialog.isVisible())
        self.assertFalse(dialog._tick_timer.isActive())

    def test_large_totals_use_fixed_integer_range_and_dialog_stays_open(self):
        dialog = EtaProgressDialog("Loading", "Cancel")
        dialog.start()
        dialog.report_progress(1_500_000_000, 3_000_000_000)
        self.assertEqual(dialog.maximum(), 1000)
        self.assertEqual(dialog.value(), 500)
        self.assertFalse(dialog.autoReset())
        self.assertFalse(dialog.autoClose())
        dialog.report_progress(3_000_000_000, 3_000_000_000)
        self.assertTrue(dialog.isVisible())
        dialog.close()
