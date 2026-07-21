"""Characterization tests for CandidateInterpretationsViewModel's progress throttle."""

from __future__ import annotations

import unittest

from viewmodels.candidate_interpretations_viewmodel import _ProgressThrottle


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


if __name__ == "__main__":
    unittest.main()
