from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from services.remote_connection import SshAuth
from services.ssh_time_poll import SshTimePoller


class _SshTimePollWorker(QObject):
    time_ready = QtSignal(float)
    finished = QtSignal()

    def __init__(self, poller: SshTimePoller):
        super().__init__()
        self._poller = poller

    def run(self) -> None:
        try:
            self._poller.run(self.time_ready.emit)
        finally:
            self.finished.emit()

    def stop(self) -> None:
        self._poller.stop()


class SshTimePollViewModel(QObject):
    """Own the SSH timestamp polling worker for the connection dialog."""

    time_ready = QtSignal(float)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _SshTimePollWorker | None = None

    def start(
        self,
        host: str,
        username: str,
        key_file: str | None,
        key_passphrase: str | None,
        iface: str,
    ) -> None:
        self.stop()
        if self._thread is not None:
            return
        thread = QThread(self)
        auth = SshAuth(username=username, key_file=key_file, key_passphrase=key_passphrase)
        worker = _SshTimePollWorker(SshTimePoller(host, auth, iface))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.time_ready.connect(self.time_ready.emit)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    def stop(self) -> None:
        thread = self._thread
        worker = self._worker
        if thread is None:
            return
        if worker is not None and thread.isRunning():
            worker.stop()
        thread.quit()
        if thread.wait(2000):
            self._thread = None
            self._worker = None

    def _on_thread_finished(self) -> None:
        if self.sender() == self._thread:
            self._thread = None
            self._worker = None
