"""Characterization tests for services/constraint_search.py (BUGS.md B-21..B-24).

Extracted from views/candidate_constraint_search.py so the "Value at Time" search
that used to run synchronously on the GUI thread, with zero test coverage, is now
Qt-free and testable.
"""

from __future__ import annotations

import unittest

from services.candidate_interpretations import CandidateItem
from services.constraint_search import (
    Constraint,
    ConstraintSearchCanceled,
    clamp_target,
    normalize,
    search_candidates,
    time_to_abs,
)


def _item(label: str, timestamps: list[float], values: list[float]) -> CandidateItem:
    return CandidateItem(
        label=label, can_id="100", frame_len=8, mux_label="None",
        mux_start=0, mux_bytes=0, mux_value=None,
        start_bit=0, signal_length=8, byte_order="LittleEndian", value_type="Unsigned",
        frames=len(values), changes=0, distinct_values=len(set(values)), score=0.5,
        min_value=min(values) if values else None, max_value=max(values) if values else None,
        sample_values=(), timestamps=tuple(timestamps), values=tuple(values),
    )


class NormalizeTests(unittest.TestCase):
    def test_normalizes_to_0_1_range(self):
        import numpy as np
        y_norm, y_min, y_span = normalize(np.array([10.0, 20.0, 30.0]))
        self.assertEqual(y_min, 10.0)
        self.assertEqual(y_span, 20.0)
        self.assertEqual(list(y_norm), [0.0, 0.5, 1.0])

    def test_zero_span_returns_zeros(self):
        import numpy as np
        y_norm, y_min, y_span = normalize(np.array([5.0, 5.0, 5.0]))
        self.assertEqual(y_span, 0.0)
        self.assertEqual(list(y_norm), [0.0, 0.0, 0.0])


class ClampTargetTests(unittest.TestCase):
    def test_in_range_value_not_clamped(self):
        value, was_clamped = clamp_target(0.5)
        self.assertEqual(value, 0.5)
        self.assertFalse(was_clamped)

    def test_above_range_clamped_to_1(self):
        value, was_clamped = clamp_target(75.0)
        self.assertEqual(value, 1.0)
        self.assertTrue(was_clamped)

    def test_below_range_clamped_to_0(self):
        value, was_clamped = clamp_target(-3.0)
        self.assertEqual(value, 0.0)
        self.assertTrue(was_clamped)

    def test_boundary_values_not_clamped(self):
        self.assertEqual(clamp_target(0.0), (0.0, False))
        self.assertEqual(clamp_target(1.0), (1.0, False))


class TimeToAbsTests(unittest.TestCase):
    def test_elapsed_mode_ignores_timezone_and_uses_t_min(self):
        result = time_to_abs(0, 1, 30, t_min=1000.0, timezone_mode="none")
        self.assertEqual(result, 1000.0 + 90)

    def test_elapsed_mode_day_offset_adds_a_full_day(self):
        result = time_to_abs(0, 0, 0, t_min=1000.0, timezone_mode="none", day_offset=1)
        self.assertEqual(result, 1000.0 + 86400)

    def test_clock_mode_utc_resolves_the_same_calendar_day_by_default(self):
        # 2024-01-01 00:00:00 UTC
        t_min = 1704067200.0
        result = time_to_abs(12, 0, 0, t_min=t_min, timezone_mode="UTC")
        self.assertEqual(result, t_min + 12 * 3600)

    def test_clock_mode_day_offset_targets_the_next_calendar_day(self):
        # B-23: a recording crossing midnight can target "day 2" via day_offset.
        t_min = 1704067200.0  # 2024-01-01 00:00:00 UTC
        result = time_to_abs(1, 0, 0, t_min=t_min, timezone_mode="UTC", day_offset=1)
        expected = t_min + 86400 + 3600  # 2024-01-02 01:00:00 UTC
        self.assertEqual(result, expected)

    def test_unknown_timezone_falls_back_to_elapsed(self):
        result = time_to_abs(0, 0, 5, t_min=1000.0, timezone_mode="Not/A_Real_Zone")
        self.assertEqual(result, 1005.0)


class SearchCandidatesTests(unittest.TestCase):
    def test_matches_a_candidate_hitting_all_constraints(self):
        item = _item("sig", [0.0, 1.0, 2.0, 3.0], [0.0, 10.0, 20.0, 30.0])
        constraints = [Constraint(time_abs=1.0, target_norm=1 / 3)]
        results, exclusions = search_candidates([item], constraints, precision=0.5, tolerance=0.05)
        self.assertEqual(len(results), 1)
        self.assertIs(results[0].item, item)
        self.assertEqual(exclusions.total, 0)

    def test_excludes_a_candidate_outside_tolerance(self):
        item = _item("sig", [0.0, 1.0, 2.0], [0.0, 10.0, 20.0])
        constraints = [Constraint(time_abs=1.0, target_norm=0.9)]  # actual norm here is 0.5
        results, exclusions = search_candidates([item], constraints, precision=0.5, tolerance=0.05)
        self.assertEqual(results, [])
        self.assertEqual(exclusions.outside_tolerance, 1)

    def test_excludes_a_candidate_with_too_few_samples(self):
        item = _item("sig", [0.0], [5.0])
        results, exclusions = search_candidates([item], [Constraint(0.0, 0.5)], precision=1.0, tolerance=0.5)
        self.assertEqual(results, [])
        self.assertEqual(exclusions.too_few_samples, 1)

    def test_excludes_a_constant_candidate_zero_variance(self):
        item = _item("sig", [0.0, 1.0, 2.0], [5.0, 5.0, 5.0])
        results, exclusions = search_candidates([item], [Constraint(0.0, 0.5)], precision=1.0, tolerance=0.5)
        self.assertEqual(results, [])
        self.assertEqual(exclusions.zero_variance, 1)

    def test_excludes_a_candidate_with_no_data_near_a_constraint(self):
        item = _item("sig", [0.0, 1.0, 2.0], [0.0, 10.0, 20.0])
        constraints = [Constraint(time_abs=100.0, target_norm=0.5)]  # far outside precision window
        results, exclusions = search_candidates([item], constraints, precision=1.0, tolerance=0.5)
        self.assertEqual(results, [])
        self.assertEqual(exclusions.no_data_near_constraint, 1)

    def test_multiple_constraints_all_must_match(self):
        item = _item("sig", [0.0, 1.0, 2.0, 3.0], [0.0, 10.0, 20.0, 30.0])
        constraints = [
            Constraint(time_abs=1.0, target_norm=1 / 3),
            Constraint(time_abs=2.0, target_norm=0.9),  # this one fails (actual is 2/3)
        ]
        results, exclusions = search_candidates([item], constraints, precision=0.5, tolerance=0.05)
        self.assertEqual(results, [])
        self.assertEqual(exclusions.outside_tolerance, 1)

    def test_reports_progress_per_item(self):
        items = [_item(f"s{i}", [0.0, 1.0], [0.0, 1.0]) for i in range(3)]
        seen = []
        search_candidates(items, [Constraint(0.0, 0.0)], precision=1.0, tolerance=1.0,
                           on_progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(seen, [(1, 3), (2, 3), (3, 3)])

    def test_cancels_via_should_cancel(self):
        items = [_item(f"s{i}", [0.0, 1.0], [0.0, 1.0]) for i in range(3)]
        calls = []

        def should_cancel():
            calls.append(1)
            return len(calls) > 1

        with self.assertRaises(ConstraintSearchCanceled):
            search_candidates(items, [Constraint(0.0, 0.0)], precision=1.0, tolerance=1.0, should_cancel=should_cancel)

    def test_empty_items_returns_empty_results_and_no_exclusions(self):
        results, exclusions = search_candidates([], [Constraint(0.0, 0.5)], precision=1.0, tolerance=0.1)
        self.assertEqual(results, [])
        self.assertEqual(exclusions.total, 0)

    def test_no_constraints_matches_every_valid_candidate(self):
        item = _item("sig", [0.0, 1.0, 2.0], [0.0, 10.0, 20.0])
        results, exclusions = search_candidates([item], [], precision=1.0, tolerance=0.1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].hits, ())


if __name__ == "__main__":
    unittest.main()
