"""Characterization tests for AnalyzeDataViewModel's thin Qt-adapter behavior."""

from __future__ import annotations

import sys
import unittest

import polars as pl
from PySide6.QtWidgets import QApplication

from services.analyze_data import AnalyzeDataAccumulator, build_matrix_summary
from services.can_data_parser import frame_dict, rows_to_df
from viewmodels.analyze_data_viewmodel import AnalyzeDataViewModel

_app: QApplication | None = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


def _row(ts: float, can_id: str, byte0: int) -> dict:
    return frame_dict(ts=ts, bus="b", can_id=can_id, data=bytes([byte0, 0, 0, 0, 0, 0, 0, 0]))


class AnalyzeDataViewModelTests(unittest.TestCase):
    def setUp(self):
        self.vm = AnalyzeDataViewModel()

    def test_emit_current_state_repushes_summary_and_plot(self):
        # BUGS.md B-26: a window opened after the log is already loaded (nothing
        # changed since the last full refresh) must still receive a summary snapshot,
        # else its stats panel stays blank while the plot renders fine.
        df = rows_to_df([_row(float(ts), "100", ts % 5) for ts in range(20)])
        self.vm.set_dataframe(df)

        summaries = []
        plots = []
        self.vm.summary_changed.connect(lambda payload: summaries.append(payload))
        self.vm.plot_changed.connect(lambda payload: plots.append(payload))

        self.vm.emit_current_state()

        self.assertEqual(len(summaries), 1)
        self.assertEqual(len(plots), 1)
        self.assertEqual(summaries[0]["CAN ID"], "100")
        self.assertEqual(summaries[0]["Frames"], 20)

    def test_selected_bytes_property_reflects_set_selected_bytes(self):
        # BUGS.md B-27: the vm is the long-lived survivor across window reopen; the
        # window should read its initial checkbox state from here, not hardcode "all".
        self.assertEqual(self.vm.selected_bytes, set(range(8)))
        self.vm.set_selected_bytes({0, 2, 5})
        self.assertEqual(self.vm.selected_bytes, {0, 2, 5})

    def test_emit_current_state_does_not_touch_selected_id_or_bytes(self):
        df = rows_to_df([_row(float(ts), "100", ts % 5) for ts in range(20)])
        self.vm.set_dataframe(df)
        self.vm.set_selected_bytes({0, 1})

        self.vm.emit_current_state()

        self.assertEqual(self.vm.selected_id, "100")
        self.assertEqual(self.vm._selected_bytes, {0, 1})


class AccumulatorCacheTests(unittest.TestCase):
    """ROADMAP.md Fase 2: revisiting an already-seen CAN ID must be instant (reuse
    the cached accumulator), but must never serve stale data."""

    def setUp(self):
        self.vm = AnalyzeDataViewModel()
        df = rows_to_df(
            [_row(float(ts), "100", ts % 5) for ts in range(10)]
            + [_row(float(ts), "200", ts % 3) for ts in range(10)]
        )
        self.vm.set_dataframe(df)

    def test_revisiting_an_id_reuses_the_same_accumulator_object(self):
        self.vm.set_selected_id("100")
        first_accumulator = self.vm._accumulator
        self.vm.set_selected_id("200")
        self.vm.set_selected_id("100")
        self.assertIs(self.vm._accumulator, first_accumulator)

    def test_new_data_for_an_unselected_cached_id_invalidates_it(self):
        self.vm.set_selected_id("100")
        cached_accumulator = self.vm._accumulator
        self.vm.set_selected_id("200")  # 100 now sits idle in cache

        # New frame for "100" while "200" is selected: ingest_raw_chunk() (fed from
        # chunk_ready) invalidates 100's cache entry; set_dataframe() (fed from the
        # parallel dataframe_changed signal) keeps self._df itself current, exactly
        # as the two run together from the composition root for every chunk.
        new_row = rows_to_df([_row(100.0, "100", 9)])
        self.vm.ingest_raw_chunk(new_row)
        grown_df = pl.concat([self.vm._df, new_row], how="vertical_relaxed")
        self.vm.set_dataframe(grown_df)
        self.assertNotIn("100", self.vm._accumulator_cache)

        self.vm.set_selected_id("100")
        self.assertIsNot(self.vm._accumulator, cached_accumulator)
        self.assertEqual(self.vm._accumulator.snapshot("100", (), "All")["Frames"], 11)

    def test_new_data_for_the_selected_id_keeps_its_cache_entry_live(self):
        self.vm.set_selected_id("100")
        live_accumulator = self.vm._accumulator
        self.vm.ingest_raw_chunk(rows_to_df([_row(100.0, "100", 9)]))
        # Still the same object -- fed in place, cache entry (if any) stays in sync.
        self.assertIs(self.vm._accumulator, live_accumulator)
        self.assertEqual(self.vm._accumulator.snapshot("100", (), "All")["Frames"], 11)

    def test_time_range_change_clears_the_whole_cache(self):
        self.vm.set_selected_id("100")
        self.vm.set_selected_id("200")
        self.assertIn("100", self.vm._accumulator_cache)
        self.vm.set_time_range(0.0, 5.0)
        # "100"'s stale entry from before the window change must be gone. "200" (the
        # currently selected id) legitimately gets rebuilt-and-recached right away by
        # the _full_refresh() that set_time_range triggers -- that's not staleness.
        self.assertNotIn("100", self.vm._accumulator_cache)

    def test_mux_configuration_change_clears_the_whole_cache(self):
        self.vm.set_selected_id("100")
        self.vm.set_selected_id("200")
        self.assertIn("100", self.vm._accumulator_cache)
        self.vm.set_mux_configuration([])
        self.assertNotIn("100", self.vm._accumulator_cache)

    def test_reset_dataframe_clears_the_whole_cache(self):
        self.vm.set_selected_id("100")
        self.vm.set_selected_id("200")
        self.assertIn("100", self.vm._accumulator_cache)
        self.vm.reset_dataframe(None)
        self.assertEqual(self.vm._accumulator_cache, {})

    def test_cache_hit_still_emits_summary_and_plot(self):
        self.vm.set_selected_id("100")
        self.vm.set_selected_id("200")

        summaries = []
        plots = []
        self.vm.summary_changed.connect(lambda payload: summaries.append(payload))
        self.vm.plot_changed.connect(lambda payload: plots.append(payload))
        self.vm.set_selected_id("100")

        self.assertEqual(len(summaries), 1)
        self.assertEqual(len(plots), 1)
        self.assertEqual(summaries[0]["CAN ID"], "100")


class PrecomputeTests(unittest.TestCase):
    """ROADMAP.md Fase 6: eagerly warm every CAN ID's accumulator at window-open
    time instead of paying the first-visit cost per id when the user browses."""

    def setUp(self):
        self.vm = AnalyzeDataViewModel()
        self.df = rows_to_df(
            [_row(float(ts), "100", ts % 5) for ts in range(10)]
            + [_row(float(ts), "200", ts % 3) for ts in range(10)]
            + [_row(float(ts), "300", ts % 2) for ts in range(10)]
        )
        self.vm.set_dataframe(self.df)  # auto-selects "100"

    def tearDown(self):
        self.vm.shutdown()  # stop any real QThread precompute_all() started

    def test_precompute_all_skips_selected_and_already_cached_ids(self):
        self.vm.set_selected_id("200")  # "100" now sits idle in cache
        self.assertIn("100", self.vm._accumulator_cache)

        self.vm.precompute_all()

        self.assertIsNotNone(self.vm._precompute_worker)
        self.assertEqual(set(self.vm._precompute_worker._can_ids), {"300"})

    def test_precompute_all_with_nothing_missing_emits_finished_without_a_thread(self):
        self.vm.set_selected_id("200")
        self.vm.set_selected_id("300")
        self.vm.set_selected_id("100")  # every id now cached or selected

        finished = []
        self.vm.precompute_finished.connect(lambda: finished.append(True))
        self.vm.precompute_all()

        self.assertEqual(finished, [True])
        self.assertIsNone(self.vm._precompute_thread)

    def test_on_precompute_finished_merges_into_cache(self):
        acc_200 = AnalyzeDataAccumulator()
        acc_200.feed(self.df.filter(pl.col("ID") == "200"))
        acc_300 = AnalyzeDataAccumulator()
        acc_300.feed(self.df.filter(pl.col("ID") == "300"))

        self.vm._on_precompute_finished({
            "200": (acc_200, ["All"]),
            "300": (acc_300, ["All"]),
        })

        self.assertIn("200", self.vm._accumulator_cache)
        self.assertIn("300", self.vm._accumulator_cache)
        cached_acc, mux_cases, seen_labels = self.vm._accumulator_cache["200"]
        self.assertIs(cached_acc, acc_200)
        self.assertEqual(mux_cases, ["All"])
        self.assertEqual(seen_labels, [])

    def test_on_precompute_finished_never_overwrites_the_selected_id(self):
        # "100" is selected -- _full_refresh() already cached it as an alias of the
        # live accumulator (see AnalyzeDataViewModel.__init__); a stale precompute
        # result for it must not clobber that live entry.
        live_accumulator = self.vm._accumulator
        stale_acc = AnalyzeDataAccumulator()

        self.vm._on_precompute_finished({"100": (stale_acc, ["All"])})

        self.assertIs(self.vm._accumulator_cache["100"][0], live_accumulator)
        self.assertIs(self.vm._accumulator, live_accumulator)

    def test_on_precompute_finished_never_overwrites_an_already_cached_id(self):
        self.vm.set_selected_id("200")  # "100" now cached
        cached_before = self.vm._accumulator_cache["100"]
        stale_acc = AnalyzeDataAccumulator()

        self.vm._on_precompute_finished({"100": (stale_acc, ["All"])})

        self.assertIs(self.vm._accumulator_cache["100"], cached_before)

    def test_precompute_all_is_a_noop_while_already_running(self):
        self.vm.set_selected_id("200")
        self.vm.precompute_all()
        first_worker = self.vm._precompute_worker
        self.vm.precompute_all()
        self.assertIs(self.vm._precompute_worker, first_worker)

    def test_cancel_precompute_and_shutdown_are_safe_when_nothing_is_running(self):
        self.vm.cancel_precompute()
        self.vm.shutdown()  # must not raise


class MatrixTests(unittest.TestCase):
    """The Matrix rollup (build_matrix()/get_matrix_entries()) is independent of
    _accumulator_cache -- opening the Matrix tab must not require precomputing
    every id's full accumulator."""

    def setUp(self):
        self.vm = AnalyzeDataViewModel()
        self.df = rows_to_df(
            [_row(float(ts), "100", ts % 5) for ts in range(10)]  # moving
            + [_row(float(ts), "200", 7) for ts in range(10)]  # flat
            + [_row(float(ts), "300", ts % 3) for ts in range(10)]  # moving
        )
        self.vm.set_dataframe(self.df)  # auto-selects "100"

    def tearDown(self):
        self.vm.shutdown()  # stop any real QThread build_matrix() started

    def _finish_with_real_summary(self):
        entries = build_matrix_summary(self.df, ["100", "200", "300"])
        self.vm._on_matrix_finished(entries)

    def test_build_matrix_starts_a_worker_over_every_id(self):
        self.vm.build_matrix()
        self.assertIsNotNone(self.vm._matrix_worker)
        self.assertEqual(set(self.vm._matrix_worker._can_ids), {"100", "200", "300"})

    def test_matrix_does_not_depend_on_accumulator_cache(self):
        # Only the auto-selected "100" ever touched _accumulator_cache -- no id was
        # visited via set_selected_id/precompute_all -- yet the rollup still covers all.
        self.assertEqual(set(self.vm._accumulator_cache), {"100"})
        self._finish_with_real_summary()
        self.assertEqual(len(self.vm.get_matrix_entries()), 24)  # 3 ids x 8 bytes each

    def test_returns_entries_for_every_id_sorted_by_can_id(self):
        self._finish_with_real_summary()
        entries = self.vm.get_matrix_entries()
        self.assertEqual({e.can_id for e in entries}, {"100", "200", "300"})

    def test_hide_flat_excludes_byte_entries_with_no_movement(self):
        self._finish_with_real_summary()
        entries = self.vm.get_matrix_entries(hide_flat=True)
        # _row() only varies byte0 -- "100"/"300" move on B0 alone (7 other flat
        # bytes each get filtered out too), "200" is flat on every byte.
        self.assertEqual([(e.can_id, e.byte_index) for e in entries], [("100", 0), ("300", 0)])

    def test_build_matrix_is_a_noop_once_already_built(self):
        self._finish_with_real_summary()
        finished = []
        self.vm.matrix_finished.connect(lambda: finished.append(True))
        self.vm.build_matrix()
        self.assertEqual(finished, [True])
        self.assertIsNone(self.vm._matrix_thread)

    def test_force_rebuilds_even_if_already_built(self):
        self._finish_with_real_summary()
        self.vm.build_matrix(force=True)
        self.assertIsNotNone(self.vm._matrix_worker)

    def test_time_range_change_invalidates_the_matrix(self):
        self._finish_with_real_summary()
        self.vm.set_time_range(0.0, 5.0)
        self.assertFalse(self.vm.matrix_built)

    def test_ingest_chunk_touching_a_matrix_id_invalidates_it(self):
        self._finish_with_real_summary()
        self.vm.ingest_raw_chunk(rows_to_df([_row(100.0, "200", 9)]))
        self.assertFalse(self.vm.matrix_built)

    def test_reset_dataframe_clears_the_matrix(self):
        self._finish_with_real_summary()
        self.vm.reset_dataframe(None)
        self.assertFalse(self.vm.matrix_built)
        self.assertEqual(self.vm.get_matrix_entries(), [])


class MatrixLiveModeTests(unittest.TestCase):
    """AN3: while Live is on, a CAN ID that starts moving is spliced into the
    already-built Matrix reactively instead of requiring a manual refresh."""

    def setUp(self):
        self.vm = AnalyzeDataViewModel()
        self.df = rows_to_df(
            [_row(float(ts), "100", ts % 5) for ts in range(10)]  # moving
            + [_row(float(ts), "200", 7) for ts in range(10)]  # flat
        )
        self.vm.set_dataframe(self.df)
        entries = build_matrix_summary(self.df, ["100", "200"])
        self.vm._on_matrix_finished(entries)
        self.vm.set_matrix_live(True)

    def tearDown(self):
        self.vm.shutdown()

    def _ingest(self, new_rows: pl.DataFrame) -> None:
        # Mirrors the real composition-root order (main_window_viewmodel.py):
        # chunk_ready -> data_vm.append_df (merges + emits dataframe_changed,
        # updating self._df) is wired *before* chunk_ready -> ingest_raw_chunk, so
        # ingest_raw_chunk always sees self._df already containing the new rows.
        self.df = pl.concat([self.df, new_rows], how="vertical_relaxed")
        self.vm.set_dataframe(self.df)
        self.vm.ingest_raw_chunk(new_rows)

    def test_set_matrix_live_seeds_the_live_set_from_the_existing_build(self):
        self.assertEqual(self.vm._matrix_live_ids, frozenset({"100"}))

    def test_a_previously_flat_id_gaining_movement_is_spliced_in_without_a_rebuild(self):
        self._ingest(rows_to_df([_row(100.0, "200", 1), _row(101.0, "200", 2)]))
        self.assertTrue(self.vm.matrix_built)  # no full invalidation, unlike non-live mode
        self.assertIn("200", self.vm._matrix_live_ids)
        entries = [e for e in self.vm.get_matrix_entries() if e.can_id == "200"]
        self.assertTrue(any(e.has_movement for e in entries))

    def test_a_brand_new_id_starting_to_move_is_auto_added(self):
        self._ingest(rows_to_df([_row(200.0, "300", 1), _row(201.0, "300", 2)]))
        self.assertTrue(self.vm.matrix_built)
        self.assertIn("300", self.vm._matrix_live_ids)
        self.assertIn("300", {e.can_id for e in self.vm.get_matrix_entries()})

    def test_a_brand_new_flat_id_is_added_to_the_grid_but_not_the_live_set(self):
        self._ingest(rows_to_df([_row(200.0, "300", 5), _row(201.0, "300", 5)]))
        self.assertNotIn("300", self.vm._matrix_live_ids)
        self.assertIn("300", {e.can_id for e in self.vm.get_matrix_entries()})

    def test_touching_an_already_moving_id_again_does_not_shrink_the_live_set(self):
        before = self.vm._matrix_live_ids
        self._ingest(rows_to_df([_row(100.0, "100", 1)]))
        self.assertTrue(self.vm._matrix_live_ids >= before)

    def test_live_off_falls_back_to_full_invalidation_on_a_touched_existing_id(self):
        self.vm.set_matrix_live(False)
        self._ingest(rows_to_df([_row(100.0, "200", 1)]))
        self.assertFalse(self.vm.matrix_built)

    def test_full_rebuild_resyncs_the_live_set_to_the_authoritative_snapshot(self):
        # "200" gains live-tracked movement incrementally, without a rebuild...
        self._ingest(rows_to_df([_row(100.0, "200", 1), _row(101.0, "200", 2)]))
        self.assertIn("200", self.vm._matrix_live_ids)
        # ...a later authoritative rebuild that only found "100" moving must win,
        # shrinking the live set back down rather than keeping "200" stuck in it.
        self.vm._on_matrix_finished(build_matrix_summary(self.df, ["100"]))
        self.assertNotIn("200", self.vm._matrix_live_ids)
        self.assertEqual(self.vm._matrix_live_ids, frozenset({"100"}))


if __name__ == "__main__":
    unittest.main()
