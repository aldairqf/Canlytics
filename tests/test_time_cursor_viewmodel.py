from __future__ import annotations

import math
import unittest

from PySide6.QtCore import QCoreApplication

from viewmodels.time_cursor_viewmodel import TimeCursorViewModel


class TimeCursorViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_publishes_finite_epoch_timestamp_and_origin(self):
        vm = TimeCursorViewModel()
        received = []
        vm.cursor_changed.connect(lambda timestamp, source: received.append((timestamp, source)))

        self.assertTrue(vm.set_timestamp(123.5, "main_table"))
        self.assertEqual(vm.timestamp, 123.5)
        self.assertEqual(received, [(123.5, "main_table")])

    def test_rejects_non_finite_or_non_numeric_values(self):
        vm = TimeCursorViewModel()
        for value in (math.nan, math.inf, -math.inf, "bad"):
            self.assertFalse(vm.set_timestamp(value))
        self.assertIsNone(vm.timestamp)

    def test_suppresses_duplicate_echo_from_the_same_surface(self):
        vm = TimeCursorViewModel()
        received = []
        vm.cursor_changed.connect(lambda *args: received.append(args))

        self.assertTrue(vm.set_timestamp(5.0, "plot"))
        self.assertFalse(vm.set_timestamp(5.0, "plot"))
        self.assertEqual(len(received), 1)
