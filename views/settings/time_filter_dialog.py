from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout

from config.app_config import get_text
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from views.widgets.time_filter_widget import TimeFilterWidget


class TimeFilterDialog(QDialog):
    def __init__(
        self,
        time_config_vm: TimeConfigViewModel,
        state: dict[str, str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(get_text("time_filter_title"))
        self.setWindowModality(Qt.WindowModal)

        self.filter_widget = TimeFilterWidget(
            time_config_vm,
            title=get_text("time_filter_group"),
            parent=self,
        )
        self.filter_widget.set_state(state)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.filter_widget)
        layout.addWidget(buttons)

    def get_range(self) -> tuple[float | None, float | None]:
        return self.filter_widget.get_range()

    def get_state(self) -> dict[str, str]:
        return self.filter_widget.get_state()
