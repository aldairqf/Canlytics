from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import polars as pl

from canlytics_sdk import DbcMessageInfo
from services.analyze_data import build_summary
from services.can_data_parser import FRAME_SCHEMA
from services.candidate_interpretations import build_candidate_items
from services.log_export import export_dataframe
from services.range_diff import TimeRange, build_range_diff_report


class _McpPluginAnalysis:
    def summarize(self, dataframe: pl.DataFrame, can_id: str | None = None) -> dict[str, Any]:
        selected = dataframe if can_id is None else dataframe.filter(pl.col("ID") == str(can_id))
        return build_summary(selected, can_id, (), "")

    def candidates(self, dataframe: pl.DataFrame, can_ids: set[str], **options: Any) -> list[Any]:
        values = {
            "min_length": 8,
            "max_length": 8,
            "granularity": 8,
            "endianness": "Little Endian",
            "value_type": "Unsigned",
            "include_constant": False,
        }
        values.update(options)
        mux_configs = list(values.pop("mux_configs", None) or [])
        return build_candidate_items(dataframe, checked_ids=set(can_ids), mux_configs=mux_configs, **values)

    def compare_ranges(
        self, dataframe: pl.DataFrame, start_a: float, end_a: float, start_b: float, end_b: float
    ) -> Any:
        return build_range_diff_report(dataframe, TimeRange(start_a, end_a), TimeRange(start_b, end_b))


class McpPluginContext:
    """Read-only plugin context for the headless MCP process."""

    def __init__(self, tools: Any):
        self._tools = tools
        self._analysis = _McpPluginAnalysis()

    @property
    def frame_schema(self) -> dict[str, str]:
        return {name: str(dtype) for name, dtype in FRAME_SCHEMA.items()}

    def get_frames(self) -> pl.DataFrame:
        return self._tools.dataframe.clone()

    def list_dbc_names(self) -> tuple[str, ...]:
        return ()

    def decode_frame(self, can_id: str, data_hex: str) -> tuple[dict[str, Any], ...]:
        return ()

    def get_working_dbc_messages(self) -> tuple[DbcMessageInfo, ...]:
        return ()

    @property
    def analysis(self) -> _McpPluginAnalysis:
        return self._analysis

    def export_log(self, dataframe: pl.DataFrame, path: str) -> str:
        target = self._tools._output_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        exported = export_dataframe(
            dataframe, target, protected_paths=[self._tools.source_path] if self._tools.source_path else ()
        )
        return str(exported)

    def list_session_markers(self) -> tuple[dict[str, Any], ...]:
        return ()

    def send_frame(self, can_id: int | str, data: bytes | str, *, extended: bool = False) -> str:
        raise PermissionError("Plugin frame transmission is unavailable in the headless MCP server")

    def subscribe_live_chunks(
        self, callback: Callable[[Any], None], *, lifetime: Any
    ) -> Callable[[], None]:
        raise RuntimeError("Live chunk subscriptions are unavailable in the headless MCP server")
