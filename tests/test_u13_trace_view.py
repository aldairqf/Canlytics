from __future__ import annotations

import unittest
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

_STATE_DIR = Path(tempfile.mkdtemp(prefix=".u13-state-", dir=Path.cwd() / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import polars as pl
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QToolButton

from services.session_state import SessionStateStore
from services.trace_columns import normalize_trace_preferences
from viewmodels.main_window_viewmodel import MainWindowViewModel
from viewmodels.table_filter_viewmodel import TableFilterViewModel
from viewmodels.table_model import TableModel
from views.main_window import MainWindow


_APP = QApplication.instance() or QApplication([])


def tearDownModule() -> None:
    shutil.rmtree(_STATE_DIR, ignore_errors=True)


class WorktreeStateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._state_environment = patch.dict(os.environ, {"CANLYTICS_STATE_DIR": str(_STATE_DIR)})
        self._state_environment.start()

    def tearDown(self) -> None:
        self._state_environment.stop()


def _frames(ids: list[str], timestamps: list[float], data: list[str]) -> pl.DataFrame:
    return pl.DataFrame({"TS": [float(value) for value in timestamps], "Bus": [0] * len(ids), "ID": ids, "LEN": [1] * len(ids), "DATA": data})


class OneRowPerIdTests(WorktreeStateTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.vm = TableFilterViewModel()
        self.model = TableModel(["TS", "ID", "LEN", "DATA"], optimize_append=False)
        self.vm.dataframe_changed.connect(self.model.set_dataframe)
        self.vm.set_history_dataframe(_frames(["200", "100", "200", "100"], [1, 2, 3, 4], ["01", "02", "03", "04"]))

    def test_loaded_log_keeps_latest_frame_per_numeric_id(self) -> None:
        self.vm.set_one_row_per_id(True)
        self.assertEqual(self.model._df["ID"].to_list(), ["100", "200"])
        self.assertEqual(self.model._df["DATA"].to_list(), ["04", "03"])

    def test_chunk_update_visits_only_chunk_and_replaces_latest_rows(self) -> None:
        self.vm.set_one_row_per_id(True)
        chunk = _frames(["200", "300"], [5, 6], ["05", "06"])
        with patch.object(self.vm, "_collect_latest_rows", wraps=self.vm._collect_latest_rows) as collect:
            self.vm.append_history_rows(chunk)
        collect.assert_called_once()
        self.assertEqual(collect.call_args.args[0].height, chunk.height)
        self.assertEqual(collect.call_args.args[0]["ID"].to_list(), chunk["ID"].to_list())
        self.assertEqual(self.model._df["ID"].to_list(), ["100", "200", "300"])
        self.assertEqual(self.model._df["DATA"].to_list(), ["04", "05", "06"])

    def test_toggle_back_restores_all_loaded_rows_without_replacement_load(self) -> None:
        self.vm.set_selected_ids({"100", "200"})
        self.vm.set_one_row_per_id(True)
        with patch.object(self.vm, "set_history_dataframe", wraps=self.vm.set_history_dataframe) as reload_history:
            self.vm.set_one_row_per_id(False)
        reload_history.assert_not_called()
        self.assertEqual(self.model._df.height, 4)
        self.assertEqual(self.model._df["DATA"].to_list(), ["01", "02", "03", "04"])

    def test_sort_id_filter_time_range_and_cursor_lookup_work_in_compact_mode(self) -> None:
        self.vm.set_one_row_per_id(True)
        self.model.sort(1, 1)
        self.vm.set_selected_ids({"200"})
        self.vm.set_time_range(2.5, 5.0)
        self.assertEqual(self.model._df["ID"].to_list(), ["200"])
        self.assertEqual(self.model.nearest_row_for_timestamp(4.8), 0)
        self.vm.set_selected_ids(set())
        self.vm.set_time_range(None, None)
        self.model.sort(1, 1)
        self.assertEqual(self.model._df["ID"].to_list(), ["100", "200"])


class TraceViewRibbonTests(WorktreeStateTestCase):
    def test_main_view_has_no_content_filter_or_changed_byte_column(self) -> None:
        vm = MainWindowViewModel()
        window = MainWindow(vm)
        try:
            self.assertFalse(hasattr(window.view, "trace_filter_bar"))
            self.assertNotIn("_ChangedBytes", vm.table_model._columns)
            self.assertEqual(type(window.view.table.itemDelegateForColumn(vm.table_model._columns.index("DATA"))).__name__, "DecodeLineLayoutDelegate")
            self.assertFalse(hasattr(window.view.table.itemDelegateForColumn(vm.table_model._columns.index("DATA")), "_draw_bytes"))
        finally:
            vm.shutdown()
            window.close()

    def test_home_view_format_and_columns_action(self) -> None:
        vm = MainWindowViewModel()
        window = MainWindow(vm)
        try:
            self.assertIsNotNone(window._ribbon.findChild(type(window._ribbon.view_group), "traceViewGroup"))
            window._ribbon.trace_mode.setCurrentIndex(window._ribbon.trace_mode.findData("bits"))
            self.assertEqual(vm.table_model.data_display_mode(), "bits")
            QTest.mouseClick(window._ribbon.one_row_button, Qt.MouseButton.LeftButton)
            self.assertTrue(vm.trace_preferences["one_row_per_id"])
            self.assertTrue(vm.table_model._one_row_per_id_view)
            self.assertTrue(window._ribbon.one_row_button.property("active"))
            self.assertEqual(window._ribbon.one_row_button.text(), "ID")
            self.assertEqual(window._ribbon.one_row_button.toolTip(), "One row per ID")
            with patch("views.main_window.TraceSettingsDialog") as dialog:
                dialog.return_value.exec.return_value = 1
                dialog.return_value.preferences.return_value = {}
                columns = next(button for button in window._ribbon.view_group.findChildren(QToolButton) if button.text() == "Columns...")
                QTest.mouseClick(columns, Qt.MouseButton.LeftButton)
                dialog.assert_called_once()
        finally:
            vm.shutdown()
            window.close()

    def test_compact_label_fits_at_1500px_in_dark_and_light_themes(self) -> None:
        vm = MainWindowViewModel()
        window = MainWindow(vm)
        previous_theme = vm.session_state.get_theme() or "Dark"
        try:
            window.resize(1500, 900)
            window.show()
            for theme in ("Dark", "Light"):
                window._set_theme(theme)
                _APP.processEvents()
                button = window._ribbon.one_row_button
                self.assertEqual(button.text(), "ID")
                self.assertLessEqual(QFontMetrics(button.font()).horizontalAdvance(button.text()), button.width() - 8)
                self.assertEqual(button.toolTip(), "One row per ID")
        finally:
            window._set_theme(previous_theme)
            vm.shutdown()
            window.close()

    def test_theme_change_resizes_timestamp_column(self) -> None:
        vm = MainWindowViewModel()
        window = MainWindow(vm)
        previous_theme = vm.session_state.get_theme() or "Dark"
        try:
            with patch.object(window, "_resize_timestamp_column", wraps=window._resize_timestamp_column) as resize:
                window._set_theme("Light" if previous_theme != "Light" else "Dark")
            resize.assert_called_once_with()
            column = vm.table_model._columns.index("TS")
            sample = window._ts_delegate.displayText(1_700_000_000.0, window.view.table.locale())
            expected_width = window.view.table.fontMetrics().horizontalAdvance(sample) + 16
            self.assertGreaterEqual(window.view.table.columnWidth(column), expected_width)
        finally:
            window._set_theme(previous_theme)
            vm.shutdown()
            window.close()

    def test_main_window_compact_mode_keeps_default_id_order_and_global_cursor(self) -> None:
        vm = MainWindowViewModel()
        window = MainWindow(vm)
        try:
            vm.filter_vm.set_history_dataframe(_frames(["200", "100", "200"], [1, 2, 3], ["01", "02", "03"]))
            vm.filter_vm.set_one_row_per_id(True)
            _APP.processEvents()
            self.assertEqual(vm.table_model._df["ID"].to_list(), ["100", "200"])
            vm.time_cursor_vm.set_timestamp(3.0, "test")
            _APP.processEvents()
            selected_row = window.view.table.currentIndex().row()
            self.assertEqual(vm.table_model.get_row_record(selected_row)["TS"], 3.0)
        finally:
            vm.shutdown()
            window.close()

    def test_one_row_preference_round_trip(self) -> None:
        preferences = normalize_trace_preferences({"one_row_per_id": True})
        store = SessionStateStore()
        store.set_window_prefs("main_trace", preferences)
        self.assertTrue(normalize_trace_preferences(store.get_window_prefs("main_trace"))["one_row_per_id"])


if __name__ == "__main__":
    unittest.main()
