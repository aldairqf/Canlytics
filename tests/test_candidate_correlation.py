from __future__ import annotations

import unittest

import numpy as np

from services.candidate_correlation import (
    CandidateCorrelationCanceled,
    cluster_correlated_candidates,
)
from services.candidate_interpretations import CandidateItem


def _candidate(
    label: str,
    can_id: str,
    timestamps: np.ndarray,
    values: np.ndarray,
    *,
    score: float = 0.5,
    start_bit: int = 0,
    signal_length: int = 8,
    mux_label: str = "all",
) -> CandidateItem:
    return CandidateItem(
        label=label,
        can_id=can_id,
        frame_len=8,
        mux_label=mux_label,
        mux_start=0,
        mux_bytes=0,
        mux_value=None,
        start_bit=start_bit,
        signal_length=signal_length,
        byte_order="LittleEndian",
        value_type="Unsigned",
        frames=len(values),
        changes=len(values) - 1,
        distinct_values=len(set(values.tolist())),
        score=score,
        min_value=float(np.min(values)) if values.size else None,
        max_value=float(np.max(values)) if values.size else None,
        sample_values=(),
        timestamps=tuple(float(value) for value in timestamps),
        values=tuple(float(value) for value in values),
    )


class CandidateCorrelationTests(unittest.TestCase):
    def test_clusters_positive_correlations_and_keeps_highest_score_representative(self) -> None:
        timestamps = np.arange(40, dtype=float) * 0.1
        base = np.linspace(0.0, 10.0, timestamps.size)
        candidates = [
            _candidate("low", "100", timestamps, base, score=0.4),
            _candidate("high", "200", timestamps, base * 2.0 + 5.0, score=0.9),
            _candidate("other", "300", timestamps, np.sin(np.arange(40)), score=0.3),
        ]
        progress: list[tuple[int, int]] = []
        clusters = cluster_correlated_candidates(
            candidates,
            threshold=0.99,
            min_samples=12,
            max_points=12,
            on_progress=lambda done, total: progress.append((done, total)),
        )
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].representative.label, "high")
        self.assertEqual(clusters[0].members[0].item.label, "low")
        self.assertAlmostEqual(clusters[0].members[0].coefficient, 1.0)
        self.assertEqual(clusters[0].members[0].samples, 12)
        self.assertEqual(progress[-1], (6, 6))

    def test_clusters_negative_correlation(self) -> None:
        timestamps = np.arange(20, dtype=float)
        values = np.arange(20, dtype=float)
        clusters = cluster_correlated_candidates(
            [_candidate("up", "100", timestamps, values), _candidate("down", "200", timestamps, -values)],
            threshold=0.95,
            min_samples=12,
        )
        self.assertEqual(len(clusters), 1)
        self.assertAlmostEqual(clusters[0].members[0].coefficient, -1.0)

    def test_aligns_asynchronous_series_and_does_not_bridge_large_gaps(self) -> None:
        left_times = np.concatenate((np.arange(12.0), np.arange(100.0, 112.0)))
        right_times = np.arange(112.0)
        left_values = np.concatenate((np.arange(12.0), np.arange(12.0, 24.0)))
        right_values = np.arange(112.0)
        clusters = cluster_correlated_candidates(
            [
                _candidate("sparse", "100", left_times, left_values),
                _candidate("dense", "200", right_times, right_values),
            ],
            threshold=0.99,
            min_samples=12,
        )
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].members[0].samples, 24)

    def test_downsampling_preserves_original_cadence_for_large_gap_detection(self) -> None:
        timestamps = np.delete(np.arange(1200, dtype=float), np.arange(600, 605))
        values = timestamps.copy()
        clusters = cluster_correlated_candidates(
            [
                _candidate("sparse", "100", timestamps, values),
                _candidate("dense", "200", np.arange(1200, dtype=float), np.arange(1200, dtype=float)),
            ],
            threshold=0.99,
            min_samples=12,
            max_points=500,
        )
        self.assertEqual(len(clusters), 1)
        self.assertLess(clusters[0].members[0].samples, 500)

    def test_skips_constant_insufficient_and_overlapping_same_message_candidates(self) -> None:
        timestamps = np.arange(20, dtype=float)
        values = np.arange(20, dtype=float)
        constant = _candidate("constant", "200", timestamps, np.ones(20))
        short = _candidate("short", "300", timestamps[:5], values[:5])
        overlap = _candidate("overlap", "100", timestamps, values * 2.0, start_bit=4)
        base = _candidate("base", "100", timestamps, values, start_bit=0)
        clusters = cluster_correlated_candidates(
            [base, overlap, constant, short], threshold=0.95, min_samples=12
        )
        self.assertEqual(clusters, [])

    def test_non_overlapping_fields_of_same_message_can_be_related(self) -> None:
        timestamps = np.arange(20, dtype=float)
        values = np.arange(20, dtype=float)
        clusters = cluster_correlated_candidates(
            [
                _candidate("low byte", "100", timestamps, values, start_bit=0),
                _candidate("high byte", "100", timestamps, values * 10.0, start_bit=8),
            ],
            threshold=0.95,
            min_samples=12,
        )
        self.assertEqual(len(clusters), 1)

    def test_does_not_compare_mutually_exclusive_mux_cases(self) -> None:
        timestamps = np.arange(20, dtype=float)
        values = np.arange(20, dtype=float)
        clusters = cluster_correlated_candidates(
            [
                _candidate("mux A", "100", timestamps, values, mux_label="A"),
                _candidate("mux B", "100", timestamps, values * 2.0, mux_label="B"),
            ],
            threshold=0.95,
            min_samples=12,
        )
        self.assertEqual(clusters, [])

    def test_cancellation_is_checked_during_pair_comparisons(self) -> None:
        timestamps = np.arange(20, dtype=float)
        values = np.arange(20, dtype=float)
        checks = 0

        def should_cancel() -> bool:
            nonlocal checks
            checks += 1
            return checks > 2

        with self.assertRaises(CandidateCorrelationCanceled):
            cluster_correlated_candidates(
                [
                    _candidate("a", "100", timestamps, values),
                    _candidate("b", "200", timestamps, values),
                    _candidate("c", "300", timestamps, values),
                ],
                should_cancel=should_cancel,
            )

    def test_rejects_invalid_threshold_and_sample_limits(self) -> None:
        with self.assertRaises(ValueError):
            cluster_correlated_candidates([], threshold=0.0)
        with self.assertRaises(ValueError):
            cluster_correlated_candidates([], min_samples=2)


if __name__ == "__main__":
    unittest.main()
