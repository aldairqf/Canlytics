# path: views/settings/ssh_connection_dialog.py
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


class SshConnectionDialog(QDialog):
    def __init__(self, vm: SshCanStreamViewModel, *, normalize_getter, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SSH Connection")
        self._vm = vm
        self._normalize_getter = normalize_getter

        self.host = QLineEdit()
        self.host.setPlaceholderText("192.168.x.x")

        self.username = QLineEdit()
        self.username.setText("root")

        self.key_file = QLineEdit()
        self.key_file.setPlaceholderText("Select private key file")

        self.btn_browse = QPushButton("Browse")
        self.btn_browse.clicked.connect(self._browse_key)

        key_row = QHBoxLayout()
        key_row.addWidget(self.key_file, 1)
        key_row.addWidget(self.btn_browse)

        self.key_pass = QLineEdit()
        self.key_pass.setEchoMode(QLineEdit.Password)

        self.iface = QComboBox()
        self.iface.setEditable(True)
        self.iface.addItems(["can0", "can1"])
        self.iface.setCurrentText("can0")

        self.btn_start = QPushButton("Start")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)

        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)

        self.status = QLabel("Idle")
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)

        form = QFormLayout()
        form.addRow("IP/Host", self.host)
        form.addRow("Username", self.username)
        form.addRow("Key file", key_row)
        form.addRow("Key passphrase", self.key_pass)
        form.addRow("CAN interface", self.iface)
        form.addRow("Status", self.status)

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
        path, _ = QFileDialog.getOpenFileName(self, "Select private key", "", "Key files (*);;All files (*)")
        if path:
            self.key_file.setText(path)

    def _start(self) -> None:
        host = self.host.text().strip()
        username = self.username.text().strip() or "root"
        key_file = self.key_file.text().strip() or None
        key_pass = self.key_pass.text()
        iface = (self.iface.currentText() or "").strip() or "can0"
        normalize = bool(self._normalize_getter())

        if not host:
            self.status.setText("Host required")
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
        self.status.setText(f"Error: {message}")

    def closeEvent(self, event) -> None:
        self._vm.stop()
        super().closeEvent(event)
