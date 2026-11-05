from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

import numpy as np
import polars as pl
from unittest.mock import Mock, patch

from services.candidate_interpretations import CandidateItem
from services.reference_correlation import (
    CorrelationCanceled,
    ReferenceSource,
    _lag_grid,
    correlate_reference,
    event_marker_reference,
    load_reference_csv,
    resolve_reference_series,
)


class ReferenceCorrelationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.times = np.arange(0.0, 60.0, 0.1)
        self.candidate = np.sin(self.times * 0.71) + 0.3 * np.sin(self.times * 0.17) + self.times * 0.002

    def test_finds_positive_lag_and_recovers_scale_and_offset(self) -> None:
        lag = 0.4
        reference = 4.0 * np.interp(self.times - lag, self.times, self.candidate) + 7.0

        result = correlate_reference(
            self.times,
            self.candidate,
            self.times,
            reference,
            method="pearson",
            window_seconds=10.0,
            max_lag_seconds=1.0,
            lag_step_seconds=0.1,
            min_samples_per_window=20,
        )

        self.assertAlmostEqual(result.lag_seconds, lag, places=6)
        self.assertGreater(result.coefficient, 0.99)
        self.assertAlmostEqual(result.scale, 4.0, places=2)
        self.assertAlmostEqual(result.offset, 7.0, places=2)
        self.assertEqual(len(result.windows), 6)

    def test_finds_negative_lag_with_spearman_rank_correlation(self) -> None:
        lag = -0.3
        shifted = np.interp(self.times - lag, self.times, self.candidate)
        reference = np.round(shifted * 3.0)  # Ties exercise average ranks.

        result = correlate_reference(
            self.times,
            self.candidate,
            self.times,
            reference,
            method="spearman",
            window_seconds=12.0,
            max_lag_seconds=0.6,
            lag_step_seconds=0.1,
            min_samples_per_window=20,
        )

        self.assertAlmostEqual(result.lag_seconds, lag, places=6)
        self.assertGreater(result.coefficient, 0.95)
        self.assertEqual(result.method, "spearman")

    def test_accepts_unsorted_and_duplicate_timestamps_and_ignores_nonfinite_points(self) -> None:
        times = np.array([0.0, 1.0, 1.0, 2.0, 3.0, np.nan])
        values = np.array([0.0, 2.0, 2.0, 4.0, 6.0, 8.0])

        result = correlate_reference(
            times[::-1],
            values[::-1],
            times,
            values,
            method="pearson",
            window_seconds=5.0,
            max_lag_seconds=0.0,
            min_samples_per_window=3,
        )

        self.assertGreater(result.coefficient, 0.999)
        self.assertAlmostEqual(result.scale, 1.0)
        self.assertAlmostEqual(result.offset, 0.0)
        self.assertEqual(result.samples, 4)

    def test_discontinuous_reference_does_not_interpolate_through_large_gaps(self) -> None:
        times = np.arange(0.0, 30.0, 1.0)
        values = np.sin(times * 0.31) + times * 0.02
        reference_mask = (times <= 9.0) | (times >= 20.0)
        result = correlate_reference(
            times, values, times[reference_mask], 3.0 * values[reference_mask] + 5.0,
            method="pearson", window_seconds=5.0, max_lag_seconds=0.0,
            min_samples_per_window=3,
        )

        self.assertEqual(result.samples, int(reference_mask.sum()))
        self.assertAlmostEqual(result.scale, 3.0, places=3)
        self.assertAlmostEqual(result.offset, 5.0, places=3)

    def test_rejects_invalid_options_and_uninformative_series(self) -> None:
        with self.assertRaisesRegex(ValueError, "method"):
            correlate_reference(self.times, self.candidate, self.times, self.candidate, method="kendall")
        with self.assertRaisesRegex(ValueError, "window_seconds"):
            correlate_reference(self.times, self.candidate, self.times, self.candidate, window_seconds=0)
        with self.assertRaisesRegex(ValueError, "no lag"):
            correlate_reference(
                self.times,
                np.ones_like(self.candidate),
                self.times,
                self.candidate,
                window_seconds=10.0,
                min_samples_per_window=20,
            )

    def test_loads_headered_and_headerless_csv_reference_series(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            headered = Path(directory) / "headered.csv"
            headered.write_text("timestamp,value\n0,1\n1,2\n2,3\n", encoding="utf-8")
            headerless = Path(directory) / "headerless.csv"
            headerless.write_text("0,4\n1,5\n2,6\n", encoding="utf-8")

            first = load_reference_csv(headered)
            second = load_reference_csv(headerless)

        self.assertEqual(first.timestamps, (0.0, 1.0, 2.0))
        self.assertEqual(first.values, (1.0, 2.0, 3.0))
        self.assertEqual(second.values, (4.0, 5.0, 6.0))

    def test_samples_named_event_markers_as_a_binary_time_reference(self) -> None:
        markers = (
            {"sequence": 1, "name": "lift", "timestamp": 1.0, "state": "ON"},
            {"sequence": 2, "name": "lift", "timestamp": 3.0, "state": "OFF"},
            {"sequence": 3, "name": "other", "timestamp": 2.0, "state": "ON"},
        )

        series = event_marker_reference((3.5, 0.0, 2.0, 1.0), markers, "lift")

        self.assertEqual(series.values, (0.0, 0.0, 1.0, 1.0))

    def test_resolves_another_candidate_without_touching_the_dataframe(self) -> None:
        candidate = CandidateItem(
            label="candidate A", can_id="123", frame_len=8, mux_label="", mux_start=0,
            mux_bytes=0, mux_value=None, start_bit=0, signal_length=8,
            byte_order="LittleEndian", value_type="Unsigned", frames=3, changes=2,
            distinct_values=3, score=1.0, min_value=1.0, max_value=3.0,
            sample_values=("1", "2", "3"), timestamps=(0.0, 1.0, 2.0),
            values=(1.0, 2.0, 3.0),
        )
        resolved = resolve_reference_series(
            ReferenceSource(kind="candidate", name=candidate.label, candidate_label=candidate.label),
            candidate_times=(0.0, 1.0, 2.0), dataframe=pl.DataFrame(),
            dbc_manager=Mock(), candidates=(candidate,), markers=(),
        )

        self.assertEqual(resolved.values, candidate.values)

    def test_decodes_a_selected_dbc_signal_with_its_frame_selector(self) -> None:
        manager = Mock()
        manager.get_signal_definition.return_value = {
            "name": "speed", "can_id": "123", "start_bit": 8, "length": 16,
            "le": True, "scale": 0.1, "offset": 1.0, "mux_start": 0,
            "mux_bytes": 0, "mux_value": None, "type_data": "uint",
            "id_match": "exact", "pgn": None,
        }
        source = ReferenceSource(
            kind="dbc", name="speed", dbc_name="vehicle", message_name="Status",
            signal_name="speed",
        )
        with patch("services.can_decoder.decode_signal", return_value=([1.0, 2.0], [4.0, 5.0])) as decode:
            resolved = resolve_reference_series(
                source, candidate_times=(1.0, 2.0), dataframe=pl.DataFrame(),
                dbc_manager=manager, candidates=(), markers=(),
            )

        self.assertEqual(resolved.values, (4.0, 5.0))
        signal, selector = decode.call_args.args[1:]
        self.assertEqual(signal.name, "speed")
        self.assertEqual((selector.selected_id, selector.mode), ("123", "exact"))

    def test_reports_progress_for_each_lag_and_honors_cancellation(self) -> None:
        progress: list[tuple[int, int]] = []
        correlate_reference(
            self.times, self.candidate, self.times, self.candidate,
            window_seconds=10.0, max_lag_seconds=0.2, lag_step_seconds=0.1,
            min_samples_per_window=10, on_progress=lambda done, total: progress.append((done, total)),
        )
        self.assertEqual(progress[0], (1, 5))
        self.assertEqual(progress[-1], (5, 5))
        self.assertEqual(tuple(_lag_grid(0.7, 0.3)), (-0.7, -0.6, -0.3, 0.0, 0.3, 0.6, 0.7))
        with self.assertRaises(CorrelationCanceled):
            correlate_reference(
                self.times, self.candidate, self.times, self.candidate,
                window_seconds=10.0, max_lag_seconds=0.2, lag_step_seconds=0.1,
                should_cancel=lambda: True,
            )


if __name__ == "__main__":
    unittest.main()
