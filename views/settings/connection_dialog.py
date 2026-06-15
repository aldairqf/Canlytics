from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_option, get_text
from viewmodels.connection_stream_viewmodel import ConnectionStreamViewModel


class ConnectionDialog(QDialog):
    def __init__(
        self,
        vm: ConnectionStreamViewModel,
        *,
        open_real_time_analysis,
        replay_offset_getter,
        normalize_getter,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(get_text("connection_title"))
        self._vm = vm
        self._open_real_time_analysis = open_real_time_analysis
        self._replay_offset_getter = replay_offset_getter
        self._normalize_getter = normalize_getter

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

        form = QFormLayout()
        form.addRow(get_text("connection_type_label"), self.connection_type)
        form.addRow(get_text("connection_mode_label"), self.stack)
        form.addRow(get_text("real_time_analysis_mode_label"), self.btn_open_real_time_analysis)
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

        self._vm.running_changed.connect(self._on_running)
        self._vm.status_changed.connect(self.status.setText)
        self._vm.error.connect(self._on_error)
        self.btn_open_real_time_analysis.clicked.connect(self._open_real_time_analysis)
        self._on_connection_type_changed(0)
        self._on_running(self._vm.running)

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

        layout.addRow(get_text("ssh_ip_host_label"), self.host)
        layout.addRow(get_text("ssh_username_label"), self.username)
        layout.addRow(get_text("ssh_key_file_label"), key_row)
        layout.addRow(get_text("ssh_key_passphrase_label"), self.key_pass)
        layout.addRow(get_text("ssh_can_interface_label"), self.iface)
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

        layout.addRow(get_text("kvaser_interface_label"), self.kvaser_interface)
        layout.addRow(get_text("kvaser_channel_label"), self.kvaser_channel)
        layout.addRow(get_text("kvaser_bitrate_label"), self.kvaser_bitrate)
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

        try:
            self._vm.start_kvaser(
                interface=interface,
                channel=channel or None,
                bitrate=bitrate,
                normalize=normalize,
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

    def _on_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.connection_type.setEnabled(not running)
        self.stack.setEnabled(not running)

    def _on_error(self, message: str) -> None:
        self.status.setText(get_text("connection_error_prefix").format(error=message))

