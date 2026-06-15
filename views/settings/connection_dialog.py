from __future__ import annotations

import time as _time
from datetime import datetime

from PySide6.QtCore import Qt, QThread, QTime, QTimer, Signal as QtSignal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_option, get_text
from viewmodels.connection_stream_viewmodel import ConnectionStreamViewModel


class _SshTimePollThread(QThread):
    """Connects via SSH, runs ``candump -ta <iface>``, and emits the absolute
    timestamp from each incoming CAN line.  Only the timestamp is used — the
    CAN payload is discarded.  Runs until ``stop()`` is called.
    """

    time_ready = QtSignal(float)

    def __init__(self, host: str, auth, iface: str, parent=None) -> None:
        super().__init__(parent)
        self._host = host
        self._auth = auth
        self._iface = iface
        self._stop_flag = False
        self._conn = None

    def stop(self) -> None:
        self._stop_flag = True
        conn = self._conn
        if conn:
            try:
                conn.cancel()
            except Exception:
                pass

    def run(self) -> None:
        try:
            from services.remote_connection import RemoteConnection
            from services.can_data_parser import parse_candump_line
            self._conn = RemoteConnection(self._host, self._auth)
            self._conn.open(cancel_check=lambda: self._stop_flag)
            if self._stop_flag:
                return
            channel = self._conn.exec_stream(f"candump -ta {self._iface}")
            buf = b""
            while not self._stop_flag:
                try:
                    if channel.recv_ready():
                        data = channel.recv(4096)
                        if data:
                            buf += data
                except Exception:
                    break
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    row = parse_candump_line(raw.decode("utf-8", errors="ignore").strip())
                    if row is not None:
                        self.time_ready.emit(float(row["TS"]))
                if not channel.recv_ready():
                    _time.sleep(0.01)
        except Exception:
            pass
        finally:
            conn = self._conn
            self._conn = None
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass


class _OffsetWidget(QWidget):
    """Compact ±HH:MM:SS offset selector. ``value()`` returns total seconds (float)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._sign = 1

        self._sign_btn = QPushButton("+")
        self._sign_btn.setFixedWidth(30)
        self._sign_btn.setCheckable(True)
        self._sign_btn.setToolTip("Toggle offset sign")
        self._sign_btn.clicked.connect(self._toggle_sign)

        self._time_edit = QTimeEdit(QTime(0, 0, 0), self)
        self._time_edit.setDisplayFormat("HH:mm:ss")
        self._time_edit.setMaximumTime(QTime(23, 59, 59))
        self._time_edit.setToolTip("Offset added to every recorded timestamp (HH:MM:SS)")

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
        open_real_time_analysis,
        replay_offset_getter,
        normalize_getter,
        time_config_vm=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(get_text("connection_title"))
        self._vm = vm
        self._open_real_time_analysis = open_real_time_analysis
        self._replay_offset_getter = replay_offset_getter
        self._normalize_getter = normalize_getter
        self._time_config_vm = time_config_vm

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

        self.btn_open_real_time_analysis = QPushButton(get_text("real_time_analysis_label"))

        self._btn_time_format = QPushButton("Time format…")
        self._btn_time_format.setToolTip("Configure timezone for timestamp display")
        self._btn_time_format.clicked.connect(self._open_time_format)
        self._btn_time_format.setEnabled(time_config_vm is not None)

        form = QFormLayout()
        form.addRow(get_text("connection_type_label"), self.connection_type)
        form.addRow(get_text("connection_mode_label"), self.stack)
        form.addRow(get_text("real_time_analysis_mode_label"), self.btn_open_real_time_analysis)
        form.addRow("Timestamp display:", self._btn_time_format)
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
        self._poller: _SshTimePollThread | None = None

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()

        self._vm.running_changed.connect(self._on_running)
        self._vm.status_changed.connect(self.status.setText)
        self._vm.error.connect(self._on_error)
        self.btn_open_real_time_analysis.clicked.connect(self._open_real_time_analysis)
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

        self.iface = QComboBox()
        self.iface.setEditable(True)
        interfaces = get_option("ssh_interfaces", ["can0"])
        self.iface.addItems(interfaces)
        self.iface.setCurrentText(interfaces[0])

        self._ssh_ts_pc = QRadioButton("PC (collecting machine)")
        self._ssh_ts_device = QRadioButton("Device (candump clock)")
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

        self._ssh_ts_device.toggled.connect(self._on_ssh_ts_source_changed)
        self.host.textChanged.connect(self._on_ssh_host_changed)

        layout.addRow(get_text("ssh_ip_host_label"), self.host)
        layout.addRow(get_text("ssh_username_label"), self.username)
        layout.addRow(get_text("ssh_key_file_label"), key_row)
        layout.addRow(get_text("ssh_key_passphrase_label"), self.key_pass)
        layout.addRow(get_text("ssh_can_interface_label"), self.iface)
        layout.addRow("Timestamp source:", ts_row)
        layout.addRow("Offset:", self._ssh_offset)
        layout.addRow("Collection time:", self._ssh_clock_label)
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

        self._kvaser_ts_pc = QRadioButton("PC (collecting machine)")
        self._kvaser_ts_device = QRadioButton("Device (hardware clock)")
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

        layout.addRow(get_text("kvaser_interface_label"), self.kvaser_interface)
        layout.addRow(get_text("kvaser_channel_label"), self.kvaser_channel)
        layout.addRow(get_text("kvaser_bitrate_label"), self.kvaser_bitrate)
        layout.addRow("Timestamp source:", kvaser_ts_row)
        layout.addRow("Offset:", self._kvaser_offset)
        layout.addRow("Collection time:", self._kvaser_clock_label)
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

        layout.addRow(get_text("replay_file_label"), replay_row)
        layout.addRow(get_text("replay_speed_label"), self.replay_speed)
        return page

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
        normalize = bool(self._normalize_getter())
        if self._selected_connection_type() == "ssh":
            self._start_ssh(normalize)
            return
        if self._selected_connection_type() == "kvaser":
            self._start_kvaser(normalize)
            return
        self._start_replay()

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
            self.status.setText(get_text("ssh_host_required"))
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
                self.status.setText(get_text("kvaser_bitrate_invalid"))
                return

        if not interface:
            self.status.setText(get_text("kvaser_interface_required"))
            return

        ts_source = "device" if self._kvaser_ts_device.isChecked() else "pc"
        ts_offset = self._kvaser_offset.value()
        try:
            self._vm.start_kvaser(
                interface=interface,
                channel=channel or None,
                bitrate=bitrate,
                normalize=normalize,
                ts_source=ts_source,
                ts_offset=ts_offset,
                extra_kwargs_text=self._default_kvaser_extra(interface, channel),
            )
        except ValueError as exc:
            self.status.setText(get_text("connection_error_prefix").format(error=str(exc)))

    def _start_replay(self) -> None:
        path = self.replay_file.text().strip()
        if not path:
            self.status.setText(get_text("replay_file_required"))
            return

        try:
            speed = float((self.replay_speed.currentText() or "").strip())
            if speed <= 0:
                raise ValueError()
        except ValueError:
            self.status.setText(get_text("replay_speed_invalid"))
            return

        ts_offset = float(self._replay_offset_getter() or 0.0)
        self._vm.start_replay(path=path, speed=speed, ts_offset=ts_offset)

    def _stop(self) -> None:
        self._vm.stop()

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
                        f"Device: {self._fmt_ts(ts, tz)}"
                    )
                else:
                    self._ssh_clock_label.setText("Device: waiting for CAN frames…")
            else:
                ts = _time.time() + offset
                self._ssh_clock_label.setText(f"PC: {self._fmt_ts(ts, tz)}")
        elif mode == "kvaser":
            offset = self._kvaser_offset.value()
            if self._kvaser_ts_device.isChecked():
                self._kvaser_clock_label.setText("Device: available when streaming")
            else:
                ts = _time.time() + offset
                self._kvaser_clock_label.setText(f"PC: {self._fmt_ts(ts, tz)}")

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
        dlg = TimeConfigDialog(self._time_config_vm, parent=self)
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
        from services.remote_connection import SshAuth
        auth = SshAuth(
            username=self.username.text().strip() or get_text("ssh_username_default"),
            key_file=self.key_file.text().strip() or None,
            key_passphrase=self.key_pass.text() or None,
        )
        self._poller = _SshTimePollThread(host, auth, iface=iface, parent=self)
        self._poller.time_ready.connect(self._on_device_time)
        self._poller.start()

    def _stop_device_poller(self) -> None:
        if self._poller is not None:
            self._poller.stop()
            self._poller.wait(2000)
            self._poller = None

    def _on_device_time(self, ts: float) -> None:
        self._device_ts = ts
        self._tick_clock()

    def closeEvent(self, event) -> None:
        self._stop_device_poller()
        self._clock_timer.stop()
        super().closeEvent(event)

    def reject(self) -> None:
        self._stop_device_poller()
        self._clock_timer.stop()
        super().reject()

    def _on_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.connection_type.setEnabled(not running)
        self.stack.setEnabled(not running)

    def _on_error(self, message: str) -> None:
        self.status.setText(get_text("connection_error_prefix").format(error=message))

