from __future__ import annotations

import polars as pl


class LogDataService:

    def merge_frames(
        self,
        base: pl.DataFrame | None,
        incoming: pl.DataFrame,
        *,
        normalize: bool,
    ) -> pl.DataFrame:
        if incoming.is_empty():
            if base is None:
                return pl.DataFrame()
            return base

        if base is None or base.is_empty():
            return incoming

        df_new = incoming
        if normalize:
            base_ts = base.select(pl.first("TS")).item()
            df_new = df_new.with_columns(
                (pl.col("TS") - base_ts).round(6).alias("TS")
            )

        return pl.concat(
            [base, df_new],
            how="vertical",
            rechunk=True,
        ).sort("TS")
