"""Characterization tests for TableModel's active-sort persistence (BUGS.md B-09)."""

from __future__ import annotations

import sys
import unittest

import polars as pl
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from viewmodels.table_model import TableModel

_app: QApplication | None = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


def _df(ids: list[str]) -> pl.DataFrame:
    return pl.DataFrame({"ID": ids, "LEN": [8] * len(ids)})


class LiveTableSortPersistsAcrossRefreshTests(unittest.TestCase):
    """optimize_append=False is what Real-Time Analysis uses -- a live-refreshing
    table where every tick re-sends the vm's own (unsorted) row order."""

    def setUp(self):
        self.model = TableModel(["ID", "LEN"], optimize_append=False)

    def test_sort_survives_a_same_height_refresh(self):
        self.model.set_dataframe(_df(["300", "100", "200"]))
        self.model.sort(0, Qt.AscendingOrder)
        self.assertEqual(self.model._df["ID"].to_list(), ["100", "200", "300"])

        # Same row count, new (unsorted) content -- as a live refresh tick would send.
        self.model.set_dataframe(_df(["300", "200", "100"]))
        self.assertEqual(self.model._df["ID"].to_list(), ["100", "200", "300"])

    def test_sort_survives_a_row_count_change(self):
        self.model.set_dataframe(_df(["300", "100", "200"]))
        self.model.sort(0, Qt.DescendingOrder)
        self.assertEqual(self.model._df["ID"].to_list(), ["300", "200", "100"])

        self.model.set_dataframe(_df(["300", "100", "200", "050"]))
        self.assertEqual(self.model._df["ID"].to_list(), ["300", "200", "100", "050"])

    def test_no_active_sort_leaves_vm_order_untouched(self):
        self.model.set_dataframe(_df(["300", "100", "200"]))
        self.assertEqual(self.model._df["ID"].to_list(), ["300", "100", "200"])


class AppendOptimizedTableIgnoresActiveSort(unittest.TestCase):
    """The main table (optimize_append=True, the default) must be completely
    unaffected -- its tail-insert fast path assumes the vm's own row order."""

    def setUp(self):
        self.model = TableModel(["ID", "LEN"])

    def test_active_sort_is_not_reapplied_on_refresh(self):
        self.model.set_dataframe(_df(["300", "100", "200"]))
        self.model.sort(0, Qt.AscendingOrder)
        self.assertEqual(self.model._df["ID"].to_list(), ["100", "200", "300"])

        self.model.set_dataframe(_df(["300", "100", "200", "050"]))
        # Appended in vm order, NOT re-sorted -- optimize_append's fast path stands.
        self.assertEqual(self.model._df["ID"].to_list(), ["300", "100", "200", "050"])


class TailAppendRechunkThrottleTests(unittest.TestCase):
    """The tail-insert fast path used to rechunk=True on every single append (an
    O(total rows) copy each time); it's now throttled to every Nth append, same
    idea as data_viewmodel.py's _RECHUNK_EVERY_N_FLUSHES. Content must stay fully
    correct regardless of the throttle, and a rechunk must still actually happen
    periodically (not just skipped forever)."""

    def setUp(self):
        self.model = TableModel(["ID", "LEN"])

    def test_content_stays_correct_across_many_small_appends(self):
        ids: list[str] = []
        for i in range(45):
            ids.append(f"{i:03d}")
            self.model.set_dataframe(_df(ids))
        self.assertEqual(self.model._df["ID"].to_list(), ids)
        self.assertEqual(self.model._df.height, 45)

    def test_rechunk_still_happens_periodically(self):
        from viewmodels.table_model import _RECHUNK_EVERY_N_APPENDS

        ids: list[str] = []
        chunk_counts = []
        for i in range(_RECHUNK_EVERY_N_APPENDS + 2):
            ids.append(f"{i:03d}")
            self.model.set_dataframe(_df(ids))
            chunk_counts.append(self.model._df.n_chunks())
        # The very first call takes the old_h==0 fast path (no tail-append, no
        # counter increment), so _append_count reaches N on the (N+1)th call, index N.
        self.assertEqual(chunk_counts[_RECHUNK_EVERY_N_APPENDS], 1)


class RowForegroundProviderTests(unittest.TestCase):
    """B-03: dimming a row (e.g. "not changed" in Real-Time) is a per-row
    foreground hook, not a filter -- the row must stay in the model/view."""

    def setUp(self):
        self.model = TableModel(["ID", "LEN"])
        self.model.set_dataframe(_df(["100", "200", "300"]))

    def test_no_provider_returns_none_for_foreground_role(self):
        index = self.model.index(0, 0)
        self.assertIsNone(self.model.data(index, Qt.ForegroundRole))

    def test_provider_result_is_returned_for_foreground_role(self):
        dimmed = QColor("#888888")
        self.model.set_row_foreground_provider(lambda row: dimmed if row == 1 else None)
        self.assertIsNone(self.model.data(self.model.index(0, 0), Qt.ForegroundRole))
        self.assertEqual(self.model.data(self.model.index(1, 0), Qt.ForegroundRole), dimmed)

    def test_provider_does_not_affect_display_role(self):
        self.model.set_row_foreground_provider(lambda row: QColor("#888888"))
        self.assertEqual(self.model.data(self.model.index(0, 0), Qt.DisplayRole), "100")

    def test_clearing_the_provider_restores_default(self):
        self.model.set_row_foreground_provider(lambda row: QColor("#888888"))
        self.model.set_row_foreground_provider(None)
        self.assertIsNone(self.model.data(self.model.index(0, 0), Qt.ForegroundRole))


class ExpandedRowsResetOnFullModelResetTests(unittest.TestCase):
    """A full model reset (filter selection change, row count shrinks/changes
    in a way that isn't the tail-append fast path) must clear _expanded_rows --
    it's keyed by row INDEX, not frame identity, so row N after the reset is a
    different frame than row N before it. Leaving it set makes a row inherit a
    stale custom height from RowHeightManager, squeezing its (different) decode
    line count into the wrong-sized row -- reproduced via: expand a row, then
    change the CAN ID filter selection (shrinks/changes the row count)."""

    def setUp(self):
        self.model = TableModel(["ID", "LEN"])
        self.model.set_dataframe(_df(["100", "200", "300"]))

    def test_shrinking_the_row_count_clears_expanded_rows(self):
        self.model.toggle_row_expanded(1)
        self.assertTrue(self.model.is_row_expanded(1))

        self.model.set_dataframe(_df(["100", "200"]))  # e.g. CAN ID filter narrowed

        self.assertFalse(self.model.is_row_expanded(1))
        self.assertEqual(self.model.get_decode_line_count(1), 0)

    def test_growing_the_row_count_via_full_reset_clears_expanded_rows(self):
        # A count *increase* that isn't a tail-append (e.g. a completely new
        # filtered selection, not the streaming-append case) is still a full
        # reset -- same hazard applies.
        self.model.toggle_row_expanded(0)
        self.assertTrue(self.model.is_row_expanded(0))

        self.model.set_dataframe(_df(["999", "888", "777", "666", "555"]))

        self.assertFalse(self.model.is_row_expanded(0))

    def test_none_dataframe_reset_clears_expanded_rows(self):
        self.model.toggle_row_expanded(2)
        self.model.set_dataframe(None)
        self.assertEqual(self.model._expanded_rows, set())


if __name__ == "__main__":
    unittest.main()
