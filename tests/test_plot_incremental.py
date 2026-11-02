"""Characterization tests for PlotViewModel's incremental decode cache."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from models.frame_selector import FrameSelector
from models.signal import Signal
from models.derived_signal import DerivedSignal
from services.can_data_parser import frame_dict, rows_to_df
from services.can_decoder import decode_signal
from viewmodels.plot_viewmodel import PlotViewModel
from viewmodels.derived_view_signal import DerivedViewSignal
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


class DerivedIncrementalTests(unittest.TestCase):
    def _signal(self, name: str, can_id: str) -> ViewSignal:
        return ViewSignal(
            signal=Signal(name=name, can_id=can_id, start_bit=0, length=16, le=True),
            selector=FrameSelector(mode="exact"),
            color=QColor("cyan"),
            line_style="Solid",
            line_width=2,
        )

    def _derived(self, name: str, formula: str) -> DerivedViewSignal:
        return DerivedViewSignal(
            derived=DerivedSignal(name=name, formula=formula),
            color=QColor("magenta"),
            line_style="Solid",
            line_width=2,
        )

    def test_simple_derived_formula_appends_only_the_new_signal_samples(self):
        initial = _frames_df((0.0, "100", bytes([1, 0])))
        vm = PlotViewModel(initial)
        vm.upsert_signal(self._signal("s", "100"))
        vm.upsert_derived(self._derived("twice", "ts, y = signal('s')\nresult = ts, y * 2"))
        vm.get_plot_data()  # seed the formula cache over the initial dataframe

        delta = _frames_df((1.0, "100", bytes([2, 0])))
        merged = _frames_df((0.0, "100", bytes([1, 0])), (1.0, "100", bytes([2, 0])))
        from services.formula_evaluator import evaluate

        with patch("viewmodels.plot_viewmodel.evaluate", wraps=evaluate) as formula_eval:
            vm.ingest_raw_chunk(delta)
            vm.set_dataframe(merged)
            incremental = vm.get_plot_data()[-1]
        self.assertEqual(formula_eval.call_count, 1)
        np.testing.assert_array_equal(incremental["x"], [0.0, 1.0])
        np.testing.assert_array_equal(incremental["y"], [2.0, 4.0])

        full = PlotViewModel(merged)
        full.upsert_signal(self._signal("s", "100"))
        full.upsert_derived(self._derived("twice", "ts, y = signal('s')\nresult = ts, y * 2"))
        expected = full.get_plot_data()[-1]
        np.testing.assert_array_equal(incremental["x"], expected["x"])
        np.testing.assert_array_equal(incremental["y"], expected["y"])

    def test_aligned_formula_forward_fills_across_chunks_and_matches_full(self):
        initial = _frames_df(
            (0.0, "100", bytes([1, 0])),
            (1.0, "200", bytes([10, 0])),
        )
        vm = PlotViewModel(initial)
        vm.upsert_signal(self._signal("a", "100"))
        vm.upsert_signal(self._signal("b", "200"))
        formula = (
            "ts_a, a = signal('a')\n"
            "ts_b, b = signal('b')\n"
            "ts, (a, b) = align((ts_a, a), (ts_b, b))\n"
            "result = ts, a + b"
        )
        vm.upsert_derived(self._derived("sum", formula))
        vm.get_plot_data()

        first_delta = _frames_df((2.0, "100", bytes([2, 0])))
        second_delta = _frames_df((3.0, "200", bytes([20, 0])))
        merged = _frames_df(
            (0.0, "100", bytes([1, 0])),
            (1.0, "200", bytes([10, 0])),
            (2.0, "100", bytes([2, 0])),
            (3.0, "200", bytes([20, 0])),
        )
        vm.ingest_raw_chunk(first_delta)
        vm.set_dataframe(_frames_df(
            (0.0, "100", bytes([1, 0])),
            (1.0, "200", bytes([10, 0])),
            (2.0, "100", bytes([2, 0])),
        ))
        vm.ingest_raw_chunk(second_delta)
        vm.set_dataframe(merged)
        actual = vm.get_plot_data()[-1]
        full = PlotViewModel(merged)
        full.upsert_signal(self._signal("a", "100"))
        full.upsert_signal(self._signal("b", "200"))
        full.upsert_derived(self._derived("sum", formula))
        expected = full.get_plot_data()[-1]
        np.testing.assert_array_equal(actual["x"], expected["x"])
        np.testing.assert_allclose(actual["y"], expected["y"], equal_nan=True)

    def test_aligned_chunk_at_the_same_timestamp_replaces_the_previous_tail(self):
        initial = _frames_df(
            (1.0, "100", bytes([1, 0])),
            (1.0, "200", bytes([10, 0])),
        )
        vm = PlotViewModel(initial)
        vm.upsert_signal(self._signal("a", "100"))
        vm.upsert_signal(self._signal("b", "200"))
        formula = (
            "ts_a, a = signal('a')\n"
            "ts_b, b = signal('b')\n"
            "ts, (a, b) = align((ts_a, a), (ts_b, b))\n"
            "result = ts, a + b"
        )
        vm.upsert_derived(self._derived("sum", formula))
        vm.get_plot_data()
        delta = _frames_df((1.0, "100", bytes([2, 0])))
        merged = _frames_df(
            (1.0, "100", bytes([1, 0])),
            (1.0, "200", bytes([10, 0])),
            (1.0, "100", bytes([2, 0])),
        )
        vm.ingest_raw_chunk(delta)
        vm.set_dataframe(merged)
        actual = vm.get_plot_data()[-1]
        self.assertEqual(actual["x"], [1.0])
        self.assertEqual(actual["y"], [12.0])

    def test_raw_byte_formula_uses_only_the_incoming_frames(self):
        initial = _frames_df((0.0, "100", bytes([1, 0])))
        vm = PlotViewModel(initial)
        formula = "ts, y = raw_bits(0x100, 0, 8)\nresult = ts, y"
        vm.upsert_derived(self._derived("byte", formula))
        vm.get_plot_data()
        delta = _frames_df((1.0, "100", bytes([2, 0])))
        merged = _frames_df(
            (0.0, "100", bytes([1, 0])),
            (1.0, "100", bytes([2, 0])),
        )
        vm.ingest_raw_chunk(delta)
        vm.set_dataframe(merged)
        self.assertEqual(vm.get_plot_data()[-1]["x"], [0.0, 1.0])
        self.assertEqual(vm.get_plot_data()[-1]["y"], [1.0, 2.0])

    def test_history_dependent_formula_falls_back_to_full_evaluation(self):
        initial = _frames_df((0.0, "100", bytes([1, 0])))
        vm = PlotViewModel(initial)
        vm.upsert_signal(self._signal("s", "100"))
        formula = "ts, y = signal('s')\nresult = ts, np.cumsum(y)"
        vm.upsert_derived(self._derived("cumulative", formula))
        vm.get_plot_data()
        self.assertFalse(vm._formula_is_incremental(formula))

        delta = _frames_df((1.0, "100", bytes([2, 0])))
        merged = _frames_df(
            (0.0, "100", bytes([1, 0])),
            (1.0, "100", bytes([2, 0])),
        )
        vm.ingest_raw_chunk(delta)
        vm.set_dataframe(merged)
        result = vm.get_plot_data()[-1]
        np.testing.assert_array_equal(result["y"], [1.0, 3.0])

    def test_chunk_dependent_branch_falls_back_to_full_evaluation(self):
        initial = _frames_df((0.0, "100", bytes([1, 0])))
        vm = PlotViewModel(initial)
        vm.upsert_signal(self._signal("s", "100"))
        formula = (
            "ts, y = signal('s')\n"
            "if y.size > 1:\n"
            "    result = ts, y * 2\n"
            "else:\n"
            "    result = ts, y * 3"
        )
        vm.upsert_derived(self._derived("branch", formula))
        vm.get_plot_data()
        self.assertFalse(vm._formula_is_incremental(formula))

        delta = _frames_df((1.0, "100", bytes([2, 0])))
        merged = _frames_df(
            (0.0, "100", bytes([1, 0])),
            (1.0, "100", bytes([2, 0])),
        )
        vm.ingest_raw_chunk(delta)
        vm.set_dataframe(merged)
        np.testing.assert_array_equal(vm.get_plot_data()[-1]["y"], [2.0, 4.0])

    def test_boolean_chunk_dependent_formula_falls_back_to_full_evaluation(self):
        initial = _frames_df((0.0, "100", bytes([1, 0])))
        vm = PlotViewModel(initial)
        vm.upsert_signal(self._signal("s", "100"))
        formula = "ts, y = signal('s')\nresult = ts, (y.size > 1 and y * 2)"
        vm.upsert_derived(self._derived("boolean", formula))
        vm.get_plot_data()
        self.assertFalse(vm._formula_is_incremental(formula))

        delta = _frames_df((1.0, "100", bytes([2, 0])))
        merged = _frames_df(
            (0.0, "100", bytes([1, 0])),
            (1.0, "100", bytes([2, 0])),
        )
        vm.ingest_raw_chunk(delta)
        vm.set_dataframe(merged)
        np.testing.assert_array_equal(vm.get_plot_data()[-1]["y"], [2.0, 4.0])

    def test_array_size_dependent_formula_falls_back_to_full_evaluation(self):
        initial = _frames_df((0.0, "100", bytes([1, 0])))
        vm = PlotViewModel(initial)
        vm.upsert_signal(self._signal("s", "100"))
        formula = "ts, y = signal('s')\nresult = ts, y + y.size"
        vm.upsert_derived(self._derived("size based", formula))
        vm.get_plot_data()
        self.assertFalse(vm._formula_is_incremental(formula))

        delta = _frames_df((1.0, "100", bytes([2, 0])))
        merged = _frames_df(
            (0.0, "100", bytes([1, 0])),
            (1.0, "100", bytes([2, 0])),
        )
        vm.ingest_raw_chunk(delta)
        vm.set_dataframe(merged)
        np.testing.assert_array_equal(vm.get_plot_data()[-1]["y"], [3.0, 4.0])

    def test_replaced_dataframe_reseeds_derived_state(self):
        vm = PlotViewModel(_frames_df((0.0, "100", bytes([1, 0]))))
        vm.upsert_signal(self._signal("s", "100"))
        vm.upsert_derived(self._derived("twice", "ts, y = signal('s')\nresult = ts, y * 2"))
        vm.get_plot_data()
        replacement = _frames_df((5.0, "100", bytes([7, 0])))
        vm.reset_dataframe(replacement)
        plot = vm.get_plot_data()[-1]
        np.testing.assert_array_equal(plot["x"], [5.0])
        np.testing.assert_array_equal(plot["y"], [14.0])


if __name__ == "__main__":
    unittest.main()
