"""Characterization tests for services/hmi_video_processor.build_plot_series.

Was viewmodels/hmi_video_extractor_viewmodel.py's private plot_series body --
moved here since it's pure aggregation with no Qt dependency.
"""

from __future__ import annotations

import unittest

from config.defaults import SIGNAL_COLOR_PALETTE
from models.hmi_video_models import HmiExtractionRecord
from services.hmi_video_processor import build_plot_series


def _record(variable, value, *, ts=0.0, confidence=1.0, frame=0, roi_id="r1"):
    return HmiExtractionRecord(
        timestamp=ts,
        frame=frame,
        variable=variable,
        value=value,
        unit="",
        confidence=confidence,
        roi_id=roi_id,
        method="ocr",
    )


class BuildPlotSeriesTests(unittest.TestCase):
    def test_one_series_per_variable_sorted_by_name(self):
        results = [
            _record("Speed", 10.0, ts=0.0),
            _record("Speed", 20.0, ts=1.0),
            _record("RPM", 1000.0, ts=0.0),
        ]
        series = build_plot_series(results)
        self.assertEqual([s["label"] for s in series], ["RPM", "Speed"])

    def test_series_carries_x_y_and_confidence_in_arrival_order(self):
        results = [_record("Speed", 10.0, ts=0.0, confidence=0.9), _record("Speed", 20.0, ts=1.0, confidence=0.8)]
        series = build_plot_series(results)
        speed = series[0]
        self.assertEqual(speed["x"], [0.0, 1.0])
        self.assertEqual(speed["y"], [10.0, 20.0])
        self.assertEqual(speed["confidence"], [0.9, 0.8])

    def test_records_with_no_value_are_excluded(self):
        results = [_record("Speed", None), _record("Speed", 10.0)]
        series = build_plot_series(results)
        self.assertEqual(series[0]["y"], [10.0])

    def test_records_below_min_confidence_are_excluded(self):
        results = [_record("Speed", 10.0, confidence=0.4), _record("Speed", 20.0, confidence=0.9)]
        series = build_plot_series(results, min_confidence=0.5)
        self.assertEqual(series[0]["y"], [20.0])

    def test_variable_excluded_entirely_when_all_its_records_are_filtered(self):
        results = [_record("Speed", None), _record("RPM", 1000.0)]
        series = build_plot_series(results)
        self.assertEqual([s["label"] for s in series], ["RPM"])

    def test_colors_assigned_round_robin_by_sorted_index(self):
        n = len(SIGNAL_COLOR_PALETTE)
        names = [f"Var{i}" for i in range(n + 2)]  # more than the shared palette
        results = [_record(name, 1.0) for name in names]
        series = build_plot_series(results)
        colors = [s["color"] for s in series]
        self.assertEqual(colors[0], colors[n])  # wraps around after the palette
        self.assertEqual(len(set(colors[:n])), n)  # first n are all distinct

    def test_empty_results_returns_empty_list(self):
        self.assertEqual(build_plot_series([]), [])


if __name__ == "__main__":
    unittest.main()
