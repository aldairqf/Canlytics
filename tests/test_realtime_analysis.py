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
    rekey_live_entries,
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
        prev = {"D0": 1, "D1": 2}
        cur = {"D0": 1, "D1": 255}
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
        _update_unique_history(e, {"D0": 1})
        _update_unique_history(e, {"D0": 2})
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
        row = {"ID": "100", "LEN": 8, **{f"D{i}": i for i in range(8)}}
        self.assertEqual(_entry_key(row, (0,)), ("100", 8, (0,)))
        # compare payload excludes the mux byte (index 0)
        self.assertEqual(_compare_payload(row, (0,)), tuple(range(1, 8)))

    def test_aggregate_mux_ignored_indexes(self):
        e = _entry(row={"ID": "100", "LEN": 8})
        configs = [MuxConfigEntry(can_id="100", length=None, mux_bytes=(2, 3))]
        self.assertEqual(_aggregate_mux_ignored_indexes([e], configs), {2, 3})


class RekeyLiveEntriesTests(unittest.TestCase):
    """BUGS.md B-05: reconfiguring mux can make two previously-distinct entries
    collapse onto the same new key. rekey_live_entries() must not silently orphan
    the loser into a permanent phantom contributor to aggregated stats."""

    def test_no_collision_just_moves_the_entry(self):
        entry = _entry(row={"ID": "100", "LEN": 8})
        entries = {("100", 8, ("01",)): entry}
        id_to_entries = {"100": [entry]}

        rekey_live_entries(entries, id_to_entries, [(("100", 8, ("01",)), ("100", 8, ()), entry)])

        self.assertEqual(entries, {("100", 8, ()): entry})
        self.assertEqual(id_to_entries["100"], [entry])

    def test_collision_discards_the_loser_from_entries_and_id_index(self):
        survivor = _entry(row={"ID": "100", "LEN": 8})
        loser = _entry(row={"ID": "100", "LEN": 8})
        old_key_a = ("100", 8, ("01",))
        old_key_b = ("100", 8, ("02",))
        new_key = ("100", 8, ())
        entries = {old_key_a: survivor, old_key_b: loser}
        id_to_entries = {"100": [survivor, loser]}

        rekey_live_entries(
            entries,
            id_to_entries,
            [(old_key_a, new_key, survivor), (old_key_b, new_key, loser)],
        )

        # Exactly one entry survives at the collapsed key -- no orphan left reachable
        # only via id_to_entries.
        self.assertEqual(entries, {new_key: survivor})
        self.assertEqual(id_to_entries["100"], [survivor])

    def test_collision_does_not_contaminate_aggregated_unique_counts(self):
        # This is the concrete symptom from BUGS.md B-05: before the fix, the loser
        # stayed in id_to_entries forever, permanently inflating this aggregate.
        survivor = _entry(row={"ID": "100", "LEN": 8}, unique_values=[{"AA"}] + [set()] * 7)
        loser = _entry(row={"ID": "100", "LEN": 8}, unique_values=[{"BB"}] + [set()] * 7)
        old_key_a = ("100", 8, ("01",))
        old_key_b = ("100", 8, ("02",))
        new_key = ("100", 8, ())
        entries = {old_key_a: survivor, old_key_b: loser}
        id_to_entries = {"100": [survivor, loser]}

        rekey_live_entries(
            entries,
            id_to_entries,
            [(old_key_a, new_key, survivor), (old_key_b, new_key, loser)],
        )

        self.assertEqual(_aggregate_unique_counts(id_to_entries["100"]), [1, 0, 0, 0, 0, 0, 0, 0])

    def test_three_way_collision_keeps_exactly_one_survivor(self):
        a = _entry(row={"ID": "100", "LEN": 8})
        b = _entry(row={"ID": "100", "LEN": 8})
        c = _entry(row={"ID": "100", "LEN": 8})
        new_key = ("100", 8, ())
        entries = {("k", 1): a, ("k", 2): b, ("k", 3): c}
        id_to_entries = {"100": [a, b, c]}

        rekey_live_entries(
            entries,
            id_to_entries,
            [(("k", 1), new_key, a), (("k", 2), new_key, b), (("k", 3), new_key, c)],
        )

        self.assertEqual(entries, {new_key: a})
        self.assertEqual(id_to_entries["100"], [a])

    def test_unrelated_ids_are_not_affected_by_a_collision_elsewhere(self):
        survivor = _entry(row={"ID": "100", "LEN": 8})
        loser = _entry(row={"ID": "100", "LEN": 8})
        other = _entry(row={"ID": "200", "LEN": 8})
        new_key = ("100", 8, ())
        entries = {("100", 8, ("01",)): survivor, ("100", 8, ("02",)): loser, ("200", 8, ()): other}
        id_to_entries = {"100": [survivor, loser], "200": [other]}

        rekey_live_entries(
            entries,
            id_to_entries,
            [
                (("100", 8, ("01",)), new_key, survivor),
                (("100", 8, ("02",)), new_key, loser),
                (("200", 8, ()), ("200", 8, ()), other),
            ],
        )

        self.assertEqual(id_to_entries["200"], [other])
        self.assertIn(("200", 8, ()), entries)


if __name__ == "__main__":
    unittest.main()
