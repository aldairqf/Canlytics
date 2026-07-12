"""Characterization tests for PlotViewModel's incremental decode cache."""

from __future__ import annotations

import sys
import unittest

import numpy as np
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from models.frame_selector import FrameSelector
from models.signal import Signal
from services.can_data_parser import frame_dict, rows_to_df
from services.can_decoder import decode_signal
from viewmodels.plot_viewmodel import PlotViewModel
from viewmodels.view_signal import ViewSignal

_app: QApplication | None = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


def _frames_df(*frames):
    """frames: iterable of (ts, can_id, data_bytes)."""
    rows = [frame_dict(ts=ts, bus="b", can_id=cid, data=data) for ts, cid, data in frames]
    return rows_to_df(rows)


def _view_signal() -> ViewSignal:
    sig = Signal(name="s", can_id="100", start_bit=0, length=16, le=True)
    return ViewSignal(
        signal=sig,
        selector=FrameSelector(mode="exact"),
        color=QColor("cyan"),
        line_style="Solid",
        line_width=2,
    )


class SetDataframeTests(unittest.TestCase):
    def test_first_call_is_structural_change_and_emits(self):
        vm = PlotViewModel()
        emitted = []
        vm.data_changed.connect(lambda: emitted.append(1))
        vm.set_dataframe(_frames_df((0.0, "100", bytes([0x01, 0x00]))))
        self.assertEqual(len(emitted), 1)

    def test_matching_watermark_skips_emit_and_cache_clear(self):
        vm = PlotViewModel()
        vs = _view_signal()
        vm.upsert_signal(vs)
        df = _frames_df((0.0, "100", bytes([0x01, 0x00])))
        vm.set_dataframe(df)
        vm._decode_cached(vs.signal, vs.selector)  # seed the cache
        vm.ingest_raw_chunk(_frames_df((1.0, "100", bytes([0x02, 0x00]))))

        merged = _frames_df(
            (0.0, "100", bytes([0x01, 0x00])),
            (1.0, "100", bytes([0x02, 0x00])),
        )
        emitted = []
        vm.data_changed.connect(lambda: emitted.append(1))
        vm.set_dataframe(merged)  # height matches watermark -- already covered
        self.assertEqual(len(emitted), 0)

    def test_mismatched_watermark_triggers_full_recompute(self):
        vm = PlotViewModel()
        vs = _view_signal()
        vm.upsert_signal(vs)
        vm.set_dataframe(_frames_df((0.0, "100", bytes([0x01, 0x00]))))
        vm._decode_cached(vs.signal, vs.selector)

        # A file append (or anything not seen via ingest_raw_chunk) shows up
        # as a dataframe whose height doesn't match the watermark.
        appended = _frames_df(
            (0.0, "100", bytes([0x01, 0x00])),
            (5.0, "100", bytes([0x03, 0x00])),
        )
        emitted = []
        vm.data_changed.connect(lambda: emitted.append(1))
        vm.set_dataframe(appended)
        self.assertEqual(len(emitted), 1)
        ts, y = vm._decode_cached(vs.signal, vs.selector)
        expected_ts, expected_y = decode_signal(appended, vs.signal, vs.selector)
        np.testing.assert_array_equal(ts, expected_ts)
        np.testing.assert_array_equal(y, expected_y)


class IngestRawChunkTests(unittest.TestCase):
    def test_extends_cache_matches_full_decode_of_merged_df(self):
        vm = PlotViewModel()
        vs = _view_signal()
        vm.upsert_signal(vs)

        initial = _frames_df((0.0, "100", bytes([0x10, 0x00])), (1.0, "100", bytes([0x20, 0x00])))
        vm.set_dataframe(initial)
        vm._decode_cached(vs.signal, vs.selector)  # seed

        chunk = _frames_df((2.0, "100", bytes([0x30, 0x00])), (3.0, "100", bytes([0x40, 0x00])))
        vm.ingest_raw_chunk(chunk)

        merged = _frames_df(
            (0.0, "100", bytes([0x10, 0x00])),
            (1.0, "100", bytes([0x20, 0x00])),
            (2.0, "100", bytes([0x30, 0x00])),
            (3.0, "100", bytes([0x40, 0x00])),
        )
        expected_ts, expected_y = decode_signal(merged, vs.signal, vs.selector)

        ts, y = vm._decode_cached(vs.signal, vs.selector)
        np.testing.assert_array_equal(ts, expected_ts)
        np.testing.assert_array_equal(y, expected_y)

    def test_ignores_signal_not_yet_seeded(self):
        vm = PlotViewModel()
        vs = _view_signal()
        vm.upsert_signal(vs)
        # No set_dataframe/_decode_cached call yet -- cache is empty.
        emitted = []
        vm.data_changed.connect(lambda: emitted.append(1))
        vm.ingest_raw_chunk(_frames_df((0.0, "100", bytes([0x01, 0x00]))))
        self.assertEqual(len(emitted), 0)

    def test_empty_chunk_is_noop(self):
        vm = PlotViewModel()
        vs = _view_signal()
        vm.upsert_signal(vs)
        vm.set_dataframe(_frames_df((0.0, "100", bytes([0x01, 0x00]))))
        vm._decode_cached(vs.signal, vs.selector)
        emitted = []
        vm.data_changed.connect(lambda: emitted.append(1))
        vm.ingest_raw_chunk(rows_to_df([]))
        self.assertEqual(len(emitted), 0)

    def test_no_signals_is_noop(self):
        vm = PlotViewModel()
        vm.set_dataframe(_frames_df((0.0, "100", bytes([0x01, 0x00]))))
        emitted = []
        vm.data_changed.connect(lambda: emitted.append(1))
        vm.ingest_raw_chunk(_frames_df((1.0, "100", bytes([0x02, 0x00]))))
        self.assertEqual(len(emitted), 0)


if __name__ == "__main__":
    unittest.main()
