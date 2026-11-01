"""Benchmark the per-flush streaming hot path as the accumulated log grows.

Simulates live capture (one flush per 100 ms) and reports the avg cost of each
stage at checkpoints. Default profile = real field logs (~900 fps, ~40 IDs).

Usage: python scripts/bench_stream.py [--fps 900] [--ids 40] [--minutes 60] [--report-every 5]
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl  # noqa: E402

from services.analyze_data import sorted_can_ids  # noqa: E402
from services.can_data_parser import empty_frame, frame_dict, rows_to_df  # noqa: E402
from services.log_data import merge_frames  # noqa: E402
from services.table_filter import IncrementalTableFilter  # noqa: E402

FLUSH_S = 0.1


def _chunk(t0: float, rows: int, fps: int, ids: list[int]) -> pl.DataFrame:
    return rows_to_df([
        frame_dict(ts=t0 + i / fps, bus="kvaser", can_id=random.choice(ids),
                   data=bytes(random.randrange(256) for _ in range(8)))
        for i in range(rows)
    ])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=int, default=900)
    ap.add_argument("--ids", type=int, default=40)
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--report-every", type=float, default=5, help="minutes between reports")
    args = ap.parse_args()

    random.seed(0)
    ids = [0x18FEF100 + i for i in range(args.ids)]
    selected = {f"{i:08X}" for i in ids[:3]}
    rows_per_flush = max(1, int(args.fps * FLUSH_S))
    flushes = int(args.minutes * 60 / FLUSH_S)
    report_every = max(1, int(args.report_every * 60 / FLUSH_S))

    df_all = empty_frame()
    filt = IncrementalTableFilter()
    stages = {"merge": 0.0, "emit_ids": 0.0, "analyze_ids": 0.0, "table_filter": 0.0}
    t, last = 1.7e9, 0
    print(f"profile: {args.fps} fps, {args.ids} IDs, {args.minutes} min ({rows_per_flush} rows/flush)")
    for n in range(1, flushes + 1):
        chunk = _chunk(t, rows_per_flush, args.fps, ids)
        t += FLUSH_S
        s0 = time.perf_counter()
        df_all = merge_frames(df_all, chunk, normalize=False, rechunk=(n % 20 == 0))
        s1 = time.perf_counter()
        df_all["ID"].unique().to_list()  # data_viewmodel._emit_ids
        s2 = time.perf_counter()
        sorted_can_ids(df_all)  # analyze_data_viewmodel.set_dataframe
        s3 = time.perf_counter()
        filt.apply(df_all, selected_ids=selected, ts_min=None, ts_max=None)
        s4 = time.perf_counter()
        for key, dt in zip(stages, (s1 - s0, s2 - s1, s3 - s2, s4 - s3)):
            stages[key] += dt
        if n % report_every == 0 or n == flushes:
            w = n - last
            total = sum(stages.values()) / w * 1000
            parts = " ".join(f"{k}={v / w * 1000:6.2f}ms" for k, v in stages.items())
            print(f"{n * FLUSH_S / 60:6.1f} min rows={df_all.height:>9,} | {parts} | total={total:6.2f}ms/flush")
            stages = {k: 0.0 for k in stages}
            last = n


if __name__ == "__main__":
    main()
