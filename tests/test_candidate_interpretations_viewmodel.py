"""Characterization tests for CandidateInterpretationsViewModel's progress throttle."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

import polars as pl

from viewmodels.candidate_interpretations_viewmodel import (
    CandidateInterpretationsViewModel,
    _ProgressThrottle,
)


class _FakeSignal:
    def __init__(self):
        self.calls: list[tuple[int, int]] = []

    def emit(self, done: int, total: int) -> None:
        self.calls.append((done, total))


class ProgressThrottleTests(unittest.TestCase):
    def test_emits_every_step_when_total_is_at_or_below_max_updates(self):
        throttle = _ProgressThrottle(max_updates=200)
        signal = _FakeSignal()
        for done in range(1, 51):
            throttle.maybe_emit(done, 50, signal)
        self.assertEqual(len(signal.calls), 50)

    def test_caps_emissions_for_a_large_total(self):
        throttle = _ProgressThrottle(max_updates=200)
        signal = _FakeSignal()
        total = 10_000
        for done in range(1, total + 1):
            throttle.maybe_emit(done, total, signal)
        self.assertLessEqual(len(signal.calls), 210)
        self.assertEqual(signal.calls[-1], (total, total))

    def test_always_emits_the_final_done_equals_total(self):
        throttle = _ProgressThrottle(max_updates=5)
        signal = _FakeSignal()
        for done in range(1, 8):
            throttle.maybe_emit(done, 7, signal)
        self.assertEqual(signal.calls[-1], (7, 7))


class CandidateDataframeUpdateTests(unittest.TestCase):
    def setUp(self):
        self.vm = CandidateInterpretationsViewModel()
        self.vm._items = [object()]
        self.emitted = []
        self.vm.candidate_list_changed.connect(self.emitted.append)

    def test_set_dataframe_preserves_results_during_append(self):
        self.vm.set_dataframe(pl.DataFrame({"ID": ["001"]}))

        self.assertEqual(len(self.vm._items), 1)
        self.assertNotIn([], self.emitted)

    def test_reset_dataframe_clears_results_on_replacement(self):
        self.vm.reset_dataframe(pl.DataFrame({"ID": ["002"]}))

        self.assertEqual(self.vm._items, [])
        self.assertIn([], self.emitted)


class CandidateSearchScopeTests(unittest.TestCase):
    def setUp(self):
        self.vm = CandidateInterpretationsViewModel()
        self.vm.set_dataframe(pl.DataFrame({
            "ID": ["100"] * 5,
            "TS": [1.0, 2.0, 3.0, 4.0, 5.0],
        }))

    def test_time_ranges_include_a_and_b_but_exclude_the_gap(self):
        self.vm.set_time_ranges(((1.0, 2.0), (4.0, 5.0)))

        self.assertEqual(self.vm._effective_df().get_column("TS").to_list(), [1.0, 2.0, 4.0, 5.0])

    def test_candidate_correlation_runs_in_owned_worker_and_reports_progress(self):
        probe = """
import numpy as np
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from services.candidate_interpretations import CandidateItem
from viewmodels.candidate_interpretations_viewmodel import CandidateInterpretationsViewModel

def item(label, can_id, values, score):
    values = tuple(float(value) for value in values)
    timestamps = tuple(float(value) for value in range(len(values)))
    return CandidateItem(label, can_id, 8, "all", 0, 0, None, 0, 8, "LittleEndian", "Unsigned",
        len(values), len(values)-1, len(set(values)), score, min(values), max(values), (), timestamps, values)

app = QCoreApplication.instance() or QCoreApplication([])
vm = CandidateInterpretationsViewModel()
values = np.arange(20, dtype=float)
finished = []
progress = []
loop = QEventLoop()
vm.candidate_correlation_finished.connect(lambda clusters: (finished.append(clusters), loop.quit()))
vm.candidate_correlation_progress.connect(lambda done, total: progress.append((done, total)))
vm.find_correlated_candidates(
    [item("a", "100", values, 0.4), item("b", "200", values * 2, 0.9)],
    threshold=0.95, min_samples=12, max_points=500,
)
QTimer.singleShot(3000, loop.quit)
loop.exec()
assert len(finished) == 1 and len(finished[0]) == 1
assert finished[0][0].representative.label == "b"
assert progress[-1] == (3, 3)
thread = vm._correlation_thread
if thread is not None:
    thread.wait(3000)
app.processEvents()
vm.shutdown()
"""
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_mux_configuration_change_cancels_worker_and_invalidates_its_results(self) -> None:
        from models.mux_config import MuxConfigEntry

        worker = Mock()
        thread = Mock()
        thread.isRunning.return_value = True
        self.vm._worker = worker
        self.vm._thread = thread
        old_generation = self.vm._search_generation

        self.vm.set_mux_configuration([MuxConfigEntry(can_id="100", length=8, mux_bytes=(0,))])

        self.assertGreater(self.vm._search_generation, old_generation)
        worker.cancel.assert_called_once_with()
        self.assertEqual(self.vm._items, [])

    def test_byte_scope_is_validated_and_normalized(self):
        self.vm.set_byte_indices([2, 1, 2])
        self.assertEqual(self.vm._byte_indices, frozenset({1, 2}))
        with self.assertRaises(ValueError):
            self.vm.set_byte_indices([8])

    def test_scope_change_cancels_worker_and_discards_its_stale_results(self):
        worker = Mock()
        thread = Mock()
        thread.isRunning.return_value = True
        self.vm._worker = worker
        self.vm._thread = thread
        old_generation = self.vm._search_generation
        finished = []
        self.vm.recalculation_finished.connect(lambda: finished.append(True))

        self.vm.set_time_ranges(((1.0, 2.0), (4.0, 5.0)))
        self.vm.set_byte_indices([1])
        self.vm.recalculate()
        self.vm._on_recalculation_finished([object()], old_generation)

        self.assertGreater(self.vm._search_generation, old_generation)
        self.assertGreaterEqual(worker.cancel.call_count, 3)
        self.assertTrue(self.vm._pending_recalculation)
        self.assertEqual(self.vm._items, [])
        self.assertEqual(finished, [True])

    def test_cleanup_restarts_a_recalculation_queued_behind_cancelled_worker(self):
        self.vm._worker = Mock()
        self.vm._thread = Mock()
        self.vm._pending_recalculation = True
        self.vm.recalculate = Mock()

        self.vm._cleanup_worker()

        self.vm.recalculate.assert_called_once_with()

    def test_recalculate_waits_for_finished_thread_cleanup_before_replacing_it(self):
        thread = Mock()
        thread.isRunning.return_value = False
        self.vm._thread = thread

        self.vm.recalculate()

        self.assertIs(self.vm._thread, thread)
        self.assertTrue(self.vm._pending_recalculation)

    def test_worker_completion_updates_viewmodel_on_its_own_thread(self):
        probe = """
from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QThread, QTimer, Signal
from viewmodels.candidate_interpretations_viewmodel import CandidateInterpretationsViewModel

class Emitter(QObject):
    finished = Signal(object, int)
    def run(self):
        self.finished.emit([], 7)

app = QCoreApplication.instance() or QCoreApplication([])
vm = CandidateInterpretationsViewModel()
vm._search_generation = 7
worker = Emitter()
thread = QThread()
worker.moveToThread(thread)
worker.finished.connect(vm._on_recalculation_finished)
worker.finished.connect(thread.quit)
thread.started.connect(worker.run)
thread.finished.connect(worker.deleteLater)
delivered_threads = []
vm.candidate_list_changed.connect(
    lambda _items: delivered_threads.append(QThread.currentThread())
)
loop = QEventLoop()
vm.recalculation_finished.connect(loop.quit)
thread.start()
QTimer.singleShot(3000, loop.quit)
loop.exec()
thread.wait()
app.processEvents()
assert vm._items == []
assert delivered_threads
assert delivered_threads[0] == vm.thread()
"""
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class MergeCheckedCanIdsTests(unittest.TestCase):
    """B-32: a live ID-list refresh must not reset the user's CAN ID selection."""

    def setUp(self):
        from utils.can_id import merge_checked_can_ids
        self.merge = merge_checked_can_ids

    def test_narrowed_selection_survives_refresh_and_new_ids_stay_unchecked(self):
        previous = {"181": True, "182": False, "183": True}
        merged = self.merge(previous, ["181", "182", "183", "1A8"])
        self.assertEqual(merged, {"181": True, "182": False, "183": True, "1A8": False})

    def test_new_ids_are_checked_when_everything_was_checked(self):
        merged = self.merge({"181": True, "182": True}, ["181", "182", "1A8"])
        self.assertEqual(merged, {"181": True, "182": True, "1A8": True})

    def test_first_population_checks_everything(self):
        self.assertEqual(self.merge({}, ["181", "182"]), {"181": True, "182": True})


if __name__ == "__main__":
    unittest.main()
