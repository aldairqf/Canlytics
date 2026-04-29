from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from config.app_config import get_text
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from views.widgets.time_filter_widget import TimeFilterWidget


class CandidateFiltersDialog(QDialog):
    def __init__(
        self,
        *,
        time_config_vm: TimeConfigViewModel,
        time_filter_state: dict[str, str] | None,
        amp_enabled: bool,
        amp_min: float,
        amp_max: float,
        frames_enabled: bool = False,
        frames_min: int = 0,
        frames_max: int = 100000,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(get_text("candidate_filters_title"))

        self.time_filter = TimeFilterWidget(time_config_vm, parent=self)
        self.time_filter.set_state(time_filter_state)

        self.amp_group = QGroupBox(get_text("candidate_amp_filter"), self)
        self.amp_group.setCheckable(True)
        self.amp_group.setChecked(bool(amp_enabled))

        self.amp_min_spin = QDoubleSpinBox(self)
        self.amp_min_spin.setRange(-1e15, 1e15)
        self.amp_min_spin.setDecimals(3)
        self.amp_min_spin.setValue(float(amp_min))
        self.amp_min_spin.setStepType(QDoubleSpinBox.AdaptiveDecimalStepType)

        self.amp_max_spin = QDoubleSpinBox(self)
        self.amp_max_spin.setRange(-1e15, 1e15)
        self.amp_max_spin.setDecimals(3)
        self.amp_max_spin.setValue(float(amp_max))
        self.amp_max_spin.setStepType(QDoubleSpinBox.AdaptiveDecimalStepType)

        amp_form = QFormLayout(self.amp_group)
        amp_form.addRow("Min", self.amp_min_spin)
        amp_form.addRow("Max", self.amp_max_spin)

        self.frames_group = QGroupBox(get_text("candidate_frames_filter"), self)
        self.frames_group.setCheckable(True)
        self.frames_group.setChecked(bool(frames_enabled))

        self.frames_min_spin = QSpinBox(self)
        self.frames_min_spin.setRange(0, 10_000_000)
        self.frames_min_spin.setValue(int(frames_min))

        self.frames_max_spin = QSpinBox(self)
        self.frames_max_spin.setRange(0, 10_000_000)
        self.frames_max_spin.setValue(int(frames_max))

        frames_form = QFormLayout(self.frames_group)
        frames_form.addRow(get_text("candidate_frames_min"), self.frames_min_spin)
        frames_form.addRow(get_text("candidate_frames_max"), self.frames_max_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.time_filter)
        layout.addWidget(self.amp_group)
        layout.addWidget(self.frames_group)
        layout.addWidget(buttons)

    def get_filter_state(self) -> dict:
        return {
            "time_filter_state": self.time_filter.get_state(),
            "amp_enabled": self.amp_group.isChecked(),
            "amp_min": self.amp_min_spin.value(),
            "amp_max": self.amp_max_spin.value(),
            "frames_enabled": self.frames_group.isChecked(),
            "frames_min": self.frames_min_spin.value(),
            "frames_max": self.frames_max_spin.value(),
        }
