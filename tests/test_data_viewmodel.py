"""Characterization tests for data_viewmodel.py's streaming-flush rechunk cadence."""

from __future__ import annotations

import sys
import unittest

from PySide6.QtWidgets import QApplication

from viewmodels.data_viewmodel import _RECHUNK_EVERY_N_FLUSHES, LogDataViewModel

_app: QApplication | None = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


class FlushRechunkCadenceTests(unittest.TestCase):
    def setUp(self):
        self.vm = LogDataViewModel()

    def _flush_one_row(self, ts: float):
        import polars as pl
        from config.defaults import DEFAULT_COLUMNS

        row = {c: ([ts] if c == "TS" else (["100"] if c == "ID" else [None])) for c in DEFAULT_COLUMNS}
        df = pl.DataFrame(row)
        self.vm.append_df(df)
        self.vm._pending_timer.stop()  # bypass the real 100ms debounce
        self.vm._flush_pending()

    def test_merged_data_is_correct_regardless_of_rechunk_cadence(self):
        for i in range(_RECHUNK_EVERY_N_FLUSHES + 5):
            self._flush_one_row(float(i))
        self.assertEqual(self.vm.df.height, _RECHUNK_EVERY_N_FLUSHES + 5)
        self.assertEqual(self.vm.df["TS"].to_list(), [float(i) for i in range(_RECHUNK_EVERY_N_FLUSHES + 5)])

    def test_rechunks_only_on_the_nth_flush(self):
        for i in range(_RECHUNK_EVERY_N_FLUSHES - 1):
            self._flush_one_row(float(i))
        # Flushes 1..N-1: not yet at the rechunk boundary.
        self.assertGreater(self.vm.df.n_chunks(), 1)

        self._flush_one_row(float(_RECHUNK_EVERY_N_FLUSHES - 1))  # the Nth flush
        self.assertEqual(self.vm.df.n_chunks(), 1)

    def test_flush_count_resets_on_clear(self):
        for i in range(3):
            self._flush_one_row(float(i))
        self.assertEqual(self.vm._flush_count, 3)
        self.vm.clear()
        self.assertEqual(self.vm._flush_count, 0)


if __name__ == "__main__":
    unittest.main()
