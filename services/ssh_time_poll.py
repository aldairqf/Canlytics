from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


class SshTimePoller:
    """Poll candump timestamps from a remote interface without Qt dependencies."""

    def __init__(self, host: str, auth: Any, iface: str):
        self._host = host
        self._auth = auth
        self._iface = iface
        self._stopped = False
        self._connection = None

    def run(self, emit_timestamp: Callable[[float], None]) -> None:
        connection = None
        try:
            from services.can_data_parser import parse_candump_line
            from services.remote_connection import RemoteConnection

            connection = RemoteConnection(self._host, self._auth)
            self._connection = connection
            connection.open(cancel_check=lambda: self._stopped)
            if self._stopped:
                return
            channel = connection.exec_stream(f"candump -ta {self._iface}")
            buffer = b""
            while not self._stopped:
                try:
                    if channel.recv_ready():
                        data = channel.recv(4096)
                        if data:
                            buffer += data
                except Exception:
                    break
                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    row = parse_candump_line(raw.decode("utf-8", errors="ignore").strip())
                    if row is not None:
                        emit_timestamp(float(row["TS"]))
                if not channel.recv_ready():
                    time.sleep(0.01)
        except Exception:
            pass
        finally:
            self._connection = None
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def stop(self) -> None:
        self._stopped = True
        connection = self._connection
        if connection is not None:
            try:
                connection.cancel()
            except Exception:
                pass
