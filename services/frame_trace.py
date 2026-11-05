"""Incremental byte-change annotation and content filters for CAN traces."""

from __future__ import annotations

import polars as pl

from models.trace_filter import TraceFilter
from utils.can_bytes import parse_hex_bytes


class ChangedBytesTracker:
    """Track each ID's preceding payload while consuming ordered chunks."""

    def __init__(self) -> None:
        self._previous: dict[str, bytes] = {}

    def reset(self) -> None:
        self._previous.clear()

    def annotate(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        """Return a copy with byte offsets changed from the preceding same-ID frame."""
        if dataframe.is_empty() or not {"ID", "DATA"}.issubset(dataframe.columns):
            return dataframe.with_columns(pl.lit("").alias("_ChangedBytes"))
        if not self._previous:
            annotated = _annotate_full_dataframe(dataframe)
            last_rows = dataframe.group_by("ID", maintain_order=True).last().select("ID", "DATA")
            self._previous = {
                str(can_id): parse_hex_bytes("".join(str(data or "").split()))
                for can_id, data in last_rows.iter_rows()
            }
            return annotated
        changed: list[str] = []
        for can_id, data in dataframe.select("ID", "DATA").iter_rows():
            key = str(can_id)
            payload = parse_hex_bytes("".join(str(data or "").split()))
            previous = self._previous.get(key)
            offsets = (
                [
                    index
                    for index in range(max(len(previous), len(payload)))
                    if index >= len(previous) or index >= len(payload) or previous[index] != payload[index]
                ]
                if previous is not None
                else []
            )
            changed.append(",".join(str(index) for index in offsets))
            self._previous[key] = payload
        if "_ChangedBytes" in dataframe.columns:
            dataframe = dataframe.drop("_ChangedBytes")
        return dataframe.with_columns(pl.Series("_ChangedBytes", changed, dtype=pl.String))


def filter_trace_rows(dataframe: pl.DataFrame, filters: TraceFilter) -> pl.DataFrame:
    """Apply content filters to one trace slice."""
    if dataframe.is_empty() or filters == TraceFilter():
        return dataframe
    predicate = pl.lit(True)
    if filters.only_changes:
        if "_ChangedBytes" not in dataframe.columns:
            return dataframe.head(0)
        predicate &= pl.col("_ChangedBytes").str.len_chars() > 0
    if filters.dlc is not None:
        if "LEN" not in dataframe.columns:
            return dataframe.head(0)
        predicate &= pl.col("LEN") == filters.dlc
    if filters.byte_index is not None or filters.value is not None or filters.mask is not None:
        if "DATA" not in dataframe.columns:
            return dataframe.head(0)
        payload = pl.col("DATA").cast(pl.String).str.replace_all(r"\s+", "")
        indices = range(8) if filters.byte_index is None else (filters.byte_index,)
        matches = []
        for index in indices:
            if index < 0 or index >= 8:
                continue
            byte_value = payload.str.slice(index * 2, 2).str.to_integer(base=16, strict=False)
            if filters.value is not None:
                mask = 0xFF if filters.mask is None else filters.mask
                matches.append(byte_value.is_not_null() & ((byte_value & pl.lit(mask)) == (filters.value & mask)))
            elif filters.mask is not None:
                matches.append(byte_value.is_not_null() & ((byte_value & pl.lit(filters.mask)) != 0))
            else:
                matches.append(byte_value.is_not_null())
        if not matches:
            return dataframe.head(0)
        predicate &= pl.any_horizontal(matches)
    return dataframe.filter(predicate)


def _annotate_full_dataframe(dataframe: pl.DataFrame) -> pl.DataFrame:
    """Annotate a replacement source with Polars expressions in one native pass."""
    working = dataframe.with_columns(
        pl.col("DATA").cast(pl.String).str.replace_all(r"\s+", "").alias("__trace_payload")
    ).with_columns(
        pl.col("__trace_payload").shift(1).over("ID").alias("__trace_previous")
    )
    changed_positions = []
    for index in range(8):
        current = pl.col("__trace_payload").str.slice(index * 2, 2)
        previous = pl.col("__trace_previous").str.slice(index * 2, 2)
        changed = pl.col("__trace_previous").is_not_null() & (current != previous)
        changed_positions.append(pl.when(changed).then(pl.lit(str(index))).otherwise(None))
    working = working.with_columns(
        pl.concat_str(changed_positions, separator=",", ignore_nulls=True)
        .fill_null("")
        .alias("_ChangedBytes")
    )
    return working.drop("__trace_payload", "__trace_previous")
