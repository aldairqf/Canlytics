from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from viewmodels.measurement_status_viewmodel import MeasurementStatusViewModel

_app: QApplication | None = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


class MeasurementStatusViewModelTests(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch("viewmodels.measurement_status_viewmodel.system_memory_bytes", return_value=100),
            patch("viewmodels.measurement_status_viewmodel.process_memory_bytes", return_value=80),
            patch("viewmodels.measurement_status_viewmodel.get_option", side_effect=lambda key, default=None: {
                "measurement_status_refresh_ms": 60000,
                "memory_warning_absolute_bytes": 100,
                "memory_warning_system_fraction": 0.6,
            }.get(key, default)),
        ]
        for item in self.patches:
            item.start()
        self.vm = MeasurementStatusViewModel()

    def tearDown(self):
        self.vm.shutdown()
        for item in reversed(self.patches):
            item.stop()

    def test_row_deltas_increment_and_replacements_reset_the_count(self):
        self.vm.append_rows(SimpleNamespace(height=4))
        self.vm.append_rows(SimpleNamespace(height=3))
        self.assertEqual(self.vm.status.frame_count, 7)

        self.vm.replace_data(SimpleNamespace(height=2))
        self.assertEqual(self.vm.status.frame_count, 2)

    def test_warning_emits_once_per_threshold_crossing(self):
        warnings = []
        self.vm.memory_warning_requested.connect(lambda used, limit: warnings.append((used, limit)))
        self.vm.replace_data(SimpleNamespace(height=1))
        self.vm.refresh()
        self.vm.refresh()
        self.assertEqual(warnings, [(80, 60)])

        self.vm.replace_data(SimpleNamespace(height=0))
        self.vm.refresh()
        self.vm.replace_data(SimpleNamespace(height=1))
        self.vm.refresh()
        self.assertEqual(warnings, [(80, 60), (80, 60)])


if __name__ == "__main__":
    unittest.main()
