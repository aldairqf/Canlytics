from __future__ import annotations

import unittest

import polars as pl

from models.trace_filter import TraceFilter
from viewmodels.table_filter_viewmodel import TableFilterViewModel


def _df(timestamps: list[float], payloads: list[str]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "TS": timestamps,
            "ID": ["100"] * len(timestamps),
            "LEN": [len(payload) // 2 for payload in payloads],
            "DATA": payloads,
        }
    )


class TableTraceFilterViewModelTests(unittest.TestCase):
    def setUp(self):
        self.vm = TableFilterViewModel()
        self.vm.set_selected_ids({"100"})
        self.full_updates: list[pl.DataFrame] = []
        self.appended: list[pl.DataFrame] = []
        self.vm.dataframe_changed.connect(self.full_updates.append)
        self.vm.rows_appended.connect(self.appended.append)

    def test_only_changes_filters_first_frame_and_retains_byte_annotations(self):
        self.vm.set_history_dataframe(_df([0.0, 1.0, 2.0], ["0102", "0102", "FF02"]))
        self.vm.set_trace_filter(TraceFilter(only_changes=True))

        self.assertEqual(self.full_updates[-1]["DATA"].to_list(), ["FF02"])
        self.assertEqual(self.full_updates[-1]["_ChangedBytes"].to_list(), ["0"])

    def test_delta_annotation_is_incremental_and_can_be_filtered(self):
        self.vm.set_history_dataframe(_df([0.0], ["0102"]))
        self.vm.set_trace_filter(TraceFilter(only_changes=True))
        self.appended.clear()
        self.vm.append_history_rows(_df([1.0, 2.0], ["0102", "0103"]))

        self.assertEqual(len(self.appended), 1)
        self.assertEqual(self.appended[0]["DATA"].to_list(), ["0103"])
        self.assertEqual(self.appended[0]["_ChangedBytes"].to_list(), ["1"])

    def test_filter_change_reuses_annotated_history(self):
        first = _df([0.0], ["0102"])
        delta = _df([1.0], ["0103"])
        self.vm.set_history_dataframe(first)
        self.vm.append_history_rows(delta)
        self.vm.update_history_source(pl.concat([first, delta], how="vertical"))
        self.vm.set_trace_filter(TraceFilter(byte_index=1, value=3))

        self.assertEqual(self.full_updates[-1]["DATA"].to_list(), ["0103"])

    def test_time_range_filter_keeps_delta_from_hidden_prior_frame(self):
        self.vm.set_history_dataframe(_df([1.0, 2.0], ["01", "02"]))
        self.vm.set_time_range(2.0, 2.0)

        self.assertEqual(self.full_updates[-1]["TS"].to_list(), [2.0])
        self.assertEqual(self.full_updates[-1]["Delta T"].to_list(), [1.0])

    def test_incremental_trace_filter_keeps_delta_across_hidden_frame(self):
        self.vm.set_history_dataframe(_df([1.0], ["01"]))
        self.vm.set_trace_filter(TraceFilter(only_changes=True))
        self.appended.clear()
        self.vm.append_history_rows(_df([2.0, 3.0], ["01", "02"]))

        self.assertEqual(self.appended[-1]["TS"].to_list(), [3.0])
        self.assertEqual(self.appended[-1]["Delta T"].to_list(), [1.0])


if __name__ == "__main__":
    unittest.main()
