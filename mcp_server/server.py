from __future__ import annotations

import logging
import os
from pathlib import Path

from mcp.server import MCPServer
from pydantic import BaseModel, Field

from mcp_server.session_client import McpSessionClient
from mcp_server.plugin_context import McpPluginContext
from mcp_server.tools import CanlyticsTools
from services.plugin_manager import PluginManager


class TimeValueConstraint(BaseModel):
    """A normalized signal value to check near an epoch timestamp."""

    time_abs: float = Field(description="Absolute log timestamp in epoch seconds")
    target_norm: float = Field(ge=0.0, le=1.0, description="Target normalized between 0.0 and 1.0")


class CanlyticsMCPServer(MCPServer):
    """MCP server that owns activated plugin resources for process lifetime."""

    plugin_manager: PluginManager

    def shutdown_plugins(self) -> None:
        self.plugin_manager.shutdown()


def build_server(
    *, allow_can_send: bool = False, plugin_manager: PluginManager | None = None
) -> MCPServer:
    """Register Canlytics tools on the official MCP server implementation."""
    tools = CanlyticsTools(allow_can_send=allow_can_send)
    session_client = McpSessionClient()
    server = CanlyticsMCPServer("Canlytics")
    configured_state = os.environ.get("CANLYTICS_PLUGIN_STATE", "").strip()
    state_path = (
        Path(configured_state).expanduser()
        if configured_state
        else Path.cwd() / ".canlytics_state" / "plugins.json"
    )
    manager = plugin_manager or PluginManager(state_path)

    @server.tool()
    def load_log(path: str, normalize_time: bool = False) -> dict:
        """Load one candump, Kvaser, ASC, BLF, TRC, or CSV log read-only."""
        return tools.load_log(path, normalize_time=normalize_time)

    @server.tool()
    def list_ids() -> list[str]:
        """List CAN IDs in the currently loaded log."""
        return tools.list_ids()

    @server.tool()
    def id_stats(can_id: str) -> dict:
        """Return frame count, lengths, buses and time bounds for a CAN ID."""
        return tools.id_stats(can_id)

    @server.tool()
    def find_candidates(
        can_ids: list[str] | None = None,
        min_length: int = 8,
        max_length: int = 8,
        granularity: int = 8,
        limit: int = 100,
    ) -> list[dict]:
        """Find likely signal interpretations for one or more CAN IDs."""
        return tools.find_candidates(can_ids, min_length, max_length, granularity, limit)

    @server.tool()
    def diff_ranges(start_a: float, end_a: float, start_b: float, end_b: float) -> dict:
        """Compare two inclusive timestamp ranges in the loaded log."""
        return tools.diff_ranges(start_a, end_a, start_b, end_b)

    @server.tool()
    def constraint_search(
        constraints: list[TimeValueConstraint],
        can_ids: list[str] | None = None,
        precision: float = 0.1,
        tolerance: float = 0.1,
        limit: int = 100,
    ) -> dict:
        """Search candidates for normalized values near absolute timestamps."""
        return tools.constraint_search(
            [constraint.model_dump() for constraint in constraints],
            can_ids, precision, tolerance, limit,
        )

    @server.tool()
    def export_log(
        filename: str,
        scope: str = "all",
        can_ids: list[str] | None = None,
        ts_min: float | None = None,
        ts_max: float | None = None,
    ) -> dict:
        """Export a standard .log, .asc, .blf, .trc, or .csv under the MCP output folder."""
        return tools.export_log(filename, scope, can_ids, ts_min, ts_max)

    @server.tool()
    def save_signals(filename: str, signals: list[dict]) -> dict:
        """Save signal definitions as JSON under the MCP output folder."""
        return tools.save_signals(filename, signals)

    @server.tool()
    def save_markers(filename: str, markers: list[dict]) -> dict:
        """Save named timestamp markers as JSON under the MCP output folder."""
        return tools.save_markers(filename, markers)

    @server.tool()
    def get_open_session() -> dict:
        """Return status and metadata for the currently open Canlytics desktop session."""
        return session_client.get_open_session()

    @server.tool()
    def get_recent_frames(
        limit: int = 100,
        can_id: str | None = None,
        ts_min: float | None = None,
        ts_max: float | None = None,
    ) -> dict:
        """Read up to 500 recent frames from the open app session."""
        return session_client.get_recent_frames(limit=limit, can_id=can_id, ts_min=ts_min, ts_max=ts_max)

    @server.tool()
    def get_analysis_context() -> dict:
        """Return the app's current AnalysisContext, if one has been selected."""
        return session_client.get_analysis_context()

    @server.tool()
    def add_session_marker(name: str, timestamp: float | None = None) -> dict:
        """Add an in-memory marker to the open app session at an absolute epoch timestamp."""
        return session_client.add_session_marker(name, timestamp)

    @server.tool()
    def list_session_markers() -> dict:
        """List in-memory markers created during the open app session."""
        return session_client.list_session_markers()

    @server.tool()
    def decode_with_dbc(can_id: str, data_hex: str) -> dict:
        """Decode a classic CAN payload with the DBCs active in the open app."""
        return session_client.decode_with_dbc(can_id, data_hex)

    @server.tool()
    def save_signal_to_working_dbc(
        can_id: str,
        signal_name: str,
        start: int,
        length: int,
        message_name: str | None = None,
        message_length: int | None = None,
        byte_order: str = "little_endian",
        is_signed: bool = False,
        scale: float = 1.0,
        offset: float = 0.0,
        unit: str | None = None,
        minimum: float | None = None,
        maximum: float | None = None,
        is_float: bool = False,
        multiplexer_signal: str | None = None,
        multiplexer_ids: list[int] | None = None,
        comment: str | None = None,
    ) -> dict:
        """Add a validated signal to the app's persistent Working DBC."""
        return session_client.save_signal_to_working_dbc({
            "can_id": can_id,
            "signal_name": signal_name,
            "start": start,
            "length": length,
            "message_name": message_name,
            "message_length": message_length,
            "byte_order": byte_order,
            "is_signed": is_signed,
            "scale": scale,
            "offset": offset,
            "unit": unit,
            "minimum": minimum,
            "maximum": maximum,
            "is_float": is_float,
            "multiplexer_signal": multiplexer_signal,
            "multiplexer_ids": multiplexer_ids,
            "comment": comment,
        })

    if allow_can_send:
        @server.tool()
        def send_frame(
            channel: str,
            can_id: int,
            data_hex: str,
            interface: str = "socketcan",
            extended: bool = False,
        ) -> dict:
            """Send one classic CAN frame; this tool exists only with --allow-can-send."""
            return tools.send_frame(channel, can_id, data_hex, interface, extended)

    plugin_context = McpPluginContext(tools)
    for record in manager.discover():
        if record.enabled:
            manager.set_enabled(record.id, True, plugin_context)
    for tool_name, (plugin_id, callback, description) in manager.mcp_extensions().items():
        try:
            server.add_tool(callback, name=tool_name, description=description)
        except Exception:
            logging.getLogger(__name__).exception(
                "Plugin %s MCP tool %s could not be registered", plugin_id, tool_name
            )
    server.plugin_manager = manager

    return server
