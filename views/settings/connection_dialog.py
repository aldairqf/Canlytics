from __future__ import annotations

import time as _time
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QTime, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_option, get_text
from views.icons import icon as _icon
from viewmodels.connection_stream_viewmodel import ConnectionStreamViewModel
from viewmodels.ssh_time_poll_viewmodel import SshTimePollViewModel


def _mnemonic_label(text: str, letter: str) -> str:
    index = text.casefold().find(letter.casefold())
    return text if index < 0 else text[:index] + "&" + text[index:]


def _add_labeled_row(
    layout: QFormLayout,
    text: str,
    buddy: QWidget,
    content: QWidget | QLayout | None = None,
    *,
    mnemonic: str,
) -> QLabel:
    label = QLabel(_mnemonic_label(text, mnemonic))
    label.setBuddy(buddy)
    layout.addRow(label, content if content is not None else buddy)
    return label


def _add_error_row(layout: QFormLayout, parent: QWidget) -> QLabel:
    label = QLabel(parent)
    label.setObjectName("validation_error")
    label.setWordWrap(True)
    label.setAccessibleName(get_text("connection_status_label"))
    label.hide()
    layout.addRow("", label)
    return label


class _OffsetWidget(QWidget):
    """Compact ±HH:MM:SS offset selector. ``value()`` returns total seconds (float)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._sign = 1

        self._sign_btn = QToolButton()
        self._sign_btn.setText("+")
        self._sign_btn.setObjectName("offset_sign_btn")
        self._sign_btn.setFixedSize(22, 22)
        self._sign_btn.setCheckable(True)
        self._sign_btn.setAutoRaise(True)
        self._sign_btn.setToolTip(get_text("connection_offset_sign_tooltip"))
        self._sign_btn.clicked.connect(self._toggle_sign)

        self._time_edit = QTimeEdit(QTime(0, 0, 0), self)
        self.setFocusProxy(self._time_edit)
        self._time_edit.setDisplayFormat("HH:mm:ss")
        self._time_edit.setMaximumTime(QTime(23, 59, 59))
        self._time_edit.setToolTip(get_text("connection_offset_tooltip"))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._sign_btn)
        layout.addWidget(self._time_edit)
        layout.addStretch(1)

    def _toggle_sign(self, checked: bool) -> None:
        self._sign = -1 if checked else 1
        self._sign_btn.setText("−" if checked else "+")

    def value(self) -> float:
        t = self._time_edit.time()
        return self._sign * float(t.hour() * 3600 + t.minute() * 60 + t.second())

    def setValue(self, seconds: float) -> None:
        if seconds < 0:
            self._sign = -1
            self._sign_btn.setChecked(True)
            self._sign_btn.setText("−")
            seconds = -seconds
        else:
            self._sign = 1
            self._sign_btn.setChecked(False)
            self._sign_btn.setText("+")
        secs = int(seconds)
        self._time_edit.setTime(QTime(secs // 3600, (secs % 3600) // 60, secs % 60))


class ConnectionDialog(QDialog):
    def __init__(
        self,
        vm: ConnectionStreamViewModel,
        *,
        replay_offset_getter,
        normalize_getter,
        time_config_vm=None,
        confirm_new_session=None,
        before_normalize_apply=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowModality(Qt.WindowModal)
        self.setWindowTitle(get_text("connection_title"))
        self._vm = vm
        self._replay_offset_getter = replay_offset_getter
        self._normalize_getter = normalize_getter
        self._time_config_vm = time_config_vm
        self._confirm_new_session = confirm_new_session
        self._before_normalize_apply = before_normalize_apply
        self._has_last_connection = False

        self.connection_type = QComboBox()
        self.connection_type.addItems(get_option("connection_types", ["SSH", "Kvaser"]))
        self.connection_type.currentIndexChanged.connect(self._on_connection_type_changed)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_ssh_page())
        self.stack.addWidget(self._build_kvaser_page())
        self.stack.addWidget(self._build_replay_page())

        self.btn_start = QPushButton(get_text("connection_start"))
        self.btn_start.setObjectName("primary")
        self.btn_stop = QPushButton(get_text("connection_stop"))
        self.btn_stop.setEnabled(False)

        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)

        self.status = QLabel(get_text("connection_status_idle"))
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self._btn_time_format = QPushButton(get_text("connection_time_config_button"))
        self._btn_time_format.setToolTip(get_text("connection_time_config_tooltip"))
        self._btn_time_format.clicked.connect(self._open_time_format)
        self._btn_time_format.setEnabled(time_config_vm is not None)

        form = QFormLayout()
        _add_labeled_row(form, get_text("connection_type_label"), self.connection_type, mnemonic="n")
        _add_labeled_row(form, get_text("connection_mode_label"), self.stack, mnemonic="s")
        self._btn_time_format.setText(_mnemonic_label(self._btn_time_format.text(), "i"))
        form.addRow(self._btn_time_format)
        form.addRow(get_text("connection_status_label"), self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        actions = QHBoxLayout()
        actions.addWidget(self.btn_start)
        actions.addWidget(self.btn_stop)
        actions.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(buttons)

        self._device_ts: float | None = None
        self._time_poll_vm = SshTimePollViewModel(self)
        self._time_poll_vm.time_ready.connect(self._on_device_time)

        self._ssh_retry_timer = QTimer(self)
        self._ssh_retry_timer.setSingleShot(True)
        self._ssh_retry_timer.timeout.connect(self._retry_ssh_now)
        self._ssh_retry_pending = False
        self._ssh_retry_count = 0

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()

        self._vm.running_changed.connect(self._on_running)
        self._vm.status_changed.connect(self.status.setText)
        self._vm.error.connect(self._on_error)
        if self._time_config_vm is not None:
            self._time_config_vm.timezone_changed.connect(lambda _: self._tick_clock())
            self._time_config_vm.normalize_changed.connect(lambda _: self._tick_clock())
        self._on_connection_type_changed(0)
        self._on_running(self._vm.running)
        self._tick_clock()

    def _build_ssh_page(self) -> QWidget:
        page = QWidget(self)
        layout = QFormLayout(page)

        self.host = QLineEdit()
        self.host.setPlaceholderText(get_text("ssh_host_placeholder"))
        self.host.textChanged.connect(lambda _: self._clear_field_error(self.host, self._ssh_host_error))

        self.username = QLineEdit()
        self.username.setText(get_text("ssh_username_default"))

        self.key_file = QLineEdit()
        self.key_file.setPlaceholderText(get_text("ssh_key_placeholder"))

        self.btn_browse = QPushButton(get_text("ssh_browse"))
        self.btn_browse.clicked.connect(self._browse_key)

        key_row = QHBoxLayout()
        key_row.addWidget(self.key_file, 1)
        key_row.addWidget(self.btn_browse)

        self.key_pass = QLineEdit()
        self.key_pass.setEchoMode(QLineEdit.Password)
        self.key_pass.setPlaceholderText("(optional)")

        self._btn_pass_vis = QToolButton()
        self._btn_pass_vis.setAutoRaise(True)
        self._btn_pass_vis.setFixedSize(24, 24)
        self._btn_pass_vis.setCheckable(True)
        self._btn_pass_vis.setIcon(_icon("eye", size=16))
        self._btn_pass_vis.setIconSize(QSize(16, 16))
        self._btn_pass_vis.setToolTip(get_text("connection_show_hide_passphrase_tooltip"))
        self._btn_pass_vis.toggled.connect(self._toggle_pass_visibility)

        pass_row = QHBoxLayout()
        pass_row.setSpacing(4)
        pass_row.addWidget(self.key_pass, 1)
        pass_row.addWidget(self._btn_pass_vis)

        self.iface = QComboBox()
        self.iface.setEditable(True)
        interfaces = get_option("ssh_interfaces", ["can0"])
        self.iface.addItems(interfaces)
        self.iface.setCurrentText(interfaces[0])

        self._ssh_ts_pc = QRadioButton(get_text("connection_ts_source_pc"))
        self._ssh_ts_device = QRadioButton(get_text("connection_ts_source_ssh_device"))
        self._ssh_ts_pc.setChecked(True)
        self._ssh_ts_group = QButtonGroup(page)
        self._ssh_ts_group.addButton(self._ssh_ts_pc)
        self._ssh_ts_group.addButton(self._ssh_ts_device)
        ts_row = QHBoxLayout()
        ts_row.addWidget(self._ssh_ts_pc)
        ts_row.addWidget(self._ssh_ts_device)
        ts_row.addStretch(1)

        self._ssh_offset = _OffsetWidget(page)

        self._ssh_clock_label = QLabel("—")
        self._ssh_clock_label.setStyleSheet("font-family: monospace; font-size: 12px;")

        self._ssh_auto_reconnect = QCheckBox(get_text("connection_ssh_auto_reconnect_label"))

        self._ssh_ts_device.toggled.connect(self._on_ssh_ts_source_changed)
        self.host.textChanged.connect(self._on_ssh_host_changed)
        self._ssh_auto_reconnect.toggled.connect(self._on_ssh_auto_reconnect_toggled)

        _add_labeled_row(layout, get_text("ssh_ip_host_label"), self.host, mnemonic="h")
        self._ssh_host_error = _add_error_row(layout, page)
        self._ssh_form = layout
        _add_labeled_row(layout, get_text("ssh_username_label"), self.username, mnemonic="u")
        _add_labeled_row(layout, get_text("ssh_key_file_label"), self.key_file, key_row, mnemonic="f")
        _add_labeled_row(layout, get_text("ssh_key_passphrase_label"), self.key_pass, pass_row, mnemonic="p")
        _add_labeled_row(layout, get_text("ssh_can_interface_label"), self.iface, mnemonic="i")
        self._ssh_ts_pc.setToolTip(get_text("connection_timestamp_source_tooltip"))
        self._ssh_ts_device.setToolTip(get_text("connection_timestamp_source_tooltip"))
        _add_labeled_row(layout, get_text("connection_timestamp_source_label"), self._ssh_ts_pc, ts_row, mnemonic="t")
        _add_labeled_row(layout, get_text("connection_offset_label"), self._ssh_offset, mnemonic="o")
        _add_labeled_row(layout, get_text("connection_collection_time_label"), self._ssh_clock_label, mnemonic="c")
        layout.addRow(self._ssh_auto_reconnect)
        return page

    def _build_kvaser_page(self) -> QWidget:
        page = QWidget(self)
        layout = QFormLayout(page)

        self.kvaser_interface = QComboBox()
        self.kvaser_interface.setEditable(True)
        interfaces = get_option("kvaser_interfaces", ["kvaser", "j2534"])
        self.kvaser_interface.addItems(interfaces)
        self.kvaser_interface.setCurrentText(get_option("kvaser_default_interface", interfaces[0]))
        self.kvaser_interface.currentIndexChanged.connect(self._apply_kvaser_defaults)

        self.kvaser_channel = QComboBox()
        self.kvaser_channel.setEditable(True)
        self.kvaser_channel.setPlaceholderText(get_text("kvaser_channel_placeholder"))

        self.kvaser_bitrate = QComboBox()
        self.kvaser_bitrate.setEditable(True)
        self.kvaser_bitrate.addItems([str(v) for v in get_option("kvaser_bitrates", [])])
        self.kvaser_bitrate.setPlaceholderText(get_text("kvaser_bitrate_placeholder"))
        self.kvaser_bitrate.setCurrentText(str(get_option("kvaser_default_bitrate", 500000)))

        self._kvaser_ts_pc = QRadioButton(get_text("connection_ts_source_pc"))
        self._kvaser_ts_device = QRadioButton(get_text("connection_ts_source_kvaser_device"))
        self._kvaser_ts_pc.setChecked(True)
        self._kvaser_ts_group = QButtonGroup(page)
        self._kvaser_ts_group.addButton(self._kvaser_ts_pc)
        self._kvaser_ts_group.addButton(self._kvaser_ts_device)
        kvaser_ts_row = QHBoxLayout()
        kvaser_ts_row.addWidget(self._kvaser_ts_pc)
        kvaser_ts_row.addWidget(self._kvaser_ts_device)
        kvaser_ts_row.addStretch(1)

        self._kvaser_offset = _OffsetWidget(page)

        self._kvaser_clock_label = QLabel("—")
        self._kvaser_clock_label.setStyleSheet("font-family: monospace; font-size: 12px;")

        self._kvaser_try_all_bitrates = QCheckBox(get_text("connection_kvaser_try_all_bitrates_label"))

        self._kvaser_form = layout
        _add_labeled_row(layout, get_text("kvaser_interface_label"), self.kvaser_interface, mnemonic="i").setToolTip(get_text("kvaser_interface_tooltip"))
        self._kvaser_interface_error = _add_error_row(layout, page)
        _add_labeled_row(layout, get_text("kvaser_channel_label"), self.kvaser_channel, mnemonic="p")
        _add_labeled_row(layout, get_text("kvaser_bitrate_label"), self.kvaser_bitrate, mnemonic="b")
        self._kvaser_bitrate_error = _add_error_row(layout, page)
        self.kvaser_interface.currentTextChanged.connect(lambda _: self._clear_field_error(self.kvaser_interface, self._kvaser_interface_error))
        self.kvaser_bitrate.currentTextChanged.connect(lambda _: self._clear_field_error(self.kvaser_bitrate, self._kvaser_bitrate_error))
        self._kvaser_ts_pc.setToolTip(get_text("connection_timestamp_source_tooltip"))
        self._kvaser_ts_device.setToolTip(get_text("connection_timestamp_source_tooltip"))
        _add_labeled_row(layout, get_text("connection_timestamp_source_label"), self._kvaser_ts_pc, kvaser_ts_row, mnemonic="t")
        _add_labeled_row(layout, get_text("connection_offset_label"), self._kvaser_offset, mnemonic="o")
        _add_labeled_row(layout, get_text("connection_collection_time_label"), self._kvaser_clock_label, mnemonic="c")
        layout.addRow(self._kvaser_try_all_bitrates)
        self._apply_kvaser_defaults()
        return page

    def _build_replay_page(self) -> QWidget:
        page = QWidget(self)
        layout = QFormLayout(page)

        self.replay_file = QLineEdit()
        self.replay_file.setPlaceholderText(get_text("replay_file_placeholder"))

        self.btn_replay_browse = QPushButton(get_text("replay_browse"))
        self.btn_replay_browse.clicked.connect(self._browse_replay_file)

        replay_row = QHBoxLayout()
        replay_row.addWidget(self.replay_file, 1)
        replay_row.addWidget(self.btn_replay_browse)

        self.replay_speed = QComboBox()
        self.replay_speed.setEditable(True)
        self.replay_speed.addItems([str(v) for v in get_option("replay_speeds", ["1.0"])])
        self.replay_speed.setCurrentText(str(get_option("replay_default_speed", "1.0")))

        self._replay_form = layout
        _add_labeled_row(layout, get_text("replay_file_label"), self.replay_file, replay_row, mnemonic="f")
        self._replay_file_error = _add_error_row(layout, page)
        self.replay_file.textChanged.connect(lambda _: self._clear_field_error(self.replay_file, self._replay_file_error))
        _add_labeled_row(layout, get_text("replay_speed_label"), self.replay_speed, mnemonic="s").setToolTip(get_text("replay_speed_tooltip"))
        self._replay_speed_error = _add_error_row(layout, page)
        self.replay_speed.currentTextChanged.connect(lambda _: self._clear_field_error(self.replay_speed, self._replay_speed_error))
        return page

    def _toggle_pass_visibility(self, visible: bool) -> None:
        self.key_pass.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        self._btn_pass_vis.setIcon(_icon("eye-off" if visible else "eye", size=16))

    def _browse_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            get_text("ssh_select_key_title"),
            "",
            get_text("ssh_key_files_filter"),
        )
        if path:
            self.key_file.setText(path)

    def _browse_replay_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            get_text("replay_select_title"),
            "",
            get_text("log_files_filter"),
        )
        if path:
            self.replay_file.setText(path)

    def _start(self) -> None:
        self._cancel_ssh_retry()  # a manual Start supersedes any pending auto-retry
        normalize = bool(self._normalize_getter())
        if self._selected_connection_type() == "ssh":
            self._start_ssh(normalize)
            return
        if self._selected_connection_type() == "kvaser":
            self._start_kvaser(normalize)
            return
        self._start_replay()

    def _retry_ssh_now(self) -> None:
        if not self._ssh_auto_reconnect.isChecked():
            return
        self._start_ssh(bool(self._normalize_getter()))

    def _start_ssh(self, normalize: bool) -> None:
        host = self.host.text().strip()
        username = self.username.text().strip() or get_text("ssh_username_default")
        key_file = self.key_file.text().strip() or None
        key_pass = self.key_pass.text() or None
        interfaces = get_option("ssh_interfaces", ["can0"])
        iface = (self.iface.currentText() or "").strip() or interfaces[0]
        ts_source = "device" if self._ssh_ts_device.isChecked() else "pc"
        ts_offset = self._ssh_offset.value()

        if not host:
            self._show_field_error(self.host, self._ssh_host_error, get_text("ssh_host_required"))
            return

        if not self._allow_manual_new_session():
            return

        self._vm.start_ssh(
            host=host,
            username=username,
            key_file=key_file,
            key_passphrase=key_pass,
            iface=iface,
            normalize=normalize,
            ts_source=ts_source,
            ts_offset=ts_offset,
        )

    def _start_kvaser(self, normalize: bool) -> None:
        interface = (self.kvaser_interface.currentText() or "").strip()
        channel = (self.kvaser_channel.currentText() or "").strip()
        bitrate_text = (self.kvaser_bitrate.currentText() or "").strip()
        bitrate = None
        if bitrate_text:
            try:
                bitrate = int(bitrate_text)
            except ValueError:
                self._show_field_error(self.kvaser_bitrate, self._kvaser_bitrate_error, get_text("kvaser_bitrate_invalid"))
                return

        if not interface:
            self._show_field_error(self.kvaser_interface, self._kvaser_interface_error, get_text("kvaser_interface_required"))
            return

        if not self._allow_manual_new_session():
            return

        ts_source = "device" if self._kvaser_ts_device.isChecked() else "pc"
        ts_offset = self._kvaser_offset.value()
        try_all = self._kvaser_try_all_bitrates.isEnabled() and self._kvaser_try_all_bitrates.isChecked()
        try:
            self._vm.start_kvaser(
                interface=interface,
                channel=channel or None,
                bitrate=bitrate,
                normalize=normalize,
                ts_source=ts_source,
                ts_offset=ts_offset,
                extra_kwargs_text=self._default_kvaser_extra(interface, channel),
                try_all_bitrates=try_all,
                bitrate_candidates=self._kvaser_bitrate_candidates(interface) if try_all else None,
            )
        except ValueError as exc:
            self.status.setText(get_text("connection_error_prefix").format(error=str(exc)))

    def _start_replay(self) -> None:
        path = self.replay_file.text().strip()
        if not path:
            self._show_field_error(self.replay_file, self._replay_file_error, get_text("replay_file_required"))
            return

        try:
            speed = float((self.replay_speed.currentText() or "").strip())
            if speed <= 0:
                raise ValueError()
        except ValueError:
            self._show_field_error(self.replay_speed, self._replay_speed_error, get_text("replay_speed_invalid"))
            return

        if not self._allow_manual_new_session():
            return

        ts_offset = float(self._replay_offset_getter() or 0.0)
        self._vm.start_replay(path=path, speed=speed, ts_offset=ts_offset)

    def _show_field_error(self, field: QWidget, label: QLabel, message: str) -> None:
        label.setText(message)
        label.setAccessibleName(get_text("connection_field_error_accessible").format(message=message))
        label.show()
        field.setProperty("invalid", True)
        field.setAccessibleDescription(message)
        field.setFocus()
        field.style().unpolish(field)
        field.style().polish(field)
        self.status.setText(message)

    def _clear_field_error(self, field: QWidget, label: QLabel) -> None:
        if not label.isVisible():
            return
        message = label.text()
        label.clear()
        label.hide()
        field.setProperty("invalid", False)
        field.setAccessibleDescription("")
        field.style().unpolish(field)
        field.style().polish(field)
        if self.status.text() == message:
            self.status.setText(get_text("connection_status_idle"))

    def _stop(self) -> None:
        self._cancel_ssh_retry()
        self._vm.stop()

    @property
    def has_last_connection(self) -> bool:
        return self._has_last_connection

    def start_last_connection(self) -> None:
        if self._has_last_connection and not self._vm.running:
            self._start()

    def stop_connection(self) -> None:
        self._stop()

    def _allow_manual_new_session(self) -> bool:
        if self._confirm_new_session is None:
            return True
        decision = self._confirm_new_session()
        return decision in (True, "discard", "append")

    def _cancel_ssh_retry(self) -> None:
        self._ssh_retry_timer.stop()
        self._ssh_retry_pending = False
        self._ssh_retry_count = 0

    def _on_ssh_auto_reconnect_toggled(self, checked: bool) -> None:
        if not checked:
            self._cancel_ssh_retry()

    def _selected_connection_type(self) -> str:
        return (self.connection_type.currentText() or "").strip().lower()

    def _on_connection_type_changed(self, _index: int) -> None:
        mode = self._selected_connection_type()
        if mode == "ssh":
            self.stack.setCurrentIndex(0)
        elif mode == "kvaser":
            self.stack.setCurrentIndex(1)
        else:
            self.stack.setCurrentIndex(2)

    def _apply_kvaser_defaults(self, _index: int | None = None) -> None:
        interface = (self.kvaser_interface.currentText() or "").strip().lower()
        ports = [str(p) for p in get_option(f"kvaser_ports_{interface}", [])]
        if not ports:
            ports = [str(get_option("kvaser_default_channel", "0"))]

        current = self.kvaser_channel.currentText()
        self.kvaser_channel.blockSignals(True)
        self.kvaser_channel.clear()
        self.kvaser_channel.addItems(ports)

        if current and current in ports:
            self.kvaser_channel.setCurrentText(current)
        elif interface == "kvaser":
            self.kvaser_channel.setCurrentText("0")
        else:
            self.kvaser_channel.setCurrentText(str(get_option("kvaser_default_channel", ports[0])))
        self.kvaser_channel.blockSignals(False)

        has_bitrates = bool(self._kvaser_bitrate_candidates(interface))
        self._kvaser_try_all_bitrates.setEnabled(has_bitrates)
        if not has_bitrates:
            self._kvaser_try_all_bitrates.setChecked(False)

    def _kvaser_bitrate_candidates(self, interface: str) -> list[int]:
        """Bitrates to probe for *interface*, most-common first. Falls back to
        the shared kvaser_bitrates list unless an interface-specific override
        (kvaser_bitrates_<interface>) says this interface has none."""
        raw = get_option(f"kvaser_bitrates_{interface}", get_option("kvaser_bitrates", []))
        try:
            values = [int(v) for v in raw]
        except (TypeError, ValueError):
            return []
        return self._vm.bitrate_probe_order(values)

    def _default_kvaser_extra(self, interface: str, _channel: str) -> str:
        key = f"kvaser_extra_default_{(interface or '').strip().lower()}"
        extra = str(get_option(key, "") or "").strip()
        return extra

    # ── Clock preview ─────────────────────────────────────────────────────────

    def _current_tz(self) -> str:
        if self._time_config_vm is None:
            return "none"
        if self._time_config_vm.normalize:
            return "none"
        return self._time_config_vm.timezone or "none"

    def _tick_clock(self) -> None:
        from utils.timezone_format import format_timestamp
        tz = self._current_tz()
        mode = self._selected_connection_type()
        if mode == "ssh":
            offset = self._ssh_offset.value()
            if self._ssh_ts_device.isChecked():
                if self._device_ts is not None:
                    ts = self._device_ts + offset
                    self._ssh_clock_label.setText(
                        get_text("connection_clock_device_prefix").format(value=self._fmt_ts(ts, tz))
                    )
                else:
                    self._ssh_clock_label.setText(get_text("connection_ssh_clock_waiting"))
            else:
                ts = _time.time() + offset
                self._ssh_clock_label.setText(
                    get_text("connection_clock_pc_prefix").format(value=self._fmt_ts(ts, tz))
                )
        elif mode == "kvaser":
            offset = self._kvaser_offset.value()
            if self._kvaser_ts_device.isChecked():
                self._kvaser_clock_label.setText(get_text("connection_kvaser_clock_waiting"))
            else:
                ts = _time.time() + offset
                self._kvaser_clock_label.setText(
                    get_text("connection_clock_pc_prefix").format(value=self._fmt_ts(ts, tz))
                )

    @staticmethod
    def _fmt_ts(ts: float, tz: str = "none") -> str:
        from utils.timezone_format import format_timestamp
        formatted = format_timestamp(ts, tz)
        if formatted:
            return formatted
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d  %H:%M:%S")
        except Exception:
            return f"{ts:.3f}"

    def _open_time_format(self) -> None:
        if self._time_config_vm is None:
            return
        from views.settings.time_config_dialog import TimeConfigDialog
        dlg = TimeConfigDialog(
            self._time_config_vm,
            parent=self,
            before_apply=self._before_normalize_apply,
        )
        dlg.exec()
        self._tick_clock()

    def _on_ssh_ts_source_changed(self, device_checked: bool) -> None:
        if device_checked:
            self._device_ts = None
            self._start_device_poller()
        else:
            self._stop_device_poller()
            self._device_ts = None
        self._tick_clock()

    def _on_ssh_host_changed(self) -> None:
        if self._ssh_ts_device.isChecked():
            self._device_ts = None
            self._start_device_poller()

    def _start_device_poller(self) -> None:
        self._stop_device_poller()
        host = self.host.text().strip()
        if not host:
            return
        interfaces = get_option("ssh_interfaces", ["can0"])
        iface = (self.iface.currentText() or "").strip() or interfaces[0]
        self._time_poll_vm.start(
            host,
            self.username.text().strip() or get_text("ssh_username_default"),
            self.key_file.text().strip() or None,
            self.key_pass.text() or None,
            iface,
        )

    def _stop_device_poller(self) -> None:
        self._time_poll_vm.stop()

    def _on_device_time(self, ts: float) -> None:
        self._device_ts = ts
        self._tick_clock()

    def closeEvent(self, event) -> None:
        self._cancel_ssh_retry()
        self._stop_device_poller()
        self._clock_timer.stop()
        super().closeEvent(event)

    def reject(self) -> None:
        self._cancel_ssh_retry()
        self._stop_device_poller()
        self._clock_timer.stop()
        super().reject()

    def _on_running(self, running: bool) -> None:
        if running:
            self._has_last_connection = True
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.connection_type.setEnabled(not running)
        self.stack.setEnabled(not running)
        if not running and self._ssh_retry_pending:
            self._ssh_retry_pending = False
            self._schedule_ssh_retry()

    def _on_error(self, message: str) -> None:
        self.status.setText(get_text("connection_error_prefix").format(error=message))
        if self._selected_connection_type() == "ssh" and self._ssh_auto_reconnect.isChecked():
            self._ssh_retry_pending = True

    def _schedule_ssh_retry(self) -> None:
        self._ssh_retry_count += 1
        delay = min(3 + 2 * (self._ssh_retry_count - 1), 15)
        self.status.setText(
            get_text("connection_ssh_retrying_status").format(seconds=delay, attempt=self._ssh_retry_count)
        )
        self._ssh_retry_timer.start(delay * 1000)

