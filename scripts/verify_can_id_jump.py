from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from viewmodels.main_window_viewmodel import MainWindowViewModel
from views.main_window import MainWindow
from views.widgets.can_id_jump_dialog import CanIdJumpDialog


class MainWindowCanIdJumpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])
        cls.app.setFont(QFont("Segoe UI", 9))

    def setUp(self):
        self._previous_cwd = Path.cwd()
        self._scratch = tempfile.TemporaryDirectory(prefix="canlytics-can-id-jump-")
        os.chdir(self._scratch.name)
        self.vm = MainWindowViewModel()
        self.window = MainWindow(self.vm)
        self.window.show()
        repo = Path(__file__).resolve().parents[1]
        self.vm.data_vm.load_log(str(repo / "tests" / "fixtures" / "logs" / "candump-sample.log"))
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.vm.shutdown()
        os.chdir(self._previous_cwd)
        self._scratch.cleanup()

    def test_ctrl_f_jumps_to_first_frame_and_clears_excluding_time_range(self):
        source = self.vm.data_vm.df
        target = source["ID"][0]
        other = next(can_id for can_id in self.vm.data_vm.can_ids if can_id != target)
        self.window.view.panel.set_checked_ids({target, other})
        self.vm.time_range_vm.set_time_range(0, 1)
        self.app.processEvents()
        self.assertEqual(
            self.vm.table_model.rowCount(),
            0,
            (self.vm.filter_vm.time_range, self.vm.filter_vm.selected_ids),
        )

        state = {"chosen": False}

        def choose_target():
            dialog = self.app.activeModalWidget()
            if not isinstance(dialog, CanIdJumpDialog):
                return
            dialog.search.setText(target)
            dialog.results.setCurrentRow(0)
            state["chosen"] = True
            dialog.accept()

        self.window.activateWindow()
        self.window.setFocus()
        self.app.processEvents()
        QTimer.singleShot(50, choose_target)
        QTest.keyClick(self.window, Qt.Key_F, Qt.ControlModifier)
        self.assertTrue(state["chosen"], "Ctrl+F did not open the CAN ID dialog")
        QTest.qWait(100)

        selected_ids = self.window.view.panel.selected_ids()
        self.assertEqual(selected_ids, {target, other})
        self.assertEqual(self.vm.time_range_vm.time_range, (None, None))
        selected_rows = self.window.view.table.selectionModel().selectedRows()
        self.assertEqual(
            len(selected_rows),
            1,
            (
                self.vm.table_model.rowCount(),
                self.vm.filter_vm.selected_ids,
                self.vm.filter_vm.time_range,
                self.vm.filter_vm._history_df.height,
                self.vm.filter_vm._history_filter.cached_filtered.height,
                self.vm.table_vm._pending_df.height if self.vm.table_vm._pending_df is not None else None,
            ),
        )
        selected_row = selected_rows[0].row()
        id_column = self.vm.table_model._columns.index("ID")
        matching_rows = [
            row for row in range(self.vm.table_model.rowCount())
            if self.vm.table_model.get_row_record(row)["ID"] == target
        ]
        self.assertTrue(matching_rows)
        first_frame_row = min(
            matching_rows,
            key=lambda row: self.vm.table_model.get_row_record(row)["TS"],
        )
        self.assertEqual(selected_row, first_frame_row)
        self.assertEqual(
            self.vm.table_model.data(self.vm.table_model.index(selected_row, id_column), Qt.DisplayRole),
            target,
        )


if __name__ == "__main__":
    unittest.main()
