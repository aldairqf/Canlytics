"""Characterization tests for services/log_data.merge_frames."""

from __future__ import annotations

import unittest

import polars as pl

from services.log_data import is_append_in_order, merge_frames


def _df(ts):
    return pl.DataFrame({"TS": [float(t) for t in ts], "ID": ["100"] * len(ts)})


class MergeFramesTests(unittest.TestCase):
    def test_base_none_returns_incoming(self):
        incoming = _df([0.0, 1.0])
        out = merge_frames(None, incoming, normalize=False)
        self.assertEqual(out["TS"].to_list(), [0.0, 1.0])

    def test_empty_base_sorts_an_internally_out_of_order_chunk(self):
        incoming = _df([2.0, 1.0])
        for base in (None, pl.DataFrame()):
            with self.subTest(base=base):
                out = merge_frames(base, incoming, normalize=False)
                self.assertEqual(out["TS"].to_list(), [1.0, 2.0])

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

    def test_out_of_order_chunk_sorts_only_affected_tail(self):
        base = _df([0.0, 1.0, 2.0, 3.0, 4.0])
        incoming = _df([2.5, 1.5, 3.5])
        out = merge_frames(base, incoming, normalize=False, rechunk=False)
        self.assertEqual(out["TS"].to_list(), [0.0, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0])
        self.assertGreater(out.n_chunks(), 1)

    def test_out_of_order_chunk_before_base_sorts_complete_affected_range(self):
        out = merge_frames(_df([2.0, 3.0, 4.0]), _df([0.0, 1.0]), normalize=False, rechunk=False)
        self.assertEqual(out["TS"].to_list(), [0.0, 1.0, 2.0, 3.0, 4.0])

    def test_out_of_order_chunk_preserves_duplicate_rows(self):
        base = pl.DataFrame({"TS": [0.0, 2.0, 3.0], "ID": ["a", "b", "c"]})
        incoming = pl.DataFrame({"TS": [2.0, 1.0], "ID": ["d", "e"]})
        out = merge_frames(base, incoming, normalize=False, rechunk=False)
        self.assertEqual(out.height, 5)
        self.assertEqual(out["TS"].to_list(), [0.0, 1.0, 2.0, 2.0, 3.0])

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

    def test_out_of_order_respects_rechunk_false(self):
        out = merge_frames(_df([0.0, 2.0]), _df([1.0]), normalize=False, rechunk=False)
        self.assertGreater(out.n_chunks(), 1)
        self.assertEqual(out["TS"].to_list(), [0.0, 1.0, 2.0])


class IsAppendInOrderTests(unittest.TestCase):
    def test_empty_base_is_an_ordered_append(self):
        self.assertTrue(is_append_in_order(None, _df([1.0])))
        self.assertFalse(is_append_in_order(None, _df([2.0, 1.0])))

    def test_incoming_starting_at_or_after_last_timestamp_is_ordered(self):
        self.assertTrue(is_append_in_order(_df([1.0, 2.0]), _df([2.0, 3.0])))

    def test_incoming_before_last_timestamp_is_not_ordered(self):
        self.assertFalse(is_append_in_order(_df([1.0, 3.0]), _df([2.0])))

    def test_incoming_rows_must_be_ordered_internally(self):
        self.assertFalse(is_append_in_order(_df([1.0]), _df([2.0, 0.0])))

    def test_normalized_incoming_is_compared_in_base_time_domain(self):
        self.assertTrue(is_append_in_order(_df([-1.0, -0.5]), _df([0.0]), normalize=True))
        self.assertFalse(is_append_in_order(_df([0.0, 1.0]), _df([0.5]), normalize=True))


if __name__ == "__main__":
    unittest.main()
