from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QVBoxLayout

from config.app_config import get_text


class SignalCoverageFiltersDialog(QDialog):
    def __init__(self, filters: dict[str, bool], parent=None):
        super().__init__(parent)
        self.setWindowTitle(get_text("signal_coverage_filters_title"))
        self.setModal(True)

        self.exclude_no_data = QCheckBox(get_text("signal_coverage_exclude_no_data"), self)
        self.exclude_no_data.setChecked(bool(filters.get("exclude_no_data", True)))

        self.only_changing = QCheckBox(get_text("signal_coverage_only_changing"), self)
        self.only_changing.setChecked(bool(filters.get("only_changing", False)))

        self.byte_aligned_only = QCheckBox(get_text("signal_coverage_byte_aligned_only"), self)
        self.byte_aligned_only.setChecked(bool(filters.get("byte_aligned_only", True)))

        self.hide_pdu1 = QCheckBox(get_text("signal_coverage_hide_pdu1"), self)
        self.hide_pdu1.setChecked(bool(filters.get("hide_pdu1", False)))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.exclude_no_data)
        layout.addWidget(self.only_changing)
        layout.addWidget(self.byte_aligned_only)
        layout.addWidget(self.hide_pdu1)
        layout.addWidget(buttons)

    def get_filter_state(self) -> dict[str, bool]:
        return {
            "exclude_no_data": self.exclude_no_data.isChecked(),
            "only_changing": self.only_changing.isChecked(),
            "byte_aligned_only": self.byte_aligned_only.isChecked(),
            "hide_pdu1": self.hide_pdu1.isChecked(),
        }
