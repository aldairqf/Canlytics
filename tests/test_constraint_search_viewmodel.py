"""Characterization tests for ConstraintSearchViewModel's thin Qt-adapter behavior."""

from __future__ import annotations

import sys
import unittest

from PySide6.QtWidgets import QApplication

from services.constraint_search import SearchExclusions
from viewmodels.constraint_search_viewmodel import ConstraintSearchViewModel

_app: QApplication | None = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


class ConstraintSearchViewModelTests(unittest.TestCase):
    def setUp(self):
        self.vm = ConstraintSearchViewModel(items=[])

    def test_on_finished_emits_results_and_search_finished(self):
        results_seen = []
        finished_seen = []
        self.vm.results_changed.connect(lambda r, e: results_seen.append((r, e)))
        self.vm.search_finished.connect(lambda: finished_seen.append(True))

        exclusions = SearchExclusions(too_few_samples=2)
        self.vm._on_finished(["fake_result"], exclusions)

        self.assertEqual(results_seen, [(["fake_result"], exclusions)])
        self.assertEqual(finished_seen, [True])

    def test_on_canceled_emits_search_canceled_and_finished(self):
        canceled_seen = []
        finished_seen = []
        self.vm.search_canceled.connect(lambda: canceled_seen.append(True))
        self.vm.search_finished.connect(lambda: finished_seen.append(True))

        self.vm._on_canceled()

        self.assertEqual(canceled_seen, [True])
        self.assertEqual(finished_seen, [True])

    def test_on_failed_emits_message_and_finished(self):
        failed_seen = []
        self.vm.search_failed.connect(lambda msg: failed_seen.append(msg))
        self.vm._on_failed("boom")
        self.assertEqual(failed_seen, ["boom"])

    def test_running_is_false_before_any_run(self):
        self.assertFalse(self.vm.running)

    def test_cancel_and_shutdown_are_safe_when_nothing_is_running(self):
        self.vm.cancel()
        self.vm.shutdown()  # must not raise


if __name__ == "__main__":
    unittest.main()
