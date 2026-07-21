from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from services.app_logging import QtLogHandler, is_debug_enabled, set_debug_enabled
from services.debug_log_filter import passes_filter
from services.session_state import SessionStateStore

_MAX_LINES = 5000  # oldest lines drop once the in-memory buffer exceeds this


class DebugLogWindow(QMainWindow):
    def __init__(
        self,
        qt_log_handler: QtLogHandler | None,
        log_path: Path | None = None,
        session_state: SessionStateStore | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowModality(Qt.WindowModal)
        self.setWindowTitle(get_text("debug_log_title"))
        self.resize(900, 600)
        self._handler = qt_log_handler
        self._log_path = log_path
        self._session_state = session_state
        self._lines: list[str] = self._load_history(log_path)

        self._build_ui()
        self._wire()
        self._rerender()

    @staticmethod
    def _load_history(log_path: Path | None) -> list[str]:
        """Backfill from the rotating log file so the window shows everything
        logged so far, whether it was open before now or not -- QtLogHandler only
        streams records logged after a listener subscribes to it."""
        if log_path is None or not log_path.exists():
            return []
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        lines = [line for line in text.splitlines() if line]
        return lines[-_MAX_LINES:]

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel(get_text("debug_log_level_label"), self))
        self.chk_debug = QCheckBox(get_text("debug_log_level_debug"), self)
        self.chk_debug.setToolTip(get_text("debug_log_level_debug_tooltip"))
        self.chk_info = QCheckBox(get_text("debug_log_level_info"), self)
        self.chk_warning = QCheckBox(get_text("debug_log_level_warning"), self)
        self.chk_error = QCheckBox(get_text("debug_log_level_error"), self)
        self.chk_debug.setChecked(is_debug_enabled())
        self.chk_info.setChecked(True)
        self.chk_warning.setChecked(True)
        self.chk_error.setChecked(True)
        for chk in (self.chk_debug, self.chk_info, self.chk_warning, self.chk_error):
            toolbar.addWidget(chk)

        toolbar.addWidget(QLabel(get_text("debug_log_tag_label"), self))
        self.tag_filter = QLineEdit(self)
        self.tag_filter.setPlaceholderText(get_text("debug_log_tag_placeholder"))
        toolbar.addWidget(self.tag_filter, 1)

        self.auto_scroll_check = QCheckBox(get_text("debug_log_autoscroll"), self)
        self.auto_scroll_check.setChecked(True)
        toolbar.addWidget(self.auto_scroll_check)

        self.btn_clear = QPushButton(get_text("debug_log_clear"), self)
        toolbar.addWidget(self.btn_clear)
        self.btn_copy = QPushButton(get_text("debug_log_copy"), self)
        toolbar.addWidget(self.btn_copy)
        self.btn_export = QPushButton(get_text("debug_log_export"), self)
        toolbar.addWidget(self.btn_export)

        layout.addLayout(toolbar)

        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)

        self.setCentralWidget(central)

    def _wire(self) -> None:
        if self._handler is not None:
            self._handler.record_emitted.connect(self._on_record)
        self.chk_debug.toggled.connect(self._on_debug_toggled)
        self.chk_info.toggled.connect(lambda _: self._rerender())
        self.chk_warning.toggled.connect(lambda _: self._rerender())
        self.chk_error.toggled.connect(lambda _: self._rerender())
        self.tag_filter.textChanged.connect(lambda _: self._rerender())
        self.btn_clear.clicked.connect(self._clear)
        self.btn_copy.clicked.connect(self._copy)
        self.btn_export.clicked.connect(self._export)

    def _on_debug_toggled(self, enabled: bool) -> None:
        set_debug_enabled(enabled)
        if self._session_state is not None:
            self._session_state.set_debug_mode(enabled)
        self._rerender()

    def _visible_levels(self) -> set[str]:
        levels = set()
        if self.chk_debug.isChecked():
            levels.add("DEBUG")
        if self.chk_info.isChecked():
            levels.add("INFO")
        if self.chk_warning.isChecked():
            levels.add("WARNING")
        if self.chk_error.isChecked():
            levels.add("ERROR")
        return levels

    def _on_record(self, line: str) -> None:
        self._lines.append(line)
        if len(self._lines) > _MAX_LINES:
            self._lines = self._lines[-_MAX_LINES:]
        if passes_filter(line, visible_levels=self._visible_levels(), tag_filter=self.tag_filter.text()):
            self.text.appendPlainText(line)
            if self.auto_scroll_check.isChecked():
                scrollbar = self.text.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())

    def _rerender(self) -> None:
        visible_levels = self._visible_levels()
        tag = self.tag_filter.text()
        self.text.setPlainText(
            "\n".join(line for line in self._lines if passes_filter(line, visible_levels=visible_levels, tag_filter=tag))
        )
        if self.auto_scroll_check.isChecked():
            scrollbar = self.text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _clear(self) -> None:
        if self._log_path is not None:
            reply = QMessageBox.question(
                self,
                get_text("debug_log_clear_confirm_title"),
                get_text("debug_log_clear_confirm_message"),
            )
            if reply != QMessageBox.Yes:
                return
            try:
                self._log_path.write_text("", encoding="utf-8")
            except OSError as exc:
                QMessageBox.warning(self, get_text("debug_log_clear"), str(exc))
                return
        self._lines = []
        self.text.clear()

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.text.toPlainText())

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, get_text("debug_log_export"), "canlytics_debug.log", "Log files (*.log);;All files (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(self._lines))
        except OSError as exc:
            QMessageBox.warning(self, get_text("debug_log_export"), str(exc))
