"""Characterization tests for CandidateInterpretationsViewModel's progress throttle."""

from __future__ import annotations

import unittest

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


class MergeCheckedCanIdsTests(unittest.TestCase):
    """B-32: a live ID-list refresh must not reset the user's CAN ID selection."""

    def setUp(self):
        from views.candidate_interpretations_window import merge_checked_can_ids
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
