from __future__ import annotations

from dataclasses import dataclass

import socket
import paramiko


class SshCanceled(RuntimeError):
    pass


@dataclass(frozen=True)
class SshAuth:
    username: str
    key_file: str | None = None
    key_passphrase: str | None = None
    password: str | None = None


class RemoteConnection:
    def __init__(self, hostname: str, auth: SshAuth, port: int = 22):
        self.hostname = hostname
        self.auth = auth
        self.port = port
        self.client: paramiko.SSHClient | None = None
        self._sock: socket.socket | None = None

    def cancel(self) -> None:
        try:
            if self._sock:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    self._sock.close()
                except Exception:
                    pass
        finally:
            self._sock = None
        self.close()

    def open(self, *, cancel_check=None) -> None:
        if cancel_check and cancel_check():
            raise SshCanceled()
        sock = socket.create_connection((self.hostname, self.port), timeout=1.0)
        self._sock = sock

        if cancel_check and cancel_check():
            self.cancel()
            raise SshCanceled()

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        client.connect(
            hostname=self.hostname,
            port=self.port,
            username=self.auth.username,
            password=self.auth.password,
            key_filename=self.auth.key_file,
            passphrase=self.auth.key_passphrase or None,
            sock=sock,
            look_for_keys=True,
            allow_agent=True,
            timeout=1.0,
            banner_timeout=1.0,
            auth_timeout=1.0,
        )

        transport = client.get_transport()
        if transport:
            transport.set_keepalive(30)

        self.client = client
        self._sock = None

    def exec_stream(self, command: str) -> paramiko.Channel:
        if not self.client:
            raise RuntimeError("SSH client not connected")
        transport = self.client.get_transport()
        if not transport:
            raise RuntimeError("SSH transport not available")

        channel = transport.open_session()
        channel.get_pty()
        channel.exec_command(command)
        channel.settimeout(0.0)
        return channel

    def close(self) -> None:
        if self.client:
            try:
                self.client.close()
            finally:
                self.client = None
