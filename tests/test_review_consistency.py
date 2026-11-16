from __future__ import annotations

import unittest

from utils.can_id import format_can_id
from utils.timezone_format import format_timestamp
from utils.period_format import format_period_ms
from PySide6.QtCore import Qt
from viewmodels.table_model import TableModel
import polars as pl


class ReviewConsistencyTests(unittest.TestCase):
    def test_extended_can_ids_use_eight_hex_digits(self):
        self.assertEqual(format_can_id("CF00400"), "0CF00400")
        self.assertEqual(format_can_id("7DF"), "7DF")

    def test_can_id_panel_displays_formatted_ids_and_keeps_raw_selection(self):
        from PySide6.QtWidgets import QApplication
        from views.widgets.can_id_panel import CanIdPanelWidget

        app = QApplication.instance() or QApplication([])
        panel = CanIdPanelWidget(show_interpret_controls=False)
        panel.set_can_ids(["CF00400"])
        self.assertEqual(panel.can_list.item(0).text(), "0CF00400")
        self.assertEqual(panel.can_list.item(0).data(Qt.UserRole), "CF00400")
        panel.deleteLater()
        app.processEvents()

    def test_unzoned_timestamp_uses_three_decimal_places(self):
        self.assertEqual(format_timestamp(12.345678, "none"), "12.346")

    def test_period_formatter_converts_seconds_to_milliseconds(self):
        self.assertEqual(format_period_ms(0.5), "500.000")

    def test_table_id_sort_is_numeric(self):
        model = TableModel(["ID"])
        model.set_dataframe(pl.DataFrame({"ID": ["1A0", "80", "10"]}))
        model.sort(0, Qt.AscendingOrder)
        self.assertEqual(model._df["ID"].to_list(), ["10", "80", "1A0"])


if __name__ == "__main__":
    unittest.main()
