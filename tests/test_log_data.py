"""Characterization tests for services/log_data.merge_frames."""

from __future__ import annotations

import unittest

import polars as pl

from services.log_data import merge_frames


def _df(ts):
    return pl.DataFrame({"TS": [float(t) for t in ts], "ID": ["100"] * len(ts)})


class MergeFramesTests(unittest.TestCase):
    def test_base_none_returns_incoming(self):
        incoming = _df([0.0, 1.0])
        out = merge_frames(None, incoming, normalize=False)
        self.assertEqual(out["TS"].to_list(), [0.0, 1.0])

    def test_incoming_empty_returns_base(self):
        base = _df([0.0, 1.0])
        out = merge_frames(base, pl.DataFrame(), normalize=False)
        self.assertEqual(out["TS"].to_list(), [0.0, 1.0])

    def test_both_empty_returns_empty(self):
        out = merge_frames(None, pl.DataFrame(), normalize=False)
        self.assertTrue(out.is_empty())

    def test_in_order_concat_preserves_order(self):
        out = merge_frames(_df([0.0, 1.0]), _df([2.0, 3.0]), normalize=False)
        self.assertEqual(out["TS"].to_list(), [0.0, 1.0, 2.0, 3.0])

    def test_out_of_order_is_sorted_by_ts(self):
        out = merge_frames(_df([0.0, 2.0]), _df([1.0]), normalize=False)
        self.assertEqual(out["TS"].to_list(), [0.0, 1.0, 2.0])

    def test_normalize_shifts_incoming_by_base_first_ts(self):
        # incoming shifted by base-first (10) -> [2,3]; result is then sorted.
        out = merge_frames(_df([10.0, 11.0]), _df([12.0, 13.0]), normalize=True)
        self.assertEqual(out["TS"].to_list(), [2.0, 3.0, 10.0, 11.0])

    def test_rechunk_false_skips_the_copy_on_in_order_append(self):
        out = merge_frames(_df([0.0, 1.0]), _df([2.0, 3.0]), normalize=False, rechunk=False)
        self.assertGreater(out.n_chunks(), 1)
        self.assertEqual(out["TS"].to_list(), [0.0, 1.0, 2.0, 3.0])

    def test_rechunk_true_is_default_and_consolidates(self):
        out = merge_frames(_df([0.0, 1.0]), _df([2.0, 3.0]), normalize=False)
        self.assertEqual(out.n_chunks(), 1)

    def test_out_of_order_always_rechunks_regardless_of_flag(self):
        out = merge_frames(_df([0.0, 2.0]), _df([1.0]), normalize=False, rechunk=False)
        self.assertEqual(out.n_chunks(), 1)
        self.assertEqual(out["TS"].to_list(), [0.0, 1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
