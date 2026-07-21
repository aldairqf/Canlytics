"""Characterization tests for RangeDiffViewModel's thin Qt-adapter behavior:
resetting A/B bands off the loaded log's extremes, and re-emitting a filtered
view from the already-computed report when options change (no re-scan).
"""

from __future__ import annotations

import sys
import unittest

from PySide6.QtWidgets import QApplication

from services.can_data_parser import frame_dict, rows_to_df
from services.range_diff import DiffOptions, RangeDiffReport, TimeRange, build_range_diff_report
from viewmodels.range_diff_viewmodel import RangeDiffViewModel

_app: QApplication | None = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


def _row(ts: float, can_id: str, byte0: int) -> dict:
    return frame_dict(ts=ts, bus="b", can_id=can_id, data=bytes([byte0]))


class RangeDiffViewModelTests(unittest.TestCase):
    def setUp(self):
        self.vm = RangeDiffViewModel(dbc_manager=None)

    def test_reset_dataframe_resets_ranges_to_log_extremes(self):
        df = rows_to_df([_row(float(ts), "100", 1) for ts in range(0, 101, 10)])
        ranges = []
        self.vm.ranges_changed.connect(lambda pair: ranges.append(pair))

        self.vm.reset_dataframe(df)

        self.assertEqual(len(ranges), 1)
        self.assertEqual(self.vm.range_a.start, 0.0)
        self.assertEqual(self.vm.range_b.end, 100.0)
        self.assertLess(self.vm.range_a.end, self.vm.range_b.start)

    def test_reset_dataframe_empty_resets_ranges_to_zero(self):
        self.vm.reset_dataframe(rows_to_df([]))
        self.assertEqual(self.vm.range_a, TimeRange(start=0.0, end=0.0))
        self.assertEqual(self.vm.range_b, TimeRange(start=0.0, end=0.0))

    def test_set_dataframe_does_not_touch_ranges_or_density(self):
        self.vm.reset_dataframe(rows_to_df([_row(float(ts), "100", 1) for ts in range(0, 101, 10)]))
        self.vm.set_range_a(3.0, 4.0)
        self.vm.set_range_b(50.0, 60.0)

        density_events = []
        ranges_events = []
        self.vm.density_changed.connect(lambda payload: density_events.append(payload))
        self.vm.ranges_changed.connect(lambda payload: ranges_events.append(payload))

        self.vm.set_dataframe(rows_to_df([_row(float(ts), "100", 1) for ts in range(0, 201, 10)]))

        self.assertEqual(density_events, [])
        self.assertEqual(ranges_events, [])
        self.assertEqual(self.vm.range_a, TimeRange(start=3.0, end=4.0))
        self.assertEqual(self.vm.range_b, TimeRange(start=50.0, end=60.0))

    def test_options_property_reflects_set_options(self):
        self.assertEqual(self.vm.options, DiffOptions())
        opts = DiffOptions(require_significance=True, min_frames=42)
        self.vm.set_options(opts)
        self.assertEqual(self.vm.options, opts)

    def test_set_range_a_and_b_emit_ranges_changed(self):
        seen = []
        self.vm.ranges_changed.connect(lambda pair: seen.append(pair))
        self.vm.set_range_a(1.0, 2.0)
        self.vm.set_range_b(8.0, 9.0)
        self.assertEqual(self.vm.range_a, TimeRange(start=1.0, end=2.0))
        self.assertEqual(self.vm.range_b, TimeRange(start=8.0, end=9.0))
        self.assertEqual(len(seen), 2)

    def _sample_report(self) -> RangeDiffReport:
        rows = (
            [_row(t, "100", 5) for t in range(3)]
            + [_row(t + 10, "100", 9) for t in range(3)]
        )
        return build_range_diff_report(
            rows_to_df(rows), TimeRange(0.0, 4.0), TimeRange(10.0, 14.0)
        )

    def test_on_finished_stores_report_and_emits_visible_for_current_options(self):
        seen = []
        self.vm.visible_changed.connect(lambda items: seen.append(items))
        report = self._sample_report()

        self.vm._on_finished(report)

        self.assertIs(self.vm.report, report)
        self.assertEqual(len(seen), 1)
        self.assertEqual({item.can_id for item in seen[0]}, {"100"})

    def test_set_options_re_filters_the_existing_report_without_rescanning(self):
        report = self._sample_report()
        self.vm._on_finished(report)

        seen = []
        self.vm.visible_changed.connect(lambda items: seen.append(items))
        self.vm.set_options(DiffOptions(min_frames=100))  # too strict -- hides the id

        self.assertIs(self.vm.report, report)  # same object, no new scan happened
        self.assertEqual(seen, [[]])

    def test_emit_current_state_repushes_density_and_ranges(self):
        # A window opened after the log loaded must still get density + ranges,
        # else its timeline stays empty and the A/B cursors can't be dragged.
        self.vm.reset_dataframe(rows_to_df([_row(float(ts), "100", ts % 5) for ts in range(0, 101, 10)]))

        density = []
        ranges = []
        self.vm.density_changed.connect(lambda payload: density.append(payload))
        self.vm.ranges_changed.connect(lambda payload: ranges.append(payload))

        self.vm.emit_current_state()

        self.assertEqual(len(density), 1)
        edges, counts = density[0]
        self.assertTrue(counts)
        self.assertEqual(ranges[-1], (self.vm.range_a, self.vm.range_b))
        self.assertNotEqual(self.vm.range_a, self.vm.range_b)

    def test_capture_live_baseline_activates_live_and_pushes_an_initial_report(self):
        self.vm.reset_dataframe(rows_to_df([_row(float(ts), "100", 1) for ts in range(3)]))
        live_events = []
        reports = []
        self.vm.live_active_changed.connect(lambda v: live_events.append(v))
        self.vm.report_changed.connect(lambda r: reports.append(r))

        self.vm.capture_live_baseline()

        self.assertTrue(self.vm.is_live)
        self.assertEqual(live_events, [True])
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].ids[0].presence, "only_a")  # nothing fed into B yet

    def test_set_dataframe_feeds_live_accumulators_when_active(self):
        self.vm.reset_dataframe(rows_to_df([_row(float(ts), "100", 1) for ts in range(3)]))
        self.vm.capture_live_baseline()

        grown = rows_to_df(
            [_row(float(ts), "100", 1) for ts in range(3)] + [_row(float(ts), "100", 9) for ts in range(3, 6)]
        )
        self.vm.set_dataframe(grown)
        self.vm._live_tick()

        report = self.vm.report
        self.assertEqual(report.ids[0].presence, "both")
        self.assertTrue(any(d.change_type.value != "unchanged" for d in report.ids[0].byte_diffs))

    def test_stop_live_stops_timer_and_emits_false(self):
        self.vm.reset_dataframe(rows_to_df([_row(float(ts), "100", 1) for ts in range(3)]))
        self.vm.capture_live_baseline()

        live_events = []
        self.vm.live_active_changed.connect(lambda v: live_events.append(v))
        self.vm.stop_live()

        self.assertFalse(self.vm.is_live)
        self.assertEqual(live_events, [False])

    def test_reset_dataframe_stops_an_active_live_session(self):
        self.vm.reset_dataframe(rows_to_df([_row(float(ts), "100", 1) for ts in range(3)]))
        self.vm.capture_live_baseline()

        self.vm.reset_dataframe(rows_to_df([_row(float(ts), "200", 1) for ts in range(3)]))

        self.assertFalse(self.vm.is_live)

    def test_emit_current_state_repushes_report_changed_so_the_tree_can_rebuild(self):
        # B-15: the view builds its full (unfiltered) tree off report_changed and
        # only toggles visibility off visible_changed -- a reopened window needs
        # report_changed too, not just visible_changed, or its tree stays empty.
        report = self._sample_report()
        self.vm._on_finished(report)

        reports_seen = []
        self.vm.report_changed.connect(lambda r: reports_seen.append(r))
        self.vm.emit_current_state()

        self.assertEqual(reports_seen, [report])

    def test_emit_current_state_does_not_emit_report_changed_without_a_report(self):
        reports_seen = []
        self.vm.report_changed.connect(lambda r: reports_seen.append(r))
        self.vm.emit_current_state()
        self.assertEqual(reports_seen, [])

    def test_cancel_and_wait_batch_is_a_safe_noop_when_nothing_is_running(self):
        self.vm.cancel_and_wait_batch()  # must not raise

    def test_cancel_and_wait_batch_does_not_touch_an_active_live_session(self):
        self.vm.reset_dataframe(rows_to_df([_row(float(ts), "100", 1) for ts in range(3)]))
        self.vm.capture_live_baseline()

        self.vm.cancel_and_wait_batch()

        self.assertTrue(self.vm.is_live)


if __name__ == "__main__":
    unittest.main()
