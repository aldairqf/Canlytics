from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)
from config.app_config import get_option, get_text
from views.icons import icon


class ActiveReWindow(QMainWindow):
    """Controls filtered replay and generated signal ramps."""

    def __init__(self, vm, dbc_signal_options=(), parent=None, working_dbc_name: str = ""):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._vm = vm
        self._frames = ()
        self.setWindowTitle(get_text("active_re_title"))
        self.tabs = QTabWidget(self)
        replay_page = QWidget(self.tabs)
        replay_form = QFormLayout(replay_page)
        self.ids = QLineEdit()
        self.ids.setMaximumWidth(240)
        self.ids.setPlaceholderText(get_text("active_re_ids_placeholder"))
        self.use_time_range = QCheckBox(get_text("active_re_use_time_range"))
        self.start_time = self._spin(-1e12, 1e12, 6)
        self.end_time = self._spin(-1e12, 1e12, 6)
        self.use_time_range.toggled.connect(self._update_time_enabled)
        self.replay_button = QPushButton(get_text("active_re_filter_replay"))
        self.replay_button.setIcon(icon("play"))
        self.replay_button.clicked.connect(self._replay)
        replay_form.addRow(get_text("active_re_ids"), self.ids)
        replay_form.addRow(self.use_time_range)
        replay_form.addRow(get_text("active_re_start"), self.start_time)
        replay_form.addRow(get_text("active_re_end"), self.end_time)
        replay_form.addRow(self.replay_button)
        self.tabs.addTab(replay_page, get_text("active_re_section_replay"))

        ramp_page = QWidget(self.tabs)
        ramp_layout = QVBoxLayout(ramp_page)
        ramp_form = QFormLayout()
        self.dbc_signal = QComboBox()
        self._fill_signals(dbc_signal_options, working_dbc_name)
        self.dbc_signal.currentIndexChanged.connect(self._update_manual_enabled)
        ramp_form.addRow(get_text("active_re_working_dbc_signal"), self.dbc_signal)
        self.start_value = self._spin(-1e9, 1e9, 3)
        self.stop_value = self._spin(-1e9, 1e9, 3)
        self.step = self._spin(-1e6, 1e6, 3)
        self.step.setValue(1)
        for key, widget in (("active_re_start_value", self.start_value),
                            ("active_re_stop_value", self.stop_value), ("active_re_step", self.step)):
            ramp_form.addRow(get_text(key), widget)
        self.period = QSpinBox()
        self.period.setRange(0, 600000)
        self.period.setMaximumWidth(120)
        self.period.setValue(int(get_option("active_re_ramp_period_ms", 100)))
        ramp_form.addRow(get_text("active_re_period"), self.period)
        ramp_layout.addLayout(ramp_form)

        self.manual_group = QGroupBox(get_text("active_re_manual"), ramp_page)
        manual_form = QFormLayout(self.manual_group)
        self.can_id = QLineEdit("100")
        self.can_id.setMaximumWidth(180)
        self.payload = QLineEdit("0000000000000000")
        self.payload.setMaximumWidth(240)
        self.extended = QCheckBox(get_text("active_re_extended"))
        self.bit = QSpinBox()
        self.bit.setRange(0, 63)
        self.bit.setMaximumWidth(100)
        self.length = QSpinBox()
        self.length.setRange(1, 64)
        self.length.setValue(8)
        self.length.setMaximumWidth(100)
        self.byte_order = QComboBox()
        self.byte_order.setMaximumWidth(200)
        self.byte_order.addItem(get_text("active_re_little_endian"), True)
        self.byte_order.addItem(get_text("active_re_big_endian"), False)
        self.value_type = QComboBox()
        self.value_type.setMaximumWidth(200)
        for key, name in (("active_re_type_unsigned", "unsigned"), ("active_re_type_signed", "signed"),
                          ("active_re_type_float", "float")):
            self.value_type.addItem(get_text(key), name)
        self.scale = self._spin(-1e9, 1e9, 6)
        self.scale.setValue(1.0)
        self.offset = self._spin(-1e9, 1e9, 6)
        for key, widget in (("active_re_can_id", self.can_id), ("active_re_extended", self.extended),
                            ("active_re_payload", self.payload), ("active_re_start_bit", self.bit),
                            ("active_re_signal_length", self.length), ("active_re_byte_order", self.byte_order),
                            ("active_re_value_type", self.value_type), ("active_re_scale", self.scale),
                            ("active_re_offset", self.offset)):
            manual_form.addRow(widget) if widget is self.extended else manual_form.addRow(get_text(key), widget)
        ramp_layout.addWidget(self.manual_group)
        self.generate_button = QPushButton(get_text("active_re_generate"))
        self.generate_button.setIcon(icon("radio"))
        self.generate_button.clicked.connect(self._generate)
        ramp_layout.addWidget(self.generate_button)
        ramp_layout.addStretch(1)
        self.tabs.addTab(ramp_page, get_text("active_re_section_ramp"))

        inject_page = QWidget(self.tabs)
        inject_layout = QVBoxLayout(inject_page)
        self.send_button = QPushButton(get_text("active_re_send"))
        self.send_button.setIcon(icon("send"))
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self._send)
        self.observation_duration = self._spin(0.1, 3600, 1)
        self.observation_duration.setValue(float(get_option("active_re_observation_window_seconds", 2.0)))
        inject_form = QFormLayout()
        inject_form.addRow(get_text("active_re_observation_duration"), self.observation_duration)
        self.observe_button = QPushButton(get_text("active_re_inject_observe"))
        self.observe_button.setIcon(icon("eye"))
        self.observe_button.clicked.connect(self._observe)
        self.cancel_observation_button = QPushButton(get_text("active_re_cancel_observation"))
        self.cancel_observation_button.setIcon(icon("eye-off"))
        self.cancel_observation_button.clicked.connect(self._cancel_observation)
        buttons = QHBoxLayout()
        buttons.addWidget(self.observe_button)
        buttons.addWidget(self.cancel_observation_button)
        self.status = QLabel()
        inject_layout.addWidget(self.send_button)
        inject_layout.addLayout(inject_form)
        inject_layout.addLayout(buttons)
        inject_layout.addWidget(self.status)
        inject_layout.addStretch(1)
        self.tabs.addTab(inject_page, get_text("active_re_section_inject"))
        self.setCentralWidget(self.tabs)
        self._update_time_enabled()
        self._update_manual_enabled()
        self._update_buttons()
        self._vm.status_changed.connect(self._on_status)
        self._vm.error.connect(self._on_status)
        self._vm.can_observe_changed.connect(self._on_vm_state_changed)
        self._vm.activity_changed.connect(self._on_vm_state_changed)

    @staticmethod
    def _spin(low: float, high: float, decimals: int) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(decimals)
        spin.setMaximumWidth(150)
        return spin

    def _fill_signals(self, options, working_dbc_name: str) -> None:
        self.dbc_signal.addItem(get_text("active_re_manual"), None)
        groups = ((get_text("active_re_group_working"), [o for o in options if o[0] == working_dbc_name]),
                  (get_text("active_re_group_active"), [o for o in options if o[0] != working_dbc_name]))
        for title, items in groups:
            if not items:
                continue
            self.dbc_signal.addItem(title, "header")
            self.dbc_signal.model().item(self.dbc_signal.count() - 1).setEnabled(False)
            for option in items:
                self.dbc_signal.addItem(" / ".join(option), option)

    def closeEvent(self, event) -> None:
        for signal, slot in ((self._vm.status_changed, self._on_status), (self._vm.error, self._on_status),
                             (self._vm.can_observe_changed, self._on_vm_state_changed),
                             (self._vm.activity_changed, self._on_vm_state_changed)):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        super().closeEvent(event)

    def _selected_signal(self):
        data = self.dbc_signal.currentData()
        return tuple(data) if isinstance(data, (tuple, list)) else None

    def _update_time_enabled(self, *_args) -> None:
        enabled = self.use_time_range.isChecked()
        self.start_time.setEnabled(enabled)
        self.end_time.setEnabled(enabled)

    def _update_manual_enabled(self, *_args) -> None:
        manual = self._selected_signal() is None
        self.manual_group.setVisible(manual)
        for widget in (self.can_id, self.payload, self.extended, self.bit, self.length, self.byte_order,
                       self.value_type, self.scale, self.offset):
            widget.setEnabled(manual)

    def _replay(self) -> None:
        ids = [value.strip() for value in self.ids.text().split(",") if value.strip()]
        time_range = (self.start_time.value(), self.end_time.value()) if self.use_time_range.isChecked() else None
        self._vm.filtered_replay(can_ids=ids or None, time_range=time_range)

    def _generate(self) -> None:
        try:
            payload = bytes.fromhex(self.payload.text())
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        value_type = self.value_type.currentData()
        self._frames = self._vm.generate_ramp(
            can_id=self.can_id.text(), base_data=payload, start=self.start_value.value(),
            stop=self.stop_value.value(), step=self.step.value(), scale=self.scale.value(),
            offset=self.offset.value(), start_bit=self.bit.value(), length=self.length.value(),
            little_endian=bool(self.byte_order.currentData()), signed=value_type == "signed",
            is_float=value_type == "float", extended=self.extended.isChecked(),
            dbc_signal=self._selected_signal())
        self._update_buttons()

    def _send(self) -> None:
        self._vm.send_ramp(self._frames, period_ms=self.period.value())

    def _observe(self) -> None:
        if self._frames:
            self._vm.start_observation(self._frames, self.can_id.text(), self.observation_duration.value(),
                                       self.period.value())

    def _cancel_observation(self) -> None:
        self._vm.cancel_observation()

    @Slot()
    def _on_vm_state_changed(self, *_args) -> None:
        self._update_buttons()

    def _update_buttons(self) -> None:
        busy = bool(self._vm.observing) or bool(self._vm.ramp_active)
        enabled = bool(self._vm.can_observe) and bool(self._frames) and not busy
        self.send_button.setEnabled(bool(self._frames) and not busy)
        self.observe_button.setEnabled(enabled)
        self.observe_button.setToolTip("" if enabled or busy else get_text("active_re_observe_unavailable"))
        self.cancel_observation_button.setEnabled(busy)

    @Slot(str)
    def _on_status(self, message: str) -> None:
        self.status.setText(message)
