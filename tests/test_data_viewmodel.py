"""Characterization tests for data_viewmodel.py's streaming-flush rechunk cadence."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from services.can_data_parser import frame_dict, rows_to_df
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


class RowsAppendedSignalTests(unittest.TestCase):
    def setUp(self):
        self.vm = LogDataViewModel()
        self.appended = []
        self.replaced = []
        self.ids_changed = []
        self.vm.rows_appended.connect(lambda delta, ids: self.appended.append((delta, ids)))
        self.vm.dataframe_replaced.connect(self.replaced.append)
        self.vm.can_ids_changed.connect(self.ids_changed.append)

    @staticmethod
    def _chunk(ts: float, can_id: int):
        return rows_to_df([frame_dict(ts=ts, bus="can0", can_id=can_id, data=b"\x01")])

    def _flush(self, ts: float, can_id: int) -> None:
        self.vm.append_df(self._chunk(ts, can_id), unsaved=False)
        self.vm.flush_pending()

    def test_ordered_appends_emit_only_the_delta_and_new_ids(self):
        self._flush(1.0, 0x100)
        self._flush(2.0, 0x100)
        self._flush(3.0, 0x200)
        self.assertEqual([delta.height for delta, _ in self.appended], [1, 1, 1])
        self.assertEqual([ids for _, ids in self.appended], [("100",), (), ("200",)])
        self.assertEqual([ids for ids in self.ids_changed], [["100"], ["100", "200"]])
        self.assertEqual(self.vm.df.height, sum(delta.height for delta, _ in self.appended))
        self.assertEqual(self.replaced, [])

    def test_out_of_order_append_replaces_dataframe_and_suppresses_delta(self):
        self._flush(1.0, 0x100)
        self.appended.clear()
        self._flush(0.5, 0x200)
        self.assertEqual(self.appended, [])
        self.assertEqual(len(self.replaced), 1)
        self.assertEqual(self.replaced[0]["TS"].to_list(), [0.5, 1.0])
        self.assertEqual(self.ids_changed[-1], ["100", "200"])

    def test_normalized_delta_matches_the_appended_rows_in_the_dataframe(self):
        self.vm._normalize = True
        self._flush(-1.0, 0x100)
        self._flush(0.0, 0x200)
        delta, new_ids = self.appended[-1]
        self.assertEqual(delta["TS"].to_list(), [1.0])
        self.assertEqual(new_ids, ("200",))
        self.assertEqual(self.vm.df.tail(1)["TS"].to_list(), delta["TS"].to_list())

    def test_replacement_rebuilds_incremental_id_set(self):
        self._flush(1.0, 0x100)
        replacement = rows_to_df([
            frame_dict(ts=5.0, bus="can1", can_id=0x300, data=b"\x02"),
            frame_dict(ts=6.0, bus="can1", can_id=0x200, data=b"\x03"),
        ])
        with tempfile.NamedTemporaryFile(suffix=".log") as log_file:
            self.vm.replace_log(log_file.name, replacement)
        self.assertEqual(self.ids_changed[-1], ["200", "300"])
        self._flush(7.0, 0x200)
        self.assertEqual(self.appended[-1][1], ())

    def test_added_source_path_is_normalized_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "trace.log")
            self.vm.add_source_path(path)
            self.vm.add_source_path(path)
        self.assertEqual(len(self.vm.source_paths), 1)
        self.assertTrue(self.vm.source_paths[0].endswith("trace.log"))


if __name__ == "__main__":
    unittest.main()
