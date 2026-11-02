from __future__ import annotations

import polars as pl


def merge_frames(
    base: pl.DataFrame | None,
    incoming: pl.DataFrame,
    *,
    normalize: bool,
    rechunk: bool = True,
) -> pl.DataFrame:
    """Append *incoming* onto *base*, sorting only the affected tail if needed.

    rechunk=False skips the O(total rows) copy -- pass it on a hot streaming
    path and rechunk periodically instead.
    """
    if incoming.is_empty():
        if base is None:
            return pl.DataFrame()
        return base

    if base is None or base.is_empty():
        if "TS" in incoming.columns and not incoming["TS"].is_sorted():
            return incoming.sort("TS")
        return incoming

    df_new = incoming
    if normalize:
        base_ts = base.select(pl.first("TS")).item()
        df_new = df_new.with_columns(
            (pl.col("TS") - base_ts).round(6).alias("TS")
        )

    if is_append_in_order(base, df_new):
        return pl.concat(
            [base, df_new],
            how="vertical",
            rechunk=rechunk,
        )

    if not base["TS"].is_sorted():
        merged = pl.concat([base, df_new], how="vertical", rechunk=False).sort("TS")
        return merged.rechunk() if rechunk else merged

    first_affected_ts = float(df_new["TS"].min())
    split_at = int(base["TS"].search_sorted(first_affected_ts, side="left"))
    prefix = base.slice(0, split_at)
    affected_tail = base.slice(split_at)
    merged_tail = pl.concat([affected_tail, df_new], how="vertical", rechunk=False).sort(
        "TS",
        maintain_order=True,
    )
    if prefix.is_empty():
        merged = merged_tail
    else:
        merged = pl.concat([prefix, merged_tail], how="vertical", rechunk=False)
    return merged.rechunk() if rechunk else merged


def is_append_in_order(
    base: pl.DataFrame | None,
    incoming: pl.DataFrame,
    *,
    normalize: bool = False,
) -> bool:
    """Return whether incoming timestamps can be appended without reordering base."""
    if incoming.is_empty() or "TS" not in incoming.columns:
        return True
    if not incoming["TS"].is_sorted():
        return False
    if base is None or base.is_empty() or "TS" not in base.columns:
        return True
    try:
        base_last_ts = float(base[-1, "TS"])
        incoming_first_ts = float(incoming[0, "TS"])
        if normalize:
            incoming_first_ts -= float(base[0, "TS"])
    except Exception:
        return False
    return incoming_first_ts >= base_last_ts
