from __future__ import annotations

import sys
import unittest

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from models.derived_signal import DerivedSignal
from models.frame_selector import FrameSelector
from models.signal import Signal
from services.can_data_parser import frame_dict, rows_to_df
from viewmodels.derived_view_signal import DerivedViewSignal
from viewmodels.plot_viewmodel import PlotViewModel
from viewmodels.view_signal import ViewSignal

_app: QApplication | None = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


class PlotXySeriesTests(unittest.TestCase):
    def setUp(self):
        rows = [
            frame_dict(ts=float(i), bus="can0", can_id="100", data=bytes([i]))
            for i in range(1, 4)
        ]
        self.vm = PlotViewModel(rows_to_df(rows))
        self.vm.upsert_signal(ViewSignal(
            Signal(name="speed", can_id="100", start_bit=0, length=8),
            QColor("cyan"), "Solid", 1, selector=FrameSelector(selected_id="100"),
        ))
        self.vm.upsert_derived(DerivedViewSignal(
            DerivedSignal(name="speed_copy", formula="result = signal('speed')"),
            QColor("yellow"), "Solid", 1,
        ))

    def test_get_series_returns_full_decoded_raw_and_derived_values(self):
        raw_ts, raw_values = self.vm.get_series("signal", "speed")
        derived_ts, derived_values = self.vm.get_series("derived", "speed_copy")
        self.assertEqual(raw_ts.tolist(), [1.0, 2.0, 3.0])
        self.assertEqual(raw_values.tolist(), [1.0, 2.0, 3.0])
        self.assertEqual(derived_ts.tolist(), [1.0, 2.0, 3.0])
        self.assertEqual(derived_values.tolist(), [1.0, 2.0, 3.0])

    def test_xy_adapter_aligns_selected_plot_series(self):
        self.assertEqual(
            self.vm.series_choices(),
            [("signal", "speed", "speed"), ("derived", "speed_copy", "speed_copy (Derived)")],
        )
        timestamps, x_values, y_values = self.vm.align_xy(
            ("signal", "speed"), ("derived", "speed_copy"), start=2.0,
        )
        self.assertEqual(timestamps.tolist(), [2.0, 3.0])
        self.assertEqual(x_values.tolist(), [2.0, 3.0])
        self.assertEqual(y_values.tolist(), [2.0, 3.0])

    def test_xy_adapter_reports_invalid_derived_formula_as_value_error(self):
        self.vm.derived["speed_copy"].derived.formula = "result = signal('missing')"
        with self.assertRaises(ValueError):
            self.vm.align_xy(("signal", "speed"), ("derived", "speed_copy"))
