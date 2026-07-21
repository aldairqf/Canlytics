"""Characterization tests for services/monotonic_changed_set.py.

Shared by Real-Time's "Changes Only" panel, and (P2.3 follow-up) Diff Analyzer
Live / Analyze Data Matrix Live (AN3) -- one implementation, tested once.
"""

from __future__ import annotations

import unittest

from services.monotonic_changed_set import compute_changed_set_delta


class ComputeChangedSetDeltaTests(unittest.TestCase):
    def test_grew_reports_only_the_newly_changed_members(self):
        delta = compute_changed_set_delta(frozenset({"100"}), frozenset({"100", "200"}))
        self.assertFalse(delta.reset)
        self.assertEqual(delta.members, frozenset({"200"}))

    def test_unchanged_set_reports_grew_with_no_new_members(self):
        delta = compute_changed_set_delta(frozenset({"100"}), frozenset({"100"}))
        self.assertFalse(delta.reset)
        self.assertEqual(delta.members, frozenset())

    def test_shrunk_reports_reset_with_the_full_new_set(self):
        # e.g. a baseline reset / mux reconfig / detect-changes cycle.
        delta = compute_changed_set_delta(frozenset({"100", "200"}), frozenset({"200"}))
        self.assertTrue(delta.reset)
        self.assertEqual(delta.members, frozenset({"200"}))

    def test_grown_then_shrunk_to_a_disjoint_set_reports_reset(self):
        # Not a superset in either direction -- must not be treated as "grew".
        delta = compute_changed_set_delta(frozenset({"100", "200"}), frozenset({"300"}))
        self.assertTrue(delta.reset)
        self.assertEqual(delta.members, frozenset({"300"}))

    def test_empty_to_empty_reports_grew_with_no_members(self):
        delta = compute_changed_set_delta(frozenset(), frozenset())
        self.assertFalse(delta.reset)
        self.assertEqual(delta.members, frozenset())

    def test_reset_to_empty_reports_reset(self):
        delta = compute_changed_set_delta(frozenset({"100"}), frozenset())
        self.assertTrue(delta.reset)
        self.assertEqual(delta.members, frozenset())


if __name__ == "__main__":
    unittest.main()
