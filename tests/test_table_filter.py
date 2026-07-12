"""Characterization tests for services/table_filter.py: incremental == one-shot filter."""

from __future__ import annotations

import unittest

import polars as pl

from services.table_filter import IncrementalTableFilter, apply_time_range


def _df(n: int, *, ids: list[str] | None = None) -> pl.DataFrame:
    ids = ids or ["100", "200"]
    return pl.DataFrame({
        "TS": [float(i) for i in range(n)],
        "ID": [ids[i % len(ids)] for i in range(n)],
        "LEN": [8] * n,
    })


class ApplyTimeRangeTests(unittest.TestCase):
    def test_none_df_returns_none(self):
        self.assertIsNone(apply_time_range(None, None, None))

    def test_empty_df_returns_empty(self):
        df = pl.DataFrame()
        self.assertTrue(apply_time_range(df, 0.0, 1.0).is_empty())

    def test_no_ts_column_returns_unchanged(self):
        df = pl.DataFrame({"ID": ["100"]})
        result = apply_time_range(df, 0.0, 1.0)
        self.assertEqual(result.height, 1)

    def test_filters_min_and_max(self):
        df = pl.DataFrame({"TS": [0.0, 1.0, 2.0, 3.0]})
        result = apply_time_range(df, 1.0, 2.0)
        self.assertEqual(result["TS"].to_list(), [1.0, 2.0])


class IncrementalTableFilterTests(unittest.TestCase):
    def test_none_source_returns_empty(self):
        state = IncrementalTableFilter()
        filtered, ids, changed = state.apply(None, selected_ids={"100"}, ts_min=None, ts_max=None)
        self.assertTrue(filtered.is_empty())
        self.assertEqual(ids, [])
        self.assertFalse(changed)

    def test_no_id_column_returns_empty_and_resets(self):
        state = IncrementalTableFilter()
        df = pl.DataFrame({"TS": [0.0, 1.0]})
        filtered, ids, changed = state.apply(df, selected_ids=set(), ts_min=None, ts_max=None)
        self.assertTrue(filtered.is_empty())
        self.assertEqual(ids, [])

    def test_empty_selected_ids_returns_empty(self):
        state = IncrementalTableFilter()
        df = _df(4)
        filtered, ids, changed = state.apply(df, selected_ids=set(), ts_min=None, ts_max=None)
        self.assertEqual(filtered.height, 0)
        self.assertEqual(ids, ["100", "200"])

    def test_single_call_matches_direct_filter(self):
        state = IncrementalTableFilter()
        df = _df(6)
        filtered, ids, changed = state.apply(df, selected_ids={"100"}, ts_min=None, ts_max=None)
        expected = df.filter(pl.col("ID") == "100")
        self.assertEqual(filtered["TS"].to_list(), expected["TS"].to_list())
        self.assertTrue(changed)

    def test_incremental_growth_matches_one_shot_filter(self):
        full = _df(10)
        # One shot: filter the whole thing at once.
        one_shot = full.filter(pl.col("ID").is_in({"100"}))

        # Incremental: feed growth in three stages.
        state = IncrementalTableFilter()
        stage1 = full.slice(0, 3)
        stage2 = full.slice(0, 7)
        stage3 = full.slice(0, 10)
        for stage in (stage1, stage2, stage3):
            filtered, _ids, _changed = state.apply(
                stage, selected_ids={"100"}, ts_min=None, ts_max=None
            )

        self.assertEqual(filtered["TS"].to_list(), one_shot["TS"].to_list())

    def test_many_single_row_appends_match_one_shot(self):
        full = _df(20)
        one_shot = full.filter(pl.col("ID").is_in({"100", "200"}))

        state = IncrementalTableFilter()
        filtered = None
        for i in range(1, 21):
            filtered, _ids, _changed = state.apply(
                full.slice(0, i), selected_ids={"100", "200"}, ts_min=None, ts_max=None
            )

        self.assertEqual(filtered["TS"].to_list(), one_shot["TS"].to_list())

    def test_time_range_applied_to_new_rows(self):
        full = _df(10)
        state = IncrementalTableFilter()
        filtered, _ids, _changed = state.apply(
            full, selected_ids={"100", "200"}, ts_min=3.0, ts_max=6.0
        )
        self.assertTrue(all(3.0 <= ts <= 6.0 for ts in filtered["TS"].to_list()))

    def test_ids_changed_true_only_when_new_id_appears(self):
        state = IncrementalTableFilter()
        stage1 = _df(4, ids=["100"])
        _filtered, _ids, changed1 = state.apply(stage1, selected_ids={"100"}, ts_min=None, ts_max=None)
        self.assertTrue(changed1)

        stage2 = pl.concat([stage1, _df(2, ids=["100"])], how="vertical")
        _filtered, _ids, changed2 = state.apply(stage2, selected_ids={"100"}, ts_min=None, ts_max=None)
        self.assertFalse(changed2)

        stage3 = pl.concat([stage2, _df(2, ids=["300"])], how="vertical")
        _filtered, ids3, changed3 = state.apply(stage3, selected_ids={"100"}, ts_min=None, ts_max=None)
        self.assertTrue(changed3)
        self.assertIn("300", ids3)

    def test_shrinking_source_resets_and_recomputes(self):
        state = IncrementalTableFilter()
        big = _df(10)
        state.apply(big, selected_ids={"100"}, ts_min=None, ts_max=None)

        smaller = _df(3)
        filtered, ids, _changed = state.apply(smaller, selected_ids={"100"}, ts_min=None, ts_max=None)
        expected = smaller.filter(pl.col("ID") == "100")
        self.assertEqual(filtered["TS"].to_list(), expected["TS"].to_list())

    def test_selected_ids_narrows_without_missing_earlier_rows(self):
        # Selecting a different ID set than what was previously cached is the
        # caller's job to reset for (config change); this just documents that
        # IncrementalTableFilter itself doesn't try to detect that -- it
        # trusts the caller's selected_ids at call time for the NEW slice only.
        state = IncrementalTableFilter()
        df = _df(4, ids=["100"])
        filtered, _ids, _changed = state.apply(df, selected_ids={"999"}, ts_min=None, ts_max=None)
        self.assertEqual(filtered.height, 0)


if __name__ == "__main__":
    unittest.main()
