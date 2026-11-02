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
from PySide6.QtWidgets import QApplication, QMenu

from config.app_config import get_text
from models.frame_selector import FrameSelector
from models.mux_config import MuxConfigEntry
from models.signal import Signal
from services.candidate_interpretations import CandidateItem
from services.constraint_search import ConstraintHit, SearchResult
from viewmodels.main_window_viewmodel import MainWindowViewModel
from views.candidate_constraint_search import ConstraintResultsWindow
from views.main_window import MainWindow
from views.plot.add_to_plot_menu import make_view_signal


class AnalysisOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])
        cls.app.setFont(QFont("Segoe UI", 9))
        cls.output = Path(os.environ.get("CANLYTICS_VERIFY_DIR", tempfile.gettempdir())) / "canlytics-f3-07-verify"
        cls.output.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self._previous_cwd = Path.cwd()
        self._scratch = tempfile.TemporaryDirectory(prefix="canlytics-f3-07-")
        os.chdir(self._scratch.name)
        self.vm = MainWindowViewModel()
        self.window = MainWindow(self.vm)
        self.window.show()
        repo = Path(__file__).resolve().parents[1]
        self.vm.data_vm.load_log(str(repo / "tests" / "fixtures" / "logs" / "candump-sample.log"))
        self.app.processEvents()

    def tearDown(self):
        self.window.hide()
        self.window._close_all_secondary_windows()
        self.vm.shutdown()
        os.chdir(self._previous_cwd)
        self._scratch.cleanup()

    def _choose_menu_actions(self, choices: list[tuple[str, str]]) -> None:
        def choose(index: int, attempts: int = 0) -> None:
            menu = self.app.activePopupWidget()
            if not isinstance(menu, QMenu):
                if attempts >= 20:
                    self.fail("send-to menu did not open")
                QTimer.singleShot(30, lambda: choose(index, attempts + 1))
                return
            label, screenshot = choices[index]
            self.app.processEvents()
            menu.grab().save(str(self.output / screenshot))
            action = next((item for item in menu.actions() if item.text() == label and item.isEnabled()), None)
            self.assertIsNotNone(action, f"menu action not found or disabled: {label}")
            if index + 1 < len(choices):
                QTimer.singleShot(50, lambda: choose(index + 1))
            QTest.mouseClick(menu, Qt.LeftButton, pos=menu.actionGeometry(action).center())

        QTimer.singleShot(50, lambda: choose(0))

    def test_analyze_selected_bytes_continue_to_plot_with_context(self):
        can_id = self.vm.data_vm.df["ID"][0]
        analyze = self.window.analyze_data_manager.open_window()
        self.vm.analyze_data_vm.set_selected_id(can_id)
        self.vm.analyze_data_vm.set_selected_bytes({0, 1})
        self.app.processEvents()
        analyze.grab().save(str(self.output / "analyze-window.png"))
        self._choose_menu_actions([(get_text("add_new_graph"), "analyze-send-menu.png")])
        analyze._open_send_to_menu()
        context = self.vm.analysis_context_vm.context
        self.assertEqual(context.can_id, can_id)
        self.assertEqual(context.byte_indices, (0, 1))
        self.assertEqual(context.source_window, get_text("analyze_data_title"))
        self.assertEqual(len(self.window.plot_manager._plot_windows), 1)

    def test_constraint_result_continues_to_plot_with_signal_bits(self):
        can_id = self.vm.data_vm.df["ID"][0]
        candidate = CandidateItem(
            label=f"{can_id} b0/8", can_id=can_id, frame_len=8, mux_label="All",
            mux_start=0, mux_bytes=0, mux_value=None, start_bit=0, signal_length=8,
            byte_order="LittleEndian", value_type="Unsigned", frames=2, changes=1,
            distinct_values=2, score=0.9, min_value=0.0, max_value=1.0,
            sample_values=("00", "01"), timestamps=(1.0, 2.0), values=(0.0, 1.0),
        )
        results = ConstraintResultsWindow(
            [SearchResult(candidate, (ConstraintHit(1.0, 1.0, 0.0, 1.0),))],
            [], 1.0, "none", plot_manager=self.window.plot_manager,
            analysis_context_vm=self.vm.analysis_context_vm,
            real_time_analysis_manager=self.window.real_time_analysis_manager,
            view_signal_builder=lambda item: make_view_signal(
                Signal(
                    name=item.label, can_id=item.can_id, start_bit=item.start_bit,
                    length=item.signal_length, le=item.byte_order == "LittleEndian",
                    mux_start=item.mux_start, mux_bytes=item.mux_bytes,
                    mux_value=item.mux_value,
                ),
                FrameSelector(selected_id=item.can_id, mode="exact"),
            ),
        )
        results.show()
        results._list.setCurrentRow(0)
        self.app.processEvents()
        results.grab().save(str(self.output / "constraint-results-window.png"))
        self._choose_menu_actions([(get_text("add_new_graph"), "constraint-send-menu.png")])
        results._open_send_to_menu()
        context = self.vm.analysis_context_vm.context
        self.assertEqual(context.can_id, can_id)
        self.assertEqual(context.bit_indices, tuple(range(8)))
        self.assertEqual(context.source_window, get_text("constraint_results_title"))
        self.assertEqual(len(self.window.plot_manager._plot_windows), 1)
        results.close()

    def test_plot_signal_publishes_analysis_destinations(self):
        can_id = self.vm.data_vm.df["ID"][0]
        view_signal = make_view_signal(
            Signal(name="speed", can_id=can_id, start_bit=8, length=8),
            FrameSelector(selected_id=can_id, mode="exact"),
        )
        plot, _ = self.window.plot_manager.add_view_signal(view_signal, use_last=False)
        plot.interaction.select("speed")
        self.app.processEvents()
        QTest.qWait(250)
        self.app.processEvents()
        plot.grab().save(str(self.output / "plot-window.png"))
        plot.vm.signals["speed"].signal.mux_value = 10
        self._choose_menu_actions([
            (get_text("analysis_send_menu_title"), "plot-context-menu.png"),
            (get_text("analysis_send_analyze"), "plot-send-menu.png"),
        ])
        plot._open_context_menu()
        context = self.vm.analysis_context_vm.context
        self.assertEqual(context.can_id, can_id)
        self.assertEqual(context.bit_indices, tuple(range(8, 16)))
        self.assertEqual(context.source_window, get_text("plot_window_title"))
        self.assertEqual(context.mux_case, 10)

    def test_analyze_plot_mux_filter_uses_byte_units_and_skips_noncontiguous_rules(self):
        can_id = self.vm.data_vm.df["ID"][0]
        analyze = self.window.analyze_data_manager.open_window()
        self.vm.analyze_data_vm.set_selected_id(can_id)
        self.vm.analyze_data_vm.set_mux_configuration([MuxConfigEntry(can_id, None, (1,))])
        analyze.mux_case.setCurrentText("00")
        self.vm.analyze_data_vm.set_selected_mux_case("00")

        analyze._send_selected_bytes_to_plot((0,), use_last=False)
        plot_vm = next(iter(self.window.plot_manager._plot_windows.values()))
        signal = next(iter(plot_vm.signals.values())).signal
        self.assertEqual(signal.mux_start, 1)
        self.assertEqual(signal.mux_bytes, 1)
        self.assertEqual(signal.mux_value, 0)

        self.vm.analyze_data_vm.set_mux_configuration([MuxConfigEntry(can_id, None, (1, 3))])
        analyze.mux_case.setCurrentText("00")
        self.vm.analyze_data_vm.set_selected_mux_case("00")
        analyze._send_selected_bytes_to_plot((1,), use_last=False)
        plot_vms = list(self.window.plot_manager._plot_windows.values())
        signal = next(iter(plot_vms[-1].signals.values())).signal
        self.assertEqual(signal.mux_bytes, 0)
        self.assertIsNone(signal.mux_value)

        self.vm.analyze_data_vm.set_mux_configuration([MuxConfigEntry(can_id, 1, (1,))])
        if analyze.mux_case.findText("00") < 0:
            analyze.mux_case.addItem("00")
        analyze.mux_case.setCurrentText("00")
        self.vm.analyze_data_vm.set_selected_mux_case("00")
        analyze._send_selected_bytes_to_plot((3,), use_last=False)
        plot_vms = list(self.window.plot_manager._plot_windows.values())
        signal = next(iter(plot_vms[-1].signals.values())).signal
        self.assertEqual(signal.mux_bytes, 0)
        self.assertIsNone(signal.mux_value)

        self.vm.analyze_data_vm.set_mux_configuration([
            MuxConfigEntry(can_id, 1, (0,)),
            MuxConfigEntry(can_id, 2, (1,)),
        ])
        if analyze.mux_case.findText("00") < 0:
            analyze.mux_case.addItem("00")
        analyze.mux_case.setCurrentText("00")
        self.vm.analyze_data_vm.set_selected_mux_case("00")
        analyze._send_selected_bytes_to_plot((2,), use_last=False)
        plot_vms = list(self.window.plot_manager._plot_windows.values())
        signal = next(iter(plot_vms[-1].signals.values())).signal
        self.assertEqual(signal.mux_bytes, 0)
        self.assertIsNone(signal.mux_value)


if __name__ == "__main__":
    unittest.main()
