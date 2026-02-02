from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QComboBox,
)

from viewmodels.ssh_can_stream_viewmodel import SshCanStreamViewModel
from config.app_config import get_option, get_text


class SshConnectionDialog(QDialog):
    def __init__(self, vm: SshCanStreamViewModel, *, normalize_getter, parent=None):
        super().__init__(parent)
        self.setWindowTitle(get_text("ssh_connection_title"))
        self._vm = vm
        self._normalize_getter = normalize_getter

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
        self.iface.addItems(get_option("ssh_interfaces", []))
        self.iface.setCurrentText(get_option("ssh_interfaces", ["can0"])[0])

        self.btn_start = QPushButton(get_text("ssh_start"))
        self.btn_stop = QPushButton(get_text("ssh_stop"))
        self.btn_stop.setEnabled(False)

        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)

        self.status = QLabel(get_text("ssh_status_idle"))
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)

        form = QFormLayout()
        form.addRow(get_text("ssh_ip_host_label"), self.host)
        form.addRow(get_text("ssh_username_label"), self.username)
        form.addRow(get_text("ssh_key_file_label"), key_row)
        form.addRow(get_text("ssh_key_passphrase_label"), self.key_pass)
        form.addRow(get_text("ssh_can_interface_label"), self.iface)
        form.addRow(get_text("ssh_status_label"), self.status)

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
        self._on_running(self._vm.running)

    def _browse_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            get_text("ssh_select_key_title"),
            "",
            get_text("ssh_key_files_filter"),
        )
        if path:
            self.key_file.setText(path)

    def _start(self) -> None:
        host = self.host.text().strip()
        username = self.username.text().strip() or get_text("ssh_username_default")
        key_file = self.key_file.text().strip() or None
        key_pass = self.key_pass.text()
        iface = (self.iface.currentText() or "").strip() or get_option("ssh_interfaces", ["can0"])[0]
        normalize = bool(self._normalize_getter())

        if not host:
            self.status.setText(get_text("ssh_host_required"))
            return

        self._vm.start(
            host=host,
            username=username,
            key_file=key_file,
            key_passphrase=key_pass or None,
            iface=iface,
            normalize=normalize,
        )

    def _stop(self) -> None:
        self._vm.stop()

    def _on_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)

    def _on_error(self, message: str) -> None:
        self.status.setText(get_text("ssh_error_prefix").format(error=message))

    def closeEvent(self, event) -> None:
        self._vm.stop()
        super().closeEvent(event)
