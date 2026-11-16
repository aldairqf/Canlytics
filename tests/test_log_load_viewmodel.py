from __future__ import annotations

import sys
import unittest

import polars as pl
from PySide6.QtWidgets import QApplication

from viewmodels.log_load_viewmodel import LogLoadViewModel

_app = QApplication.instance() or QApplication(sys.argv)


class LogLoadTerminalTests(unittest.TestCase):
    def test_cancel_racing_with_loaded_result_emits_terminal_signals(self):
        vm = LogLoadViewModel()

        class Worker:
            cancel_requested = True

        vm._worker = Worker()
        canceled, finished, loaded = [], [], []
        vm.load_canceled.connect(lambda: canceled.append(True))
        vm.load_finished.connect(lambda: finished.append(True))
        vm.loaded.connect(lambda *_args: loaded.append(True))
        vm._on_loaded("capture.log", pl.DataFrame(), True, None)
        self.assertEqual(canceled, [True])
        self.assertEqual(finished, [True])
        self.assertEqual(loaded, [])

