"""Pure incremental filtering for the main table's history dataframe.

TableFilterViewModel thin-wraps IncrementalTableFilter for its "history"
source (the accumulated log, append-only growth from a loaded file or a live
connection). Every dataframe_changed carries the WHOLE accumulated dataframe,
so filtering it by selected IDs / time range from scratch on every batch is
O(rows seen so far) per batch -- O(N^2) total over a long session. Folding in
only the rows new since the last call keeps it at O(new rows) per batch.

This is deliberately NOT used for the "live" source (real-time analysis's
bounded, in-place-updated table): that dataframe has one row per distinct
(ID, LEN, mux) entry whose VALUES change in place rather than growing by
appended rows, so a row-count watermark would miss updates entirely. It's
also small (bounded by distinct entries, not total frames), so re-deriving it
in full each time was never the expensive case.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl


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
    seen_ids: set = field(default_factory=set)

    def reset(self) -> None:
        self.cached_height = 0
        self.cached_filtered = None
        self.seen_ids = set()

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
        if height < self.cached_height:
            # Source shrank (reload/clear) -- can't be append-only growth.
            self.reset()

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

        if self.cached_filtered is None:
            self.cached_filtered = filtered_slice
        else:
            self.cached_filtered = pl.concat(
                [self.cached_filtered, filtered_slice], how="vertical", rechunk=False
            )

        return self.cached_filtered, sorted(self.seen_ids), ids_changed
