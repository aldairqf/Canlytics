"""Characterization tests for services/realtime_analysis pure helpers."""

from __future__ import annotations

import unittest

from models.mux_config import MuxConfigEntry
from services.realtime_analysis import (
    _LiveEntry,
    _active_highlighted_bytes,
    _aggregate_frame_period,
    _aggregate_mux_ignored_indexes,
    _aggregate_unique_counts,
    _changed_byte_indexes,
    _changed_bytes_from_row,
    _compare_payload,
    _entry_key,
    _fmt_period,
    _mux_bytes_for_row,
    _safe_float,
    _update_entry_period_stats,
    _update_unique_history,
    _with_delta_t,
    compute_changed_ids_delta,
)


def _entry(**kw):
    base = dict(row={}, compare_payload=(), last_seen_monotonic=0.0, first_seen_index=0)
    base.update(kw)
    return _LiveEntry(**base)


class ScalarHelpersTests(unittest.TestCase):
    def test_safe_float(self):
        self.assertEqual(_safe_float("1.5"), 1.5)
        self.assertEqual(_safe_float(3), 3.0)
        self.assertIsNone(_safe_float(None))
        self.assertIsNone(_safe_float("x"))

    def test_fmt_period(self):
        self.assertEqual(_fmt_period(None), "-")
        self.assertEqual(_fmt_period(0.5), "0.500000")


class ChangeTrackingTests(unittest.TestCase):
    def test_changed_byte_indexes_with_ignored(self):
        prev = {"B0": "01", "B1": "02"}
        cur = {"B0": "01", "B1": "FF"}
        self.assertEqual(_changed_byte_indexes(prev, cur), (1,))
        self.assertEqual(_changed_byte_indexes(prev, cur, ignored_indexes={1}), ())

    def test_with_delta_t_and_roundtrip(self):
        row = _with_delta_t({"ID": "100"}, 0.25, (1, 2))
        self.assertEqual(row["Delta T"], 0.25)
        self.assertEqual(row["_ChangedBytes"], "1,2")
        self.assertEqual(_changed_bytes_from_row(row), (1, 2))

    def test_changed_bytes_from_row_empty(self):
        self.assertEqual(_changed_bytes_from_row({"_ChangedBytes": ""}), ())

    def test_active_highlighted_bytes_hold_window(self):
        # now=101, hold=5s: index1 (age 1s) active, index2 (age 11s) expired
        active = _active_highlighted_bytes([None, 100.0, 90.0], now=101.0, hold_ms=5000)
        self.assertEqual(active, (1,))


class PeriodAndUniqueTests(unittest.TestCase):
    def test_period_stats_and_aggregate(self):
        e = _entry()
        for dt in (0.1, 0.3, 0.2):
            _update_entry_period_stats(e, dt, {})
        min_v, max_v, avg_v, count = _aggregate_frame_period([e])
        self.assertAlmostEqual(min_v, 0.1)
        self.assertAlmostEqual(max_v, 0.3)
        self.assertAlmostEqual(avg_v, 0.2)
        self.assertEqual(count, 3)

    def test_negative_delta_ignored(self):
        e = _entry()
        _update_entry_period_stats(e, -1.0, {})
        self.assertEqual(e.period_count, 0)

    def test_unique_counts(self):
        e = _entry()
        _update_unique_history(e, {"B0": "01"})
        _update_unique_history(e, {"B0": "02"})
        self.assertEqual(_aggregate_unique_counts([e]), [2, 0, 0, 0, 0, 0, 0, 0])


class MuxHelpersTests(unittest.TestCase):
    def test_mux_bytes_for_row_matches_id(self):
        configs = [MuxConfigEntry(can_id="100", length=None, mux_bytes=(0, 1))]
        self.assertEqual(_mux_bytes_for_row({"ID": "100", "LEN": 8}, configs), (0, 1))
        self.assertEqual(_mux_bytes_for_row({"ID": "200", "LEN": 8}, configs), ())

    def test_mux_bytes_respects_length(self):
        configs = [MuxConfigEntry(can_id="100", length=8, mux_bytes=(2,))]
        self.assertEqual(_mux_bytes_for_row({"ID": "100", "LEN": 8}, configs), (2,))
        self.assertEqual(_mux_bytes_for_row({"ID": "100", "LEN": 6}, configs), ())

    def test_entry_key_and_compare_payload(self):
        row = {"ID": "100", "LEN": 8, **{f"B{i}": f"{i:02X}" for i in range(8)}}
        self.assertEqual(_entry_key(row, (0,)), ("100", 8, ("00",)))
        # compare payload excludes the mux byte (index 0)
        self.assertEqual(_compare_payload(row, (0,)), tuple(f"{i:02X}" for i in range(1, 8)))

    def test_aggregate_mux_ignored_indexes(self):
        e = _entry(row={"ID": "100", "LEN": 8})
        configs = [MuxConfigEntry(can_id="100", length=None, mux_bytes=(2, 3))]
        self.assertEqual(_aggregate_mux_ignored_indexes([e], configs), {2, 3})


class ChangedIdsDeltaTests(unittest.TestCase):
    """compute_changed_ids_delta() backs the real-time analysis window's
    "Changes Only" CAN ID panel selection -- it decides whether the panel
    should just check newly-changed ids (grew) or fully resync (shrunk, e.g.
    after a baseline reset), so the View doesn't have to track a previous
    snapshot or make that call itself."""

    def test_grew_reports_only_the_newly_changed_ids(self):
        delta = compute_changed_ids_delta(frozenset({"100"}), frozenset({"100", "200"}))
        self.assertFalse(delta.reset)
        self.assertEqual(delta.ids, frozenset({"200"}))

    def test_unchanged_set_reports_grew_with_no_new_ids(self):
        delta = compute_changed_ids_delta(frozenset({"100"}), frozenset({"100"}))
        self.assertFalse(delta.reset)
        self.assertEqual(delta.ids, frozenset())

    def test_shrunk_reports_reset_with_the_full_new_set(self):
        # e.g. a baseline reset / mux reconfig / detect-changes cycle.
        delta = compute_changed_ids_delta(frozenset({"100", "200"}), frozenset({"200"}))
        self.assertTrue(delta.reset)
        self.assertEqual(delta.ids, frozenset({"200"}))

    def test_grown_then_shrunk_to_a_disjoint_set_reports_reset(self):
        # Not a superset in either direction -- must not be treated as "grew".
        delta = compute_changed_ids_delta(frozenset({"100", "200"}), frozenset({"300"}))
        self.assertTrue(delta.reset)
        self.assertEqual(delta.ids, frozenset({"300"}))

    def test_empty_to_empty_reports_grew_with_no_ids(self):
        delta = compute_changed_ids_delta(frozenset(), frozenset())
        self.assertFalse(delta.reset)
        self.assertEqual(delta.ids, frozenset())

    def test_reset_to_empty_reports_reset(self):
        delta = compute_changed_ids_delta(frozenset({"100"}), frozenset())
        self.assertTrue(delta.reset)
        self.assertEqual(delta.ids, frozenset())


if __name__ == "__main__":
    unittest.main()
