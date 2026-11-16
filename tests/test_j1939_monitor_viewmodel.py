from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import polars as pl
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from viewmodels.j1939_monitor_viewmodel import (
    J1939MonitorViewModel,
    _J1939MonitorWorker,
)
from models.j1939 import J1939AnalysisSnapshot, J1939Node
from viewmodels.data_viewmodel import LogDataViewModel
from views.j1939_monitor_window_manager import J1939MonitorWindowManager
from viewmodels.main_window_viewmodel import MainWindowViewModel
from views.main_window import MainWindow


class J1939MonitorViewModelTests(unittest.TestCase):
    def test_main_window_tracks_and_closes_j1939_monitor(self):
        app = QApplication.instance() or QApplication([])
        vm = MainWindowViewModel()
        window = MainWindow(vm)
        try:
            empty_menu = window._build_source_menu(vm.active_source)
            self.assertFalse(empty_menu.actions()[0].isEnabled())
            self.assertFalse(empty_menu.actions()[1].isEnabled())
            vm.data_vm._source_paths = {str(Path("C:/logs/drive.asc"))}
            vm._emit_active_source()
            self.assertIn("drive.asc", window._source_text.text())
            self.assertIn("drive.asc", window._source_indicator.toolTip())
            self.assertIn("drive.asc", window.windowTitle())
            menu = window._build_source_menu(vm.active_source)
            self.assertTrue(menu.actions()[0].isEnabled())
            vm.data_vm._source_paths.add(str(Path("C:/logs/second.blf")))
            vm._emit_active_source()
            self.assertIn("2 archivos", window._source_text.text())
            self.assertIn("2 archivos", window.windowTitle())
            menu = window._build_source_menu(vm.active_source)
            self.assertEqual(menu.actions()[0].text(), "2 archivos")
            self.assertEqual(len(menu.actions()), 1)
            monitor = window.j1939_monitor_manager.open_window()
            app.processEvents()
            self.assertTrue(window._has_open_secondary_windows())
            window._close_all_secondary_windows()
            self.assertFalse(monitor.isVisible())
            app.processEvents()
            self.assertIsNone(window.j1939_monitor_manager._window)
        finally:
            vm.shutdown()
            window.close()

    def test_shutdown_clears_pending_reanalysis_and_dataframe(self):
        vm = J1939MonitorViewModel()
        vm.set_dataframe(pl.DataFrame({"TS": [1.0]}))
        vm._reanalyze_pending = True
        vm.shutdown()
        self.assertTrue(vm._closed)
        self.assertFalse(vm._reanalyze_pending)
        self.assertTrue(vm._dataframe.is_empty())
        with patch.object(vm, "_cleanup") as cleanup:
            vm.analyze(pl.DataFrame({"TS": [2.0]}))
            cleanup.assert_not_called()
        self.assertIsNone(vm._thread)

    def test_thread_cleanup_does_not_restart_when_shutdown_has_pending_work(self):
        vm = J1939MonitorViewModel()
        vm._closed = True
        vm._reanalyze_pending = True
        with patch("viewmodels.j1939_monitor_viewmodel.QTimer.singleShot") as single_shot:
            vm._cleanup()
        single_shot.assert_not_called()
        self.assertFalse(vm._reanalyze_pending)

    def test_analyze_during_run_replaces_pending_dataframe(self):
        vm = J1939MonitorViewModel()
        first = pl.DataFrame({"TS": [1.0]})
        latest = pl.DataFrame({"TS": [9.0]})
        with patch.object(type(vm), "analysis_running", new_callable=unittest.mock.PropertyMock, return_value=True):
            vm.analyze(first)
            vm.analyze(latest)
        self.assertTrue(vm._reanalyze_pending)
        self.assertIs(vm._dataframe, latest)
    def test_analysis_uses_owned_qthread_worker_and_publishes_snapshot(self):
        dataframe = pl.DataFrame({
            "TS": [1.0],
            "ID": ["18EEFF80"],
            "DATA": ["0000000000000000"],
        })
        vm = J1939MonitorViewModel()
        snapshots = []
        progress = []
        vm.analysis_finished.connect(snapshots.append)
        vm.analysis_progress.connect(lambda done, total: progress.append((done, total)))

        with patch.object(_J1939MonitorWorker, "moveToThread") as move_to_thread:
            with patch.object(QThread, "start"):
                vm.analyze(dataframe)
                move_to_thread.assert_called_once_with(vm._thread)
                self.assertIs(vm._thread.parent(), vm)
                vm._worker.run()

        self.assertEqual(snapshots[0].nodes[0].source_address, 0x80)
        self.assertEqual(progress[-1], (2, 2))
        vm._worker.deleteLater()
        vm._thread.deleteLater()

    def test_cancel_flag_stops_worker_analysis(self):
        dataframe = pl.DataFrame({
            "TS": [1.0],
            "ID": ["18FEE300"],
            "DATA": ["0000000000000000"],
        })
        worker = _J1939MonitorWorker(dataframe)
        canceled = []
        worker.canceled.connect(lambda: canceled.append(True))
        worker.cancel()
        worker.run()
        self.assertEqual(canceled, [True])

    def test_real_thread_finishes_cleans_up_and_allows_second_analysis(self):
        script = """
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QSignalSpy, QTest
import polars as pl
from viewmodels.j1939_monitor_viewmodel import J1939MonitorViewModel

app = QCoreApplication.instance() or QCoreApplication([])
vm = J1939MonitorViewModel()
finished = QSignalSpy(vm.analysis_finished)
try:
    vm.analyze(pl.DataFrame({"TS": [1.0], "ID": ["18EEFF80"], "DATA": ["0000000000000000"]}))
    deadline = 5000
    while finished.count() < 1 and deadline > 0:
        QTest.qWait(10)
        deadline -= 10
    assert finished.count() == 1
    deadline = 5000
    while vm._thread is not None and deadline > 0:
        QTest.qWait(10)
        deadline -= 10
    assert not vm.analysis_running and vm._thread is None
    vm.analyze()
    deadline = 5000
    while finished.count() < 2 and deadline > 0:
        QTest.qWait(10)
        deadline -= 10
    assert finished.count() == 2
    deadline = 5000
    while vm._thread is not None and deadline > 0:
        QTest.qWait(10)
        deadline -= 10
    assert not vm.analysis_running and vm._thread is None and vm._worker is None
    vm.release()
    assert vm._dataframe.is_empty() and vm.snapshot.nodes == ()
finally:
    vm.shutdown()
"""
        environment = dict(os.environ)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_replacement_clears_old_snapshot_and_restarts_analysis(self):
        vm = J1939MonitorViewModel()
        manager = J1939MonitorWindowManager(vm, LogDataViewModel())
        old = J1939AnalysisSnapshot((J1939Node(1, 1.0),), ())
        vm._snapshot = old
        dataframe = pl.DataFrame({"TS": [2.0], "ID": ["18EEFF80"], "DATA": ["0000000000000000"]})
        manager._data_vm.dataframe_changed.connect(vm.set_dataframe)
        manager._data_vm.dataframe_replaced.connect(manager._on_dataframe_replaced)
        with patch.object(vm, "analyze") as analyze:
            manager._on_dataframe_replaced(dataframe)
            analyze.assert_called_once_with()
        self.assertEqual(vm.snapshot, J1939AnalysisSnapshot((), ()))
        self.assertIs(vm._dataframe, dataframe)
        manager._on_window_destroyed()
        self.assertTrue(vm._dataframe.is_empty())

    def test_timestamp_formatter_uses_display_format_instead_of_epoch(self):
        vm = J1939MonitorViewModel()
        self.assertEqual(vm.format_timestamp(1.0), "1.000")


if __name__ == "__main__":
    unittest.main()
