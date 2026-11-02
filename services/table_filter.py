"""Pure incremental filtering for the main table's history dataframe.

Only for append-only growth (the "history" source). NOT for the "live"
source (real-time analysis's bounded, in-place-updated table) -- a row-count
watermark would miss in-place value changes there.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl


_RECHUNK_EVERY_APPENDS = 20


def apply_time_range(df: pl.DataFrame, ts_min: float | None, ts_max: float | None) -> pl.DataFrame:
    if df is None or df.is_empty() or "TS" not in df.columns:
        return df
    filtered = df
    if ts_min is not None:
        filtered = filtered.filter(pl.col("TS") >= float(ts_min))
    if ts_max is not None:
        filtered = filtered.filter(pl.col("TS") <= float(ts_max))
    return filtered


@dataclass
class IncrementalTableFilter:
    """Running state for one growing source dataframe."""

    cached_height: int = 0
    cached_filtered: pl.DataFrame | None = None
    cached_columns: list[str] | None = None
    seen_ids: set = field(default_factory=set)
    append_count: int = 0

    def reset(self) -> None:
        self.cached_height = 0
        self.cached_filtered = None
        self.cached_columns = None
        self.seen_ids = set()
        self.append_count = 0

    def apply(
        self,
        source: pl.DataFrame | None,
        *,
        selected_ids: set,
        ts_min: float | None,
        ts_max: float | None,
    ) -> tuple[pl.DataFrame, list[str], bool]:
        """Fold in rows new since the last call. Returns (filtered_df, all
        distinct IDs seen so far (sorted), whether the ID set changed)."""
        if source is None:
            empty = self.cached_filtered if self.cached_filtered is not None else pl.DataFrame()
            return empty, sorted(self.seen_ids), False

        if "ID" not in source.columns:
            self.reset()
            return source.head(0), [], bool(self.seen_ids)

        height = source.height
        if height < self.cached_height or (
            self.cached_columns is not None and source.columns != self.cached_columns
        ):
            # Shrank or schema changed -- not append-only growth of the same frame.
            self.reset()
        self.cached_columns = source.columns

        new_slice = source.slice(self.cached_height, height - self.cached_height)
        self.cached_height = height
        new_slice = apply_time_range(new_slice, ts_min, ts_max)

        ids_changed = False
        if not new_slice.is_empty():
            new_ids = set(new_slice["ID"].unique().to_list())
            added = new_ids - self.seen_ids
            if added:
                self.seen_ids |= added
                ids_changed = True

        if not selected_ids:
            filtered_slice = new_slice.head(0)
        else:
            filtered_slice = new_slice.filter(pl.col("ID").is_in(selected_ids))

        self._append_filtered(filtered_slice)

        return self.cached_filtered, sorted(self.seen_ids), ids_changed

    def append(
        self,
        delta: pl.DataFrame,
        *,
        selected_ids: set,
        ts_min: float | None,
        ts_max: float | None,
    ) -> tuple[pl.DataFrame, list[str], bool]:
        """Filter one new chunk and append its matching rows to the cache."""
        if "ID" not in delta.columns:
            self.reset()
            return delta.head(0), [], False
        if self.cached_columns is not None and delta.columns != self.cached_columns:
            self.reset()
        self.cached_columns = delta.columns
        if self.cached_filtered is None:
            self.cached_filtered = delta.head(0)
        self.cached_height += delta.height
        new_slice = apply_time_range(delta, ts_min, ts_max)
        new_ids = set(new_slice["ID"].unique().to_list()) if not new_slice.is_empty() else set()
        added = new_ids - self.seen_ids
        self.seen_ids.update(new_ids)
        if selected_ids:
            filtered_slice = new_slice.filter(pl.col("ID").is_in(selected_ids))
        else:
            filtered_slice = new_slice.head(0)
        self._append_filtered(filtered_slice)
        return filtered_slice, sorted(self.seen_ids), bool(added)

    def _append_filtered(self, filtered_slice: pl.DataFrame) -> None:
        if self.cached_filtered is None:
            self.cached_filtered = filtered_slice
            return
        if filtered_slice.is_empty():
            return
        if self.cached_filtered.is_empty():
            self.cached_filtered = filtered_slice
            return
        self.append_count += 1
        rechunk = self.append_count % _RECHUNK_EVERY_APPENDS == 0
        self.cached_filtered = pl.concat(
            [self.cached_filtered, filtered_slice], how="vertical", rechunk=rechunk
        )
