from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QMessageBox,
    QWidget,
)

from config.app_config import get_text
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from views.widgets.time_filter_widget import TimeFilterWidget


class LogExportDialog(QDialog):
    def __init__(
        self,
        time_config_vm: TimeConfigViewModel,
        *,
        filter_state: dict[str, str] | None = None,
        fixed_scope: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(get_text("log_export_title"))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.scope_combo = QComboBox(self)
        for scope, key in (
            ("all", "log_export_scope_all"),
            ("filtered", "log_export_scope_filtered"),
            ("range", "log_export_scope_range"),
        ):
            self.scope_combo.addItem(get_text(key), scope)
        self.scope_combo.currentIndexChanged.connect(self._update_range_visibility)
        self.time_filter = TimeFilterWidget(
            time_config_vm,
            title=get_text("log_export_time_range"),
            parent=self,
        )
        for field in (
            self.time_filter.ts_from,
            self.time_filter.ts_to,
            self.time_filter.date_from,
            self.time_filter.date_to,
        ):
            field.setMinimumWidth(150)
        self.time_filter.set_state(filter_state)
        if fixed_scope is not None:
            index = self.scope_combo.findData(fixed_scope)
            if index >= 0:
                self.scope_combo.setCurrentIndex(index)
            self.scope_combo.setEnabled(False)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(get_text("log_export_scope_label"), self))
        layout.addWidget(self.scope_combo)
        layout.addWidget(self.time_filter)
        layout.addWidget(buttons)
        self._update_range_visibility()

    def selection(self) -> tuple[str, float | None, float | None]:
        ts_min, ts_max = self.time_filter.get_range()
        return str(self.scope_combo.currentData()), ts_min, ts_max

    def _accept_if_valid(self) -> None:
        scope, ts_min, ts_max = self.selection()
        if scope == "range" and ts_min is None and ts_max is None:
            QMessageBox.warning(self, self.windowTitle(), get_text("log_export_range_required"))
            return
        if ts_min is not None and ts_max is not None and ts_min > ts_max:
            QMessageBox.warning(self, self.windowTitle(), get_text("log_export_range_invalid"))
            return
        self.accept()

    def _update_range_visibility(self, *_args: object) -> None:
        self.time_filter.setVisible(self.scope_combo.currentData() == "range")
