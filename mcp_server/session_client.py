from __future__ import annotations

import json
import os
from multiprocessing.connection import Client
from pathlib import Path


_MAX_RESPONSE_BYTES = 1_048_576


class McpSessionUnavailable(RuntimeError):
    """The desktop app does not have a reachable MCP session endpoint."""


class McpSessionClient:
    """Read the app's private local-session descriptor and request one bounded response."""

    def __init__(self, *, endpoint_path: str | Path | None = None, timeout: float = 2.0):
        configured_path = endpoint_path or os.environ.get("CANLYTICS_MCP_SESSION_FILE")
        self._endpoint_path = Path(configured_path).expanduser() if configured_path else (
            Path.home() / ".canlytics" / "mcp" / "session-endpoint.json"
        )
        self._timeout = float(timeout)
        if self._timeout <= 0:
            raise ValueError("timeout must be positive")

    def request(self, method: str, params: dict | None = None, *, timeout: float | None = None) -> dict:
        descriptor = self._read_descriptor()
        connection = None
        try:
            connection = Client(
                descriptor["address"],
                family=descriptor["family"],
                authkey=bytes.fromhex(descriptor["authkey"]),
            )
            payload = json.dumps({"method": method, "params": params or {}}, allow_nan=False).encode("utf-8")
            connection.send_bytes(payload)
            if not connection.poll(self._timeout if timeout is None else timeout):
                raise TimeoutError("Canlytics session request timed out")
            response = json.loads(connection.recv_bytes(maxlength=_MAX_RESPONSE_BYTES).decode("utf-8"))
        except (OSError, EOFError, TimeoutError, ValueError, KeyError) as exc:
            raise McpSessionUnavailable("Canlytics session is unavailable") from exc
        finally:
            if connection is not None:
                connection.close()
        if not isinstance(response, dict) or not isinstance(response.get("ok"), bool):
            raise McpSessionUnavailable("Canlytics returned an invalid session response")
        if not response["ok"]:
            error = response.get("error") or {}
            raise ValueError(str(error.get("message") or "Invalid session request"))
        result = response.get("result")
        if not isinstance(result, dict):
            raise McpSessionUnavailable("Canlytics returned an invalid session result")
        return result

    def get_open_session(self) -> dict:
        try:
            return {"connected": True, **self.request("get_open_session")}
        except McpSessionUnavailable as exc:
            return {"connected": False, "message": str(exc)}

    def get_recent_frames(
        self,
        *,
        limit: int = 100,
        can_id: str | None = None,
        ts_min: float | None = None,
        ts_max: float | None = None,
    ) -> dict:
        params = {"limit": limit, "can_id": can_id, "ts_min": ts_min, "ts_max": ts_max}
        return self.request("get_recent_frames", params)

    def get_analysis_context(self) -> dict:
        return self.request("get_analysis_context")

    def add_session_marker(self, name: str, timestamp: float | None = None) -> dict:
        return self.request("add_session_marker", {"name": name, "timestamp": timestamp})

    def list_session_markers(self) -> dict:
        return self.request("list_session_markers")

    def decode_with_dbc(self, can_id: str, data_hex: str) -> dict:
        return self.request("decode_with_dbc", {"can_id": can_id, "data_hex": data_hex}, timeout=60.0)

    def save_signal_to_working_dbc(self, params: dict) -> dict:
        return self.request("save_signal_to_working_dbc", params, timeout=60.0)

    def _read_descriptor(self) -> dict:
        try:
            descriptor = json.loads(self._endpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise McpSessionUnavailable("Canlytics is not publishing an open session") from exc
        if not isinstance(descriptor, dict) or not all(
            isinstance(descriptor.get(key), str) and descriptor[key]
            for key in ("address", "family", "authkey")
        ):
            raise McpSessionUnavailable("Canlytics session descriptor is invalid")
        return descriptor
