from __future__ import annotations

import unittest

from services.measurement_status import FrameRateTracker, memory_warning_threshold_bytes


class FrameRateTrackerTests(unittest.TestCase):
    def test_sums_chunks_within_window(self):
        tracker = FrameRateTracker(window_seconds=2)
        tracker.add(120, now=1)
        tracker.add(80, now=2)

        self.assertEqual(tracker.frames_per_second(now=2), 100)

    def test_drops_samples_older_than_window(self):
        tracker = FrameRateTracker(window_seconds=1)
        tracker.add(500, now=1)
        tracker.add(100, now=1.5)

        self.assertEqual(tracker.frames_per_second(now=2.1), 100)

    def test_ignores_empty_chunks(self):
        tracker = FrameRateTracker(window_seconds=1)
        tracker.add(0, now=1)

        self.assertEqual(tracker.frames_per_second(now=1), 0)


class MemoryWarningThresholdTests(unittest.TestCase):
    def test_uses_lower_of_absolute_and_system_limits(self):
        self.assertEqual(memory_warning_threshold_bytes(2 * 1024**3), int(2 * 1024**3 * 0.6))
        self.assertEqual(memory_warning_threshold_bytes(64 * 1024**3), 2 * 1024**3)

    def test_never_returns_zero(self):
        self.assertEqual(memory_warning_threshold_bytes(1, absolute_limit_bytes=0), 1)


if __name__ == "__main__":
    unittest.main()
