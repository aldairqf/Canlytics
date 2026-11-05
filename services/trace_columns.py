from __future__ import annotations

import polars as pl

DEFAULT_TRACE_PREFERENCES = {
    "data_mode": "hex",
    "show_delta_t": False,
    "show_name": False,
}


def normalize_trace_preferences(preferences: dict[str, object] | None) -> dict[str, bool | str]:
    """Validate persisted trace preferences and fill defaults for older sessions."""
    values = preferences if isinstance(preferences, dict) else {}
    mode = str(values.get("data_mode", DEFAULT_TRACE_PREFERENCES["data_mode"])).strip().lower()
    if mode not in {"hex", "dec", "bits"}:
        mode = str(DEFAULT_TRACE_PREFERENCES["data_mode"])
    show_delta_t = values.get("show_delta_t", DEFAULT_TRACE_PREFERENCES["show_delta_t"])
    show_name = values.get("show_name", DEFAULT_TRACE_PREFERENCES["show_name"])
    return {
        "data_mode": mode,
        "show_delta_t": show_delta_t if isinstance(show_delta_t, bool) else False,
        "show_name": show_name if isinstance(show_name, bool) else False,
    }


def calculate_delta_t(dataframe: pl.DataFrame) -> list[float | None]:
    """Return time since the prior frame of the same ID in source row order."""
    if dataframe.is_empty() or not {"ID", "TS"}.issubset(dataframe.columns):
        return [None] * dataframe.height
    delta_column = "__trace_delta_t"
    result = dataframe.with_columns(pl.col("TS").diff().over("ID").alias(delta_column))
    return [None if value is None else float(value) for value in result[delta_column].to_list()]


def calculate_appended_delta_t(
    dataframe: pl.DataFrame,
    previous_timestamps: dict[str, float],
) -> tuple[list[float | None], dict[str, float]]:
    """Calculate append deltas in O(chunk), updating the last timestamp per ID."""
    if dataframe.is_empty() or not {"ID", "TS"}.issubset(dataframe.columns):
        return [None] * dataframe.height, dict(previous_timestamps)
    last = dict(previous_timestamps)
    deltas: list[float | None] = []
    for can_id, timestamp in zip(dataframe["ID"].to_list(), dataframe["TS"].to_list()):
        if can_id is None or timestamp is None:
            deltas.append(None)
            continue
        key = str(can_id)
        value = float(timestamp)
        previous = last.get(key)
        deltas.append(None if previous is None else value - previous)
        last[key] = value
    return deltas, last


def last_timestamps_by_id(dataframe: pl.DataFrame) -> dict[str, float]:
    """Return the last source-order timestamp per ID with work proportional to ID count."""
    if dataframe.is_empty() or not {"ID", "TS"}.issubset(dataframe.columns):
        return {}
    last_values = dataframe.group_by("ID", maintain_order=True).agg(pl.col("TS").last())
    return {
        str(can_id): float(timestamp)
        for can_id, timestamp in last_values.iter_rows()
        if can_id is not None and timestamp is not None
    }
