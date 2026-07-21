"""Characterization tests for services/range_diff.py.

Pins the byte-level change taxonomy (classify_byte), the counter overlay
(looks_counter/is_counter), the offline report builder (presence, len_changed,
byte presence under a varying LEN), and the display-time filter (visible())
never needing to re-scan the source dataframe.
"""

from __future__ import annotations

import os
import random
import tempfile
import unittest

from PySide6.QtCore import QCoreApplication

from services.can_data_parser import empty_frame, frame_dict, rows_to_df
from services.dbc_manager import DbcManager
from services.range_diff import (
    ChangeType,
    DiffOptions,
    TimeRange,
    build_range_diff_report,
    classify_byte,
    dbc_hint_for_byte,
    export_range_diff_csv,
    frame_density,
    observe_byte,
    slice_window,
)

try:
    import scipy  # noqa: F401

    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False

# DbcManager is a QObject; ensure an application object exists.
_app = QCoreApplication.instance() or QCoreApplication([])

_DBC = """VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ 256 MsgByte0: 8 ECU
 SG_ SigByte0 : 0|8@1+ (1,0) [0|255] "unit" ECU
"""


def _row(ts, can_id, *byte_values, bus="b"):
    return frame_dict(ts=ts, bus=bus, can_id=can_id, data=bytes(byte_values))


class ObserveByteTests(unittest.TestCase):
    def test_basic_stats(self):
        obs = observe_byte([5, 5, 5, 7, 7])
        self.assertEqual(obs.n_frames, 5)
        self.assertEqual(obs.values, (5, 7))
        self.assertEqual(obs.vmin, 5)
        self.assertEqual(obs.vmax, 7)
        self.assertAlmostEqual(obs.mean, 5.8)
        self.assertEqual(obs.first, 5)
        self.assertEqual(obs.last, 7)
        self.assertAlmostEqual(obs.change_ratio, 0.25)

    def test_single_frame_has_zero_change_ratio_and_no_counter(self):
        obs = observe_byte([3])
        self.assertEqual(obs.n_frames, 1)
        self.assertEqual(obs.change_ratio, 0.0)
        self.assertFalse(obs.looks_counter)

    def test_looks_counter_monotonic_full_range(self):
        obs = observe_byte(list(range(256)))
        self.assertTrue(obs.looks_counter)

    def test_looks_counter_toggle_between_two_values(self):
        obs = observe_byte([0, 1] * 20)
        self.assertTrue(obs.looks_counter)

    def test_looks_counter_false_for_constant(self):
        obs = observe_byte([5] * 10)
        self.assertFalse(obs.looks_counter)

    def test_looks_counter_false_for_varied_physical_value(self):
        obs = observe_byte([10, 50, 10, 80, 5, 60, 40, 90])
        self.assertFalse(obs.looks_counter)


class ClassifyByteTests(unittest.TestCase):
    def test_unchanged_when_both_windows_are_the_same_constant(self):
        diff = classify_byte(observe_byte([5] * 10), observe_byte([5] * 8))
        self.assertEqual(diff.change_type, ChangeType.UNCHANGED)
        self.assertEqual(diff.score, 0.0)
        self.assertEqual(diff.new_values, ())
        self.assertEqual(diff.lost_values, ())

    def test_same_oscillation_when_value_set_is_unchanged(self):
        diff = classify_byte(
            observe_byte([1, 2, 3, 1, 2, 3]),
            observe_byte([3, 2, 1, 3, 2, 1]),
        )
        self.assertEqual(diff.change_type, ChangeType.SAME_OSCILLATION)
        self.assertFalse(diff.is_counter)

    def test_const_shift_from_one_fixed_value_to_another(self):
        diff = classify_byte(observe_byte([5] * 6), observe_byte([9] * 6))
        self.assertEqual(diff.change_type, ChangeType.CONST_SHIFT)
        self.assertAlmostEqual(diff.delta_mean, 4.0)
        self.assertGreater(diff.score, 0.0)

    def test_new_territory_when_b_gains_values(self):
        diff = classify_byte(
            observe_byte([1, 2, 3] * 3),
            observe_byte([1, 2, 3, 4] * 3),
        )
        self.assertEqual(diff.change_type, ChangeType.NEW_TERRITORY)
        self.assertEqual(diff.new_values, (4,))

    def test_range_shift_when_b_narrows_without_new_values(self):
        diff = classify_byte(
            observe_byte([1, 2, 3] * 3),
            observe_byte([1, 2] * 3),
        )
        self.assertEqual(diff.change_type, ChangeType.RANGE_SHIFT)
        self.assertEqual(diff.lost_values, (3,))
        self.assertEqual(diff.new_values, ())

    def test_full_cycle_counter_is_same_oscillation_with_counter_overlay(self):
        # Same full 0..255 set both sides -> SAME_OSCILLATION, but still flagged as a counter.
        diff = classify_byte(observe_byte(list(range(256))), observe_byte(list(range(256))))
        self.assertEqual(diff.change_type, ChangeType.SAME_OSCILLATION)
        self.assertTrue(diff.is_counter)

    def test_partial_cycle_counter_is_new_territory_with_counter_overlay(self):
        # Counter over a shifted sub-range -> NEW_TERRITORY, still flagged as a counter.
        diff = classify_byte(observe_byte(list(range(0, 10))), observe_byte(list(range(5, 15))))
        self.assertEqual(diff.change_type, ChangeType.NEW_TERRITORY)
        self.assertTrue(diff.is_counter)

    def test_p_value_is_none_when_theres_nothing_to_test(self):
        diff = classify_byte(observe_byte([5] * 5), observe_byte([5] * 3))
        self.assertIsNone(diff.p_value)

    @unittest.skipUnless(_HAS_SCIPY, "scipy not installed")
    def test_p_value_is_small_for_a_clear_well_sampled_shift(self):
        diff = classify_byte(observe_byte([5] * 20), observe_byte([9] * 20))
        self.assertEqual(diff.change_type, ChangeType.CONST_SHIFT)
        self.assertIsNotNone(diff.p_value)
        self.assertLess(diff.p_value, 0.05)

    @unittest.skipUnless(_HAS_SCIPY, "scipy not installed")
    def test_p_value_is_not_significant_with_only_two_frames_per_side(self):
        # n=2,2 can never reach p < 0.05 for Mann-Whitney, even fully separated.
        diff = classify_byte(observe_byte([5, 5]), observe_byte([9, 9]))
        self.assertEqual(diff.change_type, ChangeType.CONST_SHIFT)
        self.assertIsNotNone(diff.p_value)
        self.assertGreaterEqual(diff.p_value, 0.05)


class SliceWindowAndDensityTests(unittest.TestCase):
    def test_slice_window_is_inclusive_on_both_ends(self):
        df = rows_to_df([_row(float(ts), "100", 1) for ts in range(11)])
        sliced = slice_window(df, TimeRange(start=2.0, end=5.0))
        self.assertEqual(sorted(sliced.get_column("TS").to_list()), [2.0, 3.0, 4.0, 5.0])

    def test_frame_density_buckets_cover_all_frames(self):
        df = rows_to_df([_row(float(ts), "100", 1) for ts in range(20)])
        edges, counts = frame_density(df, buckets=4)
        self.assertEqual(len(edges), 5)
        self.assertEqual(len(counts), 4)
        self.assertEqual(sum(counts), 20)

    def test_frame_density_empty_df(self):
        edges, counts = frame_density(empty_frame(), buckets=4)
        self.assertEqual((edges, counts), ([], []))


class BuildRangeDiffReportTests(unittest.TestCase):
    def _report(self, rows, *, dbc_manager=None):
        df = rows_to_df(rows)
        return build_range_diff_report(
            df, TimeRange(start=0.0, end=4.0), TimeRange(start=10.0, end=14.0), dbc_manager=dbc_manager
        )

    def test_empty_dataframe_returns_no_ids(self):
        report = build_range_diff_report(empty_frame(), TimeRange(0.0, 1.0), TimeRange(2.0, 3.0))
        self.assertEqual(report.ids, ())

    def test_presence_only_a(self):
        rows = [_row(1.0, "100", 5)]  # only inside range A
        report = self._report(rows)
        item = next(i for i in report.ids if i.can_id == "100")
        self.assertEqual(item.presence, "only_a")
        self.assertEqual(item.frames_a, 1)
        self.assertEqual(item.frames_b, 0)
        self.assertEqual(item.byte_diffs, ())

    def test_presence_only_b(self):
        rows = [_row(11.0, "100", 5)]  # only inside range B
        report = self._report(rows)
        item = next(i for i in report.ids if i.can_id == "100")
        self.assertEqual(item.presence, "only_b")
        self.assertEqual(item.frames_a, 0)
        self.assertEqual(item.frames_b, 1)

    def test_len_changed_flagged_when_declared_length_differs(self):
        rows = [_row(1.0, "100", 1, 2, 3, 4)] * 3 + [_row(11.0, "100", 1, 2, 3, 4, 5, 6, 7, 8)] * 3
        report = self._report(rows)
        item = next(i for i in report.ids if i.can_id == "100")
        self.assertTrue(item.len_changed)

    def test_byte_beyond_declared_len_is_skipped_not_zero_padded(self):
        # Window A LEN=4 (byte 5 absent), window B LEN=8 -- byte 5 must not appear.
        rows = [_row(1.0, "100", 1, 2, 3, 4)] * 3 + [_row(11.0, "100", 1, 2, 3, 4, 5, 10, 7, 8)] * 3
        report = self._report(rows)
        item = next(i for i in report.ids if i.can_id == "100")
        self.assertTrue(item.len_changed)
        self.assertNotIn(5, {d.byte_index for d in item.byte_diffs})

    def test_ids_sorted_by_score_descending(self):
        rows = (
            [_row(t, "100", 5) for t in range(3)] + [_row(t + 10, "100", 5) for t in range(3)]  # UNCHANGED, score 0
            + [_row(t, "200", 5) for t in range(3)] + [_row(t + 10, "200", 9) for t in range(3)]  # CONST_SHIFT
        )
        report = self._report(rows)
        scores = [item.score for item in report.ids]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(report.ids[0].can_id, "200")

    def test_dbc_hint_names_the_signal_covering_a_changed_byte(self):
        fd, path = tempfile.mkstemp(suffix=".dbc")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(_DBC)
            mgr = DbcManager()
            mgr.load_dbc(path)

            rows = [_row(t, "100", 5) for t in range(3)] + [_row(t + 10, "100", 9) for t in range(3)]
            report = self._report(rows, dbc_manager=mgr)
            item = next(i for i in report.ids if i.can_id == "100")
            self.assertEqual(item.dbc_hint, "SigByte0")
        finally:
            os.remove(path)

    def test_dbc_hint_is_none_without_a_dbc_manager(self):
        rows = [_row(t, "100", 5) for t in range(3)] + [_row(t + 10, "100", 9) for t in range(3)]
        report = self._report(rows)
        item = next(i for i in report.ids if i.can_id == "100")
        self.assertIsNone(item.dbc_hint)


class MultiByteHintTests(unittest.TestCase):
    """P2.3: Diff Analyzer reports the same carry-alignment hint as Candidate
    Interpretations (P2.2), fed from ByteObservation.raw already captured per window."""

    def test_carry_linked_bytes_report_the_hint(self):
        values = list(range(0, 3000, 5))
        rows_a = [_row(float(i), "100", v % 256, (v // 256) % 256) for i, v in enumerate(values[:150])]
        rows_b = [_row(float(i) + 100.0, "100", v % 256, (v // 256) % 256) for i, v in enumerate(values[150:300])]
        df = rows_to_df(rows_a + rows_b)
        report = build_range_diff_report(df, TimeRange(0.0, 149.0), TimeRange(100.0, 249.0))
        item = next(i for i in report.ids if i.can_id == "100")
        byte0 = next(d for d in item.byte_diffs if d.byte_index == 0)
        self.assertIn("B1", byte0.multi_byte_hint)
        self.assertIn("likely 16-bit", byte0.multi_byte_hint)

    def test_independent_bytes_are_not_flagged(self):
        rng = random.Random(9)
        rows_a = [_row(float(t), "100", rng.randint(0, 255), rng.randint(0, 255)) for t in range(200)]
        rows_b = [_row(float(t) + 300.0, "100", rng.randint(0, 255), rng.randint(0, 255)) for t in range(200)]
        df = rows_to_df(rows_a + rows_b)
        report = build_range_diff_report(df, TimeRange(0.0, 199.0), TimeRange(300.0, 499.0))
        item = next(i for i in report.ids if i.can_id == "100")
        byte0 = next(d for d in item.byte_diffs if d.byte_index == 0)
        self.assertNotIn("likely 16-bit", byte0.multi_byte_hint)

    def test_last_byte_has_no_neighbor_so_hint_is_empty(self):
        rows = [_row(t, "100", 1, 2, 3, 4, 5, 6, 7, 8) for t in range(3)]
        rows += [_row(t + 10, "100", 1, 2, 3, 4, 5, 6, 7, 9) for t in range(3)]
        report = self._make_report(rows)
        item = next(i for i in report.ids if i.can_id == "100")
        byte7 = next(d for d in item.byte_diffs if d.byte_index == 7)
        self.assertEqual(byte7.multi_byte_hint, "")

    def _make_report(self, rows):
        df = rows_to_df(rows)
        return build_range_diff_report(df, TimeRange(start=0.0, end=4.0), TimeRange(start=10.0, end=14.0))


class DbcHintForByteTests(unittest.TestCase):
    """B-17: per-byte DBC hint, scoped to a single byte instead of the whole id."""

    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".dbc")
        with os.fdopen(self._fd, "w", encoding="utf-8") as handle:
            handle.write(_DBC)
        self.mgr = DbcManager()
        self.mgr.load_dbc(self._path)

    def tearDown(self):
        os.remove(self._path)

    def test_names_the_signal_covering_that_byte(self):
        self.assertEqual(dbc_hint_for_byte(self.mgr, "100", 0), "SigByte0")

    def test_none_for_a_byte_with_no_covering_signal(self):
        self.assertIsNone(dbc_hint_for_byte(self.mgr, "100", 5))

    def test_none_without_a_dbc_manager(self):
        self.assertIsNone(dbc_hint_for_byte(None, "100", 0))

    def test_none_for_an_unrelated_can_id(self):
        self.assertIsNone(dbc_hint_for_byte(self.mgr, "999", 0))


class VisibleFilterTests(unittest.TestCase):
    def _report_with_same_oscillation_and_min_frames_case(self):
        rows = (
            # ID 100: SAME_OSCILLATION byte -- filterable via ignore_same_oscillation
            [_row(t, "100", v) for t, v in enumerate([1, 2, 3])]
            + [_row(t + 10, "100", v) for t, v in enumerate([3, 2, 1])]
            # ID 300: only 1 frame in window A -- below default min_frames, no len_changed
            + [_row(0.5, "300", 5)]
            + [_row(t + 10, "300", 9) for t in range(5)]
        )
        return build_range_diff_report(
            rows_to_df(rows), TimeRange(start=0.0, end=4.0), TimeRange(start=10.0, end=14.0)
        )

    def test_min_frames_guard_hides_unreliable_byte_diffs(self):
        report = self._report_with_same_oscillation_and_min_frames_case()
        visible = report.visible(DiffOptions())
        self.assertNotIn("300", {item.can_id for item in visible})
        # The raw (unfiltered) report still carries the classification.
        raw_300 = next(i for i in report.ids if i.can_id == "300")
        self.assertTrue(raw_300.byte_diffs)

    def test_visible_reapplies_options_without_rescanning(self):
        report = self._report_with_same_oscillation_and_min_frames_case()
        ids_before = report.ids

        strict = report.visible(DiffOptions(ignore_same_oscillation=True))
        lenient = report.visible(DiffOptions(ignore_same_oscillation=False))

        self.assertNotIn("100", {item.can_id for item in strict})
        self.assertIn("100", {item.can_id for item in lenient})
        self.assertIs(report.ids, ids_before)  # never mutated

    def test_ignore_counters_hides_partial_cycle_counter_byte(self):
        rows = [_row(t, "400", v) for t, v in enumerate(range(10))] + [
            _row(t + 10, "400", v) for t, v in enumerate(range(5, 15))
        ]
        report = build_range_diff_report(
            rows_to_df(rows), TimeRange(start=0.0, end=9.0), TimeRange(start=10.0, end=19.0)
        )
        strict = report.visible(DiffOptions(ignore_counters=True))
        lenient = report.visible(DiffOptions(ignore_counters=False))
        self.assertNotIn("400", {item.can_id for item in strict})
        self.assertIn("400", {item.can_id for item in lenient})

    def test_only_new_territory_keeps_only_that_change_type(self):
        # byte 0: CONST_SHIFT 5 -> 9 ; byte 1: NEW_TERRITORY {1,2,3} -> {1,2,3,4}
        rows = [_row(t, "500", 5, v) for t, v in enumerate([1, 2, 3])] + [
            _row(t + 10, "500", 9, v) for t, v in enumerate([1, 2, 3, 4])
        ]
        report = build_range_diff_report(
            rows_to_df(rows), TimeRange(start=0.0, end=4.0), TimeRange(start=10.0, end=14.0)
        )
        visible = report.visible(
            DiffOptions(only_new_territory=True, ignore_same_oscillation=False, ignore_counters=False)
        )
        item = next(i for i in visible if i.can_id == "500")
        self.assertEqual({d.change_type for d in item.byte_diffs}, {ChangeType.NEW_TERRITORY})

    @unittest.skipUnless(_HAS_SCIPY, "scipy not installed")
    def test_require_significance_hides_a_confident_label_backed_by_too_few_frames(self):
        rows = [_row(t, "800", 5) for t in range(2)] + [_row(t + 10, "800", 9) for t in range(2)]
        report = build_range_diff_report(
            rows_to_df(rows), TimeRange(start=0.0, end=1.0), TimeRange(start=10.0, end=11.0)
        )
        # min_frames=2 isolates the significance filter from the frame-count guard.
        lenient = report.visible(DiffOptions(min_frames=2, require_significance=False))
        strict = report.visible(DiffOptions(min_frames=2, require_significance=True))
        self.assertIn("800", {item.can_id for item in lenient})
        self.assertNotIn("800", {item.can_id for item in strict})

    @unittest.skipUnless(_HAS_SCIPY, "scipy not installed")
    def test_require_significance_keeps_a_well_sampled_shift(self):
        rows = [_row(t, "900", 5) for t in range(20)] + [_row(t + 20, "900", 9) for t in range(20)]
        report = build_range_diff_report(
            rows_to_df(rows), TimeRange(start=0.0, end=19.0), TimeRange(start=20.0, end=39.0)
        )
        visible = report.visible(DiffOptions(require_significance=True))
        self.assertIn("900", {item.can_id for item in visible})

    def test_include_presence_toggle(self):
        rows = [_row(1.0, "600", 5)]  # only in window A
        report = build_range_diff_report(
            rows_to_df(rows), TimeRange(start=0.0, end=4.0), TimeRange(start=10.0, end=14.0)
        )
        self.assertIn("600", {i.can_id for i in report.visible(DiffOptions(include_presence=True))})
        self.assertNotIn("600", {i.can_id for i in report.visible(DiffOptions(include_presence=False))})

    def test_min_frames_guard_clears_byte_diffs_even_when_len_changed(self):
        # Regression: len_changed must not smuggle through the unreliable byte_diffs.
        rows = [_row(1.0, "700", 1, 2, 3, 4)] + [  # 1 frame, LEN=4 -- below default min_frames
            _row(t + 10, "700", 1, 2, 3, 4, 5, 6, 7, 8) for t in range(5)  # LEN=8
        ]
        report = build_range_diff_report(
            rows_to_df(rows), TimeRange(start=0.0, end=4.0), TimeRange(start=10.0, end=14.0)
        )
        item = next(i for i in report.visible(DiffOptions()) if i.can_id == "700")
        self.assertTrue(item.len_changed)
        self.assertEqual(item.byte_diffs, ())


class ExportRangeDiffCsvTests(unittest.TestCase):
    def test_export_writes_a_row_per_visible_byte_diff(self):
        rows = [_row(t, "100", 5) for t in range(3)] + [_row(t + 10, "100", 9) for t in range(3)]
        report = build_range_diff_report(
            rows_to_df(rows), TimeRange(start=0.0, end=4.0), TimeRange(start=10.0, end=14.0)
        )
        items = report.visible(DiffOptions())

        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            export_range_diff_csv(items, path)
            with open(path, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("100", content)
            self.assertIn("const_shift", content)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
