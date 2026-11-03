from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from config.app_config import get_text
from models.analysis_context import AnalysisContext
from viewmodels.main_window_viewmodel import MainWindowViewModel
from views.main_window import MainWindow
from views.widgets.save_signal_dialog import SaveSignalDialog


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setFont(QFont("Segoe UI", 9))
    repo = Path(__file__).resolve().parents[1]
    output = Path(os.environ.get("CANLYTICS_VERIFY_DIR", tempfile.gettempdir())) / "canlytics-f4-03-verify"
    output.mkdir(parents=True, exist_ok=True)
    previous_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="canlytics-f403-") as temporary:
        os.chdir(temporary)
        vm = MainWindowViewModel()
        window = MainWindow(vm)
        window.show()
        fixture = repo / "tests" / "fixtures" / "logs" / "candump-sample.log"
        vm.data_vm.load_log(str(fixture))
        app.processEvents()
        can_id = vm.data_vm.can_ids[0]
        contexts = [
            AnalysisContext.from_signal(
                can_id=can_id, start_bit=0, length=8, little_endian=True,
                source_window=get_text("analysis_send_candidate"),
            ),
            AnalysisContext(
                can_id=can_id, byte_indices=(1,), range_a=(1.0, 2.0), range_b=(3.0, 4.0),
                source_window=get_text("analysis_send_diff"),
            ),
            AnalysisContext(
                can_id=can_id, byte_indices=(0, 1), source_window=get_text("analysis_send_analyze"),
            ),
            AnalysisContext.from_signal(
                can_id=can_id, start_bit=6, length=4, little_endian=False,
                source_window=get_text("plot_window_title"), mux_case=2,
            ),
            AnalysisContext(
                can_id=can_id, byte_indices=(0,), source_window=get_text("analysis_source_main_table"),
            ),
        ]
        try:
            for index, context in enumerate(contexts):
                def inspect_dialog(index=index, context=context) -> None:
                    dialog = app.activeModalWidget()
                    if not isinstance(dialog, SaveSignalDialog):
                        QTimer.singleShot(25, lambda: inspect_dialog(index, context))
                        return
                    app.processEvents()
                    screenshot = output / f"save-signal-{index + 1}-{index + 1}.png"
                    if not dialog.grab().save(str(screenshot)):
                        raise RuntimeError(f"unable to save {screenshot}")
                    if dialog.can_id.text() != context.can_id:
                        raise AssertionError(f"CAN ID was not prefilled for {context.source_window}")
                    if context.mux_case is not None and str(context.mux_case) not in dialog.source_label.text():
                        raise AssertionError(f"MUX case was not shown for {context.source_window}")
                    expected = context.suggested_signal_geometry()
                    actual = (dialog.start.value(), dialog.length.value(), dialog.byte_order.currentData() == "little_endian")
                    if actual != expected:
                        raise AssertionError(f"geometry mismatch for {context.source_window}: {actual} != {expected}")
                    if index == len(contexts) - 1:
                        dialog.signal_name.setText("VerifiedSignal")
                        dialog.start.setValue(63)
                        dialog.length.setValue(8)
                        QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.Save), Qt.LeftButton)
                        if not dialog.error_label.isVisible():
                            raise AssertionError("invalid geometry was not reported in the dialog")
                        dialog.grab().save(str(output / "save-signal-validation.png"))
                        dialog.start.setValue(0)
                        dialog.length.setValue(8)
                        QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.Save), Qt.LeftButton)
                    else:
                        dialog.reject()

                QTimer.singleShot(50, inspect_dialog)
                window._route_analysis_context("working_dbc", context)
                app.processEvents()
            message = vm.working_dbc.get_message(int(can_id, 16))
            if message.get_signal_by_name("VerifiedSignal") is None:
                raise AssertionError("the signal was not saved to Working DBC")
            if not vm.session_state.working_dbc_path.exists():
                raise AssertionError("Working DBC was not persisted")
        finally:
            window.hide()
            window._close_all_secondary_windows()
            vm.shutdown()
            os.chdir(previous_cwd)
    print(f"F4-03 save-signal UI smoke passed; screenshots: {output}")


if __name__ == "__main__":
    main()
