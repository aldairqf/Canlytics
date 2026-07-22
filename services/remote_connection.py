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

        # When a key file is explicitly given, disable look_for_keys and the
        # SSH agent so paramiko doesn't exhaust MaxAuthTries probing unrelated
        # keys from ~/.ssh/ before reaching the specified one.
        # Mirrors: ssh -o PubkeyAcceptedAlgorithms=+ssh-rsa — needed for older
        # embedded SSH servers that don't support SHA-2 RSA signatures.
        has_key = bool(self.auth.key_file or self.auth.password)
        client.connect(
            hostname=self.hostname,
            port=self.port,
            username=self.auth.username,
            password=self.auth.password,
            key_filename=self.auth.key_file,
            passphrase=self.auth.key_passphrase or None,
            sock=sock,
            look_for_keys=not has_key,
            allow_agent=not has_key,
            timeout=10.0,
            banner_timeout=10.0,
            auth_timeout=10.0,
            disabled_algorithms={"pubkeys": ["rsa-sha2-256", "rsa-sha2-512"]},
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

    def exec_once(self, command: str, *, timeout: float = 5.0) -> tuple[int, bytes, bytes]:
        """One-off blocking remote command -> (exit_status, stdout, stderr).

        Mirrors exec_stream (own transport.open_session()) but skips get_pty()
        -- a PTY merges stdout/stderr and mangles exit-status semantics for
        tools that report failure only via exit code. Must only be called
        from the thread that already owns this connection's other channel(s)
        -- paramiko multiplexes channels over one transport safely only when
        driven from a single thread.
        """
        if not self.client:
            raise RuntimeError("SSH client not connected")
        transport = self.client.get_transport()
        if not transport:
            raise RuntimeError("SSH transport not available")

        channel = transport.open_session()
        try:
            channel.settimeout(timeout)
            channel.exec_command(command)
            exit_status = channel.recv_exit_status()
            stdout = b""
            while channel.recv_ready():
                stdout += channel.recv(4096)
            stderr = b""
            while channel.recv_stderr_ready():
                stderr += channel.recv_stderr(4096)
            return exit_status, stdout, stderr
        finally:
            channel.close()

    def is_alive(self) -> bool:
        """Passive check -- reflects the last keepalive result, not necessarily current."""
        if not self.client:
            return False
        transport = self.client.get_transport()
        return bool(transport and transport.is_active())

    def ping(self) -> bool:
        """Actively probe the transport instead of waiting for the next passive keepalive."""
        if not self.is_alive():
            return False
        try:
            self.client.get_transport().send_ignore()
            return True
        except Exception:
            return False

    def close(self) -> None:
        if self.client:
            try:
                self.client.close()
            finally:
                self.client = None
