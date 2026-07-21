from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
        endianness_filter: str = "All",
        min_length_filter: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowModality(Qt.WindowModal)
        self.setWindowTitle(get_text("candidate_filters_title"))

        self.time_filter = TimeFilterWidget(time_config_vm, parent=self)
        self.time_filter.set_state(time_filter_state)

        # Explicit checkbox, not a checkable QGroupBox -- the checkable-groupbox
        # indicator is easy to miss next to the custom title styling this app uses.
        self.amp_enabled_check = QCheckBox(get_text("candidate_amp_filter"), self)
        self.amp_enabled_check.setChecked(bool(amp_enabled))

        self.amp_group = QGroupBox(self)
        self.amp_group.setEnabled(bool(amp_enabled))
        self.amp_enabled_check.toggled.connect(self.amp_group.setEnabled)

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
        amp_form.addRow(get_text("candidate_amp_min"), self.amp_min_spin)
        amp_form.addRow(get_text("candidate_amp_max"), self.amp_max_spin)

        self.frames_enabled_check = QCheckBox(get_text("candidate_frames_filter"), self)
        self.frames_enabled_check.setChecked(bool(frames_enabled))

        self.frames_group = QGroupBox(self)
        self.frames_group.setEnabled(bool(frames_enabled))
        self.frames_enabled_check.toggled.connect(self.frames_group.setEnabled)

        self.frames_min_spin = QSpinBox(self)
        self.frames_min_spin.setRange(0, 10_000_000)
        self.frames_min_spin.setValue(int(frames_min))

        self.frames_max_spin = QSpinBox(self)
        self.frames_max_spin.setRange(0, 10_000_000)
        self.frames_max_spin.setValue(int(frames_max))

        frames_form = QFormLayout(self.frames_group)
        frames_form.addRow(get_text("candidate_frames_min"), self.frames_min_spin)
        frames_form.addRow(get_text("candidate_frames_max"), self.frames_max_spin)

        # CI3/CI4: display-time only -- hide multibyte partials / one endianness,
        # never recompute (the search already tried both, see CI6).
        self.encoding_group = QGroupBox(get_text("candidate_encoding_filter"), self)
        self.endianness_filter_combo = QComboBox(self)
        self.endianness_filter_combo.addItems([
            get_text("candidate_filter_endianness_all"),
            get_text("candidate_interpretations_little_endian"),
            get_text("candidate_interpretations_big_endian"),
        ])
        self.endianness_filter_combo.setCurrentIndex(
            {"All": 0, "LittleEndian": 1, "BigEndian": 2}.get(endianness_filter, 0)
        )
        self.min_length_filter_spin = QSpinBox(self)
        self.min_length_filter_spin.setRange(0, 64)
        self.min_length_filter_spin.setValue(int(min_length_filter))
        self.min_length_filter_spin.setSpecialValueText(get_text("candidate_filter_endianness_all"))
        self.min_length_filter_spin.setToolTip(get_text("candidate_min_length_filter_tooltip"))

        encoding_form = QFormLayout(self.encoding_group)
        encoding_form.addRow(get_text("candidate_endianness_filter_label"), self.endianness_filter_combo)
        encoding_form.addRow(get_text("candidate_min_length_filter_label"), self.min_length_filter_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.time_filter)
        layout.addWidget(self.amp_enabled_check)
        layout.addWidget(self.amp_group)
        layout.addWidget(self.frames_enabled_check)
        layout.addWidget(self.frames_group)
        layout.addWidget(self.encoding_group)
        layout.addWidget(buttons)

    def get_filter_state(self) -> dict:
        return {
            "time_filter_state": self.time_filter.get_state(),
            "amp_enabled": self.amp_enabled_check.isChecked(),
            "amp_min": self.amp_min_spin.value(),
            "amp_max": self.amp_max_spin.value(),
            "frames_enabled": self.frames_enabled_check.isChecked(),
            "frames_min": self.frames_min_spin.value(),
            "frames_max": self.frames_max_spin.value(),
            "endianness_filter": ("All", "LittleEndian", "BigEndian")[self.endianness_filter_combo.currentIndex()],
            "min_length_filter": self.min_length_filter_spin.value(),
        }
