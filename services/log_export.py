from __future__ import annotations

import os
from pathlib import Path
import uuid
from collections.abc import Callable, Iterable

import polars as pl

from config.app_config import get_text
from services.table_filter import apply_time_range


class ExportCancelled(Exception):
    """Raised when the export worker is asked to stop before completion."""


def select_export_frames(
    dataframe: pl.DataFrame,
    scope: str,
    *,
    selected_ids: Iterable[str] = (),
    ts_min: float | None = None,
    ts_max: float | None = None,
) -> pl.DataFrame:
    """Select a complete log, the current table filter, or a time range."""
    if scope == "all":
        return dataframe
    if scope == "range":
        if ts_min is None and ts_max is None:
            raise ValueError(get_text("log_export_range_required"))
        return apply_time_range(dataframe, ts_min, ts_max)
    if scope != "filtered":
        raise ValueError(get_text("log_export_scope_invalid").format(scope=scope))
    filtered = apply_time_range(dataframe, ts_min, ts_max)
    ids = set(selected_ids)
    if not ids or "ID" not in filtered.columns:
        return filtered.head(0)
    return filtered.filter(pl.col("ID").is_in(ids))


def export_dataframe(
    dataframe: pl.DataFrame,
    path: str | Path,
    *,
    progress_callback: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    protected_paths: Iterable[str | Path] = (),
) -> Path:
    """Write CAN frames atomically through the python-can format writers."""
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix not in {".log", ".asc", ".blf", ".trc", ".csv"}:
        raise ValueError(get_text("log_export_format_invalid").format(suffix=suffix or "(no extension)"))
    if dataframe.is_empty():
        raise ValueError(get_text("connection_no_data_to_save"))
    if suffix == ".csv" and "Bus" in dataframe.columns and dataframe["Bus"].n_unique() > 1:
        raise ValueError(get_text("log_export_csv_multibus"))
    target_resolved = target.resolve()
    if any(Path(source).resolve() == target_resolved for source in protected_paths):
        raise ValueError(get_text("log_export_source_protected"))

    import can

    temporary = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.tmp{suffix}")
    writer = None
    channels: dict[str, int] = {}
    total = dataframe.height
    update_every = max(1, total // 1000)
    try:
        writer = can.Logger(temporary)
        rows = dataframe.select(["TS", "Bus", "ID", "DATA"]).iter_rows()
        for completed, (timestamp, bus, can_id, data) in enumerate(rows, start=1):
            if should_cancel is not None and should_cancel():
                raise ExportCancelled()
            bus_name = str(bus or "can0")
            if suffix == ".log":
                channel: str | int | None = bus_name
            elif suffix == ".csv":
                channel = None
            else:
                channel = channels.setdefault(bus_name, len(channels))
            identifier = int(str(can_id), 16)
            writer.on_message_received(can.Message(
                timestamp=float(timestamp or 0.0),
                arbitration_id=identifier,
                is_extended_id=identifier > 0x7FF,
                data=bytes.fromhex(str(data or "")),
                channel=channel,
            ))
            if progress_callback is not None and (completed % update_every == 0 or completed == total):
                progress_callback(completed, total)
        if should_cancel is not None and should_cancel():
            raise ExportCancelled()
        writer.stop()
        writer = None
        os.replace(temporary, target)
        return target
    except BaseException:
        if writer is not None:
            try:
                writer.stop()
            except Exception:
                pass
        temporary.unlink(missing_ok=True)
        raise
