from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QFormLayout, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
    QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from config.app_config import get_option, get_text


class DiagnosticsWindow(QMainWindow):
    def __init__(self, vm, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("diagnostics_title"))
        self.resize(760, 460)
        self._vm = vm
        self._pending_messages = []
        self._pending_snapshot = None
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(int(get_option("diagnostics_flush_ms", 200)))
        self._flush_timer.timeout.connect(self._flush_updates)
        body = QWidget(self)
        layout = QVBoxLayout(body)
        self._errors = QLabel(self)
        layout.addWidget(self._errors)
        self._messages = QTableWidget(0, 4, self)
        self._messages.setHorizontalHeaderLabels([get_text(k) for k in
            ("diagnostics_protocol", "diagnostics_id", "diagnostics_service", "diagnostics_payload")])
        header = self._messages.horizontalHeader()
        for column in range(3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._messages, 1)
        controls = QHBoxLayout()
        self._pgn = QSpinBox(self); self._pgn.setRange(0, 0x3FFFF); self._pgn.setPrefix(get_text("diagnostics_pgn_prefix"))
        self._pid = QSpinBox(self); self._pid.setRange(0, 255); self._pid.setPrefix(get_text("diagnostics_pid_prefix"))
        self._pgn.setDisplayIntegerBase(16)
        self._pid.setDisplayIntegerBase(16)
        controls.addWidget(self._pgn)
        request_pgn = QPushButton(get_text("diagnostics_request_pgn"), self)
        request_pgn.clicked.connect(self._request_pgn)
        controls.addWidget(request_pgn)
        controls.addWidget(self._pid)
        request_pid = QPushButton(get_text("diagnostics_request_pid"), self)
        request_pid.clicked.connect(self._request_pid)
        controls.addWidget(request_pid)
        layout.addLayout(controls)
        self.setCentralWidget(body)
        vm.changed.connect(self._render_errors)
        vm.message_observed.connect(self._append_message)
        vm.history_loaded.connect(self._replace_history)
        self._render_errors(vm.snapshot, vm.transport_errors)
        self._flush_timer.start()
        for message in getattr(vm, "messages", ()):
            self._append_message(message)
        self._flush_updates()
        self.destroyed.connect(self._disconnect)

    def ingest_chunk(self, chunk) -> None:
        self._vm.ingest_chunk(chunk)

    def _render_errors(self, snapshot, transport_count: int) -> None:
        self._pending_snapshot = (snapshot, transport_count)

    def _render_error_snapshot(self, snapshot, transport_count: int) -> None:
        origins = ", ".join(f"{get_text('diagnostics_error_' + key, key)}: {value}"
                             for key, value in sorted(snapshot.counts.items())) or get_text("diagnostics_none")
        classes = ", ".join(f"{get_text('diagnostics_error_' + key, key)}: {value}"
                             for key, value in sorted(snapshot.classes.items())) or get_text("diagnostics_none")
        details = f"{get_text('diagnostics_error_origins').format(items=origins)} | {get_text('diagnostics_error_classes').format(items=classes)}"
        self._errors.setText(get_text("diagnostics_error_summary").format(
            total=snapshot.total, rate=snapshot.rate_per_minute, types=details,
            transport=transport_count, application=self._vm.application_errors))

    def _append_message(self, message: dict) -> None:
        self._pending_messages.append(message)

    def _replace_history(self, messages: list[dict]) -> None:
        self._messages.setRowCount(0)
        self._pending_messages = list(messages)

    def _flush_updates(self) -> None:
        if self._pending_snapshot is not None:
            self._render_error_snapshot(*self._pending_snapshot)
            self._pending_snapshot = None
        batch_size = max(1, int(get_option("diagnostics_ui_flush_batch_size", 250)))
        messages = self._pending_messages[:batch_size]
        del self._pending_messages[:batch_size]
        for message in messages:
            self._insert_message(message)

    def _insert_message(self, message: dict) -> None:
        row = self._messages.rowCount(); self._messages.insertRow(row)
        if message["protocol"] == "OBD":
            service = get_text("diagnostics_obd_mode_pid").format(mode=message["mode"], pid=message["pid"])
        else:
            service = get_text("diagnostics_uds_service").format(sid=message.get("sid", 0))
        if message.get("negative") and "nrc" in message:
            pending_text = get_text("diagnostics_response_pending") if message.get("response_pending") or message.get("nrc") == 0x78 else ""
            pending = f" ({pending_text})" if pending_text else ""
            service = get_text("diagnostics_nrc").format(nrc=int(message["nrc"]), pending=pending).rstrip()
        values = (message["protocol"], f"{message['can_id']:X}",
                  service, message["payload"])
        for column, value in enumerate(values):
            self._messages.setItem(row, column, QTableWidgetItem(str(value)))
        while self._messages.rowCount() > int(get_option("diagnostics_message_limit", 2000)):
            self._messages.removeRow(0)

    def _confirm(self, title: str) -> bool:
        answer = QMessageBox.question(self, get_text("diagnostics_confirm_title"),
            get_text("diagnostics_confirm_message").format(action=title))
        return answer == QMessageBox.StandardButton.Yes

    def _request_pgn(self) -> None:
        if self._confirm(get_text("diagnostics_request_pgn")):
            self._vm.request_j1939_pgn(self._pgn.value())

    def _request_pid(self) -> None:
        if self._confirm(get_text("diagnostics_request_pid")):
            self._vm.request_obd_pid(self._pid.value())

    def _disconnect(self) -> None:
        self._flush_timer.stop()
        try:
            self._vm.changed.disconnect(self._render_errors)
            self._vm.message_observed.disconnect(self._append_message)
            self._vm.history_loaded.disconnect(self._replace_history)
        except (RuntimeError, TypeError):
            pass
