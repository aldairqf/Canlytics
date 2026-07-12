from __future__ import annotations

import polars as pl


def merge_frames(
    base: pl.DataFrame | None,
    incoming: pl.DataFrame,
    *,
    normalize: bool,
    rechunk: bool = True,
) -> pl.DataFrame:
    """Append *incoming* onto *base*, sorting by TS if out of order.

    rechunk=False skips the O(total rows) copy -- pass it on a hot streaming
    path and rechunk periodically instead. A resort always rechunks anyway.
    """
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

    if _is_already_appended_in_order(base, df_new):
        return pl.concat(
            [base, df_new],
            how="vertical",
            rechunk=rechunk,
        )

    return pl.concat(
        [base, df_new],
        how="vertical",
        rechunk=True,
    ).sort("TS")


def _is_already_appended_in_order(base: pl.DataFrame, incoming: pl.DataFrame) -> bool:
    if base.is_empty() or incoming.is_empty() or "TS" not in base.columns or "TS" not in incoming.columns:
        return True
    try:
        base_last_ts = float(base[-1, "TS"])
        incoming_first_ts = float(incoming[0, "TS"])
    except Exception:
        return False
    return incoming_first_ts >= base_last_ts
