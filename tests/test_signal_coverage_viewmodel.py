"""Characterization tests for SignalCoverageViewModel's CAN-id index upkeep."""

from __future__ import annotations

import sys
import unittest

from PySide6.QtWidgets import QApplication

from services.can_data_parser import frame_dict, rows_to_df
from services.signal_coverage import SignalCoverageItem, SignalStats
from viewmodels.signal_coverage_viewmodel import SignalCoverageViewModel

_app: QApplication | None = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


def _stats(value: float) -> SignalStats:
    return SignalStats(
        frame_count=1, unique_count=1, min_value=value, max_value=value,
        mean_value=value, is_changing=False, last_value=value,
    )


def _item(signal_name: str, can_id: str) -> SignalCoverageItem:
    return SignalCoverageItem(
        dbc_name="d", message_name="m", signal_name=signal_name, can_id=can_id,
        pgn=None, is_pdu1=None, match_mode="exact", unit="", description="",
        start_bit=0, length=8, byte_order="little_endian", value_type="uint",
        scale=1.0, offset=0.0, mux_info=None, mux_start=0, mux_bytes=0, mux_value=None,
        stats_all=_stats(10.0), stats_real=_stats(10.0),
    )


def _row(ts: float, can_id: str, byte0: int) -> dict:
    return frame_dict(ts=ts, bus="b", can_id=can_id, data=bytes([byte0]))


class CanIdIndexUpkeepTests(unittest.TestCase):
    def setUp(self):
        self.vm = SignalCoverageViewModel(dbc_manager=None)

    def test_on_finished_builds_the_index(self):
        items = [_item("SigA", "100"), _item("SigB", "101")]
        self.vm._on_finished(items)
        self.assertEqual(set(self.vm._can_id_index.keys()), {0x100, 0x101})

    def test_ingest_df_updates_the_right_item_via_the_index(self):
        items = [_item("SigA", "100"), _item("SigB", "101")]
        self.vm._on_finished(items)

        changed = []
        self.vm.last_values_changed.connect(lambda items_: changed.extend(items_))
        self.vm.ingest_df(rows_to_df([_row(1.0, "100", 42)]))

        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0].signal_name, "SigA")
        self.assertEqual(changed[0].stats_all.last_value, 42.0)

    def test_second_scan_rebuilds_the_index_for_new_results(self):
        self.vm._on_finished([_item("SigA", "100")])
        self.vm._on_finished([_item("SigC", "200")])

        self.assertEqual(set(self.vm._can_id_index.keys()), {0x200})

        changed = []
        self.vm.last_values_changed.connect(lambda items_: changed.extend(items_))
        self.vm.ingest_df(rows_to_df([_row(1.0, "200", 7)]))
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0].signal_name, "SigC")


if __name__ == "__main__":
    unittest.main()
