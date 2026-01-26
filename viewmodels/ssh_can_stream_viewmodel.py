from __future__ import annotations

import time
from typing import Optional

import polars as pl
from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from core.candump_parser import CandumpParser
from core.remote_connection import RemoteConnection, SshAuth, SshCanceled



class _SshCanStreamWorker(QObject):
    status = QtSignal(str)
    error = QtSignal(str)
    chunk_ready = QtSignal(object)
    finished = QtSignal()

    def __init__(
        self,
        *,
        host: str,
        username: str,
        key_file: str | None,
        key_passphrase: str | None,
        iface: str,
        normalize: bool,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._host = host
        self._username = username
        self._key_file = key_file or None
        self._key_passphrase = key_passphrase or None
        self._iface = iface
        self._normalize = normalize

        self._stop = False
        self._conn: Optional[RemoteConnection] = None
        self._channel = None

    def stop(self) -> None:
        self._stop = True
        try:
            if self._conn:
                self._conn.cancel()
        except Exception:
            pass
        try:
            if self._channel:
                self._channel.close()
        except Exception:
            pass

    def run(self) -> None:
        try:
            self.status.emit("Connecting...")
            auth = SshAuth(username=self._username, key_file=self._key_file, key_passphrase=self._key_passphrase)
            self._conn = RemoteConnection(self._host, auth)
            self._conn.open(cancel_check=lambda: self._stop)

            if self._stop:
                self.status.emit("Stopped")
                return

            cmd = f"candump -ta {self._iface}"
            self.status.emit(f"Streaming: {cmd}")
            self._channel = self._conn.exec_stream(cmd)

            parser = CandumpParser(normalize_time=self._normalize)

            buf = b""
            rows: list[dict] = []
            last_flush = time.monotonic()
            batch_size = 200
            flush_interval = 0.05

            while not self._stop:
                if self._channel is None or self._channel.closed:
                    break

                got_data = False
                try:
                    if self._channel.recv_ready():
                        data = self._channel.recv(4096)
                        if data:
                            buf += data
                            got_data = True
                except Exception:
                    pass

                while b"\n" in buf:
                    raw_line, buf = buf.split(b"\n", 1)
                    line = raw_line.decode("utf-8", errors="ignore")
                    row = parser.parse_line(line)
                    if row:
                        rows.append(row)

                now = time.monotonic()
                if rows and (len(rows) >= batch_size or (now - last_flush) >= flush_interval):
                    self.chunk_ready.emit(self._rows_to_df(rows))
                    rows.clear()
                    last_flush = now

                if not got_data:
                    time.sleep(0.01)

            if rows:
                self.chunk_ready.emit(self._rows_to_df(rows))

            self.status.emit("Stopped")
        except SshCanceled:
            self.status.emit("Stopped")
        except Exception as e:
            if self._stop:
                self.status.emit("Stopped")
            else:
                self.error.emit(str(e))
        finally:
            try:
                if self._channel:
                    self._channel.close()
            except Exception:
                pass
            try:
                if self._conn:
                    self._conn.close()
            except Exception:
                pass
            self.finished.emit()

    @staticmethod
    def _rows_to_df(rows: list[dict]) -> pl.DataFrame:
        schema = {
            "TS": pl.Float64,
            "Bus": pl.Utf8,
            "ID": pl.Utf8,
            "DATA": pl.Utf8,
            "LEN": pl.Int64,
            "B0": pl.Utf8,
            "B1": pl.Utf8,
            "B2": pl.Utf8,
            "B3": pl.Utf8,
            "B4": pl.Utf8,
            "B5": pl.Utf8,
            "B6": pl.Utf8,
            "B7": pl.Utf8,
            "D0": pl.Int64,
            "D1": pl.Int64,
            "D2": pl.Int64,
            "D3": pl.Int64,
            "D4": pl.Int64,
            "D5": pl.Int64,
            "D6": pl.Int64,
            "D7": pl.Int64,
        }
        cols = {k: [] for k in schema.keys()}
        for r in rows:
            for k in cols.keys():
                cols[k].append(r.get(k))
        return pl.DataFrame(cols, schema=schema) 
    
class SshCanStreamViewModel(QObject):
    running_changed = QtSignal(bool)
    status_changed = QtSignal(str)
    error = QtSignal(str)
    chunk_ready = QtSignal(object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._worker: Optional[_SshCanStreamWorker] = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(
        self,
        *,
        host: str,
        username: str,
        key_file: str | None,
        key_passphrase: str | None,
        iface: str,
        normalize: bool,
    ) -> None:
        if self._thread and self._thread.isRunning():
            return

        self._worker = _SshCanStreamWorker(
            host=host,
            username=username,
            key_file=key_file,
            key_passphrase=key_passphrase,
            iface=iface,
            normalize=normalize,
        )
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.status.connect(self.status_changed.emit)
        self._worker.error.connect(self.error.emit)
        self._worker.chunk_ready.connect(self.chunk_ready.emit)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup)

        self._running = True
        self.running_changed.emit(True)
        self._thread.start()

    def stop(self) -> None:
        if self._worker:
            self._worker.stop()

    def shutdown(self) -> None:
        self.stop()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)

    def _cleanup(self) -> None:
        self._running = False
        self.running_changed.emit(False)
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        if self._thread:
            self._thread.deleteLater()
            self._thread = None
