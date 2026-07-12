"""Characterization tests for services/decoded_signal_cache.py."""

from __future__ import annotations

import unittest

import numpy as np

from services.decoded_signal_cache import DecodedSignalCache


class DecodedSignalCacheTests(unittest.TestCase):
    def test_get_missing_key_returns_none(self):
        cache = DecodedSignalCache()
        self.assertIsNone(cache.get(("a",)))

    def test_set_full_then_get_roundtrips(self):
        cache = DecodedSignalCache()
        ts = np.array([0.0, 1.0])
        y = np.array([10, 20])
        cache.set_full(("sig",), ts, y)
        got_ts, got_y = cache.get(("sig",))
        np.testing.assert_array_equal(got_ts, ts)
        np.testing.assert_array_equal(got_y, y)

    def test_extend_appends_onto_existing(self):
        cache = DecodedSignalCache()
        cache.set_full(("sig",), np.array([0.0, 1.0]), np.array([10, 20]))
        cache.extend(("sig",), np.array([2.0, 3.0]), np.array([30, 40]))
        ts, y = cache.get(("sig",))
        np.testing.assert_array_equal(ts, [0.0, 1.0, 2.0, 3.0])
        np.testing.assert_array_equal(y, [10, 20, 30, 40])

    def test_extend_with_no_prior_entry_seeds_fresh(self):
        cache = DecodedSignalCache()
        cache.extend(("sig",), np.array([5.0]), np.array([99]))
        ts, y = cache.get(("sig",))
        np.testing.assert_array_equal(ts, [5.0])
        np.testing.assert_array_equal(y, [99])

    def test_extend_with_empty_new_data_is_noop(self):
        cache = DecodedSignalCache()
        cache.set_full(("sig",), np.array([0.0]), np.array([1]))
        cache.extend(("sig",), np.array([]), np.array([]))
        ts, y = cache.get(("sig",))
        np.testing.assert_array_equal(ts, [0.0])
        np.testing.assert_array_equal(y, [1])

    def test_incremental_extend_matches_one_shot_set(self):
        cache_incremental = DecodedSignalCache()
        cache_incremental.extend(("sig",), np.array([0.0, 1.0]), np.array([1, 2]))
        cache_incremental.extend(("sig",), np.array([2.0]), np.array([3]))
        cache_incremental.extend(("sig",), np.array([3.0, 4.0]), np.array([4, 5]))

        cache_full = DecodedSignalCache()
        cache_full.set_full(("sig",), np.array([0.0, 1.0, 2.0, 3.0, 4.0]), np.array([1, 2, 3, 4, 5]))

        inc_ts, inc_y = cache_incremental.get(("sig",))
        full_ts, full_y = cache_full.get(("sig",))
        np.testing.assert_array_equal(inc_ts, full_ts)
        np.testing.assert_array_equal(inc_y, full_y)

    def test_clear_removes_all_entries(self):
        cache = DecodedSignalCache()
        cache.set_full(("sig",), np.array([0.0]), np.array([1]))
        cache.clear()
        self.assertIsNone(cache.get(("sig",)))
        self.assertEqual(len(cache), 0)

    def test_contains(self):
        cache = DecodedSignalCache()
        cache.set_full(("sig",), np.array([0.0]), np.array([1]))
        self.assertIn(("sig",), cache)
        self.assertNotIn(("other",), cache)

    def test_len(self):
        cache = DecodedSignalCache()
        cache.set_full(("a",), np.array([0.0]), np.array([1]))
        cache.set_full(("b",), np.array([0.0]), np.array([1]))
        self.assertEqual(len(cache), 2)


if __name__ == "__main__":
    unittest.main()
