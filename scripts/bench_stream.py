"""Benchmark the per-flush streaming hot path as the accumulated log grows.

Simulates live capture (one flush per 100 ms) and reports the avg cost of each
stage at checkpoints. Default profile = real field logs (~900 fps, ~40 IDs).
The Phase 2 target is a flat total cost below 5 ms/flush.

Usage: python scripts/bench_stream.py [--fps 900] [--ids 40] [--minutes 60] [--report-every 5]
"""

from __future__ import annotations

import argparse
import random
import sys
import time
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402

from config.defaults import DEFAULT_COLUMNS  # noqa: E402
from services.analyze_data import sorted_can_ids  # noqa: E402
from services.can_data_parser import empty_frame, frame_dict, rows_to_df  # noqa: E402
from services.log_data import merge_frames  # noqa: E402
from services.table_filter import IncrementalTableFilter  # noqa: E402
from models.frame_selector import FrameSelector  # noqa: E402
from models.signal import Signal  # noqa: E402
from viewmodels.plot_viewmodel import PlotViewModel  # noqa: E402
from viewmodels.real_time_analysis_viewmodel import RealTimeAnalysisViewModel  # noqa: E402
from viewmodels.table_model import TableModel  # noqa: E402
from viewmodels.view_signal import ViewSignal  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402

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
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])

    random.seed(0)
    ids = [0x18FEF100 + i for i in range(args.ids)]
    selected = {f"{i:08X}" for i in ids[:3]}
    rows_per_flush = max(1, int(args.fps * FLUSH_S))
    flushes = int(args.minutes * 60 / FLUSH_S)
    report_every = max(1, int(args.report_every * 60 / FLUSH_S))

    df_all = empty_frame()
    filt = IncrementalTableFilter()
    table_model = TableModel(DEFAULT_COLUMNS)
    realtime_vm = RealTimeAnalysisViewModel()
    realtime_vm.set_enabled(True)
    realtime_vm._refresh_timer.stop()
    realtime_vm._highlight_expiry_timer.stop()
    plot_vm = PlotViewModel()
    for index, can_id in enumerate(ids[:4]):
        signal = Signal(name=f"Signal {index + 1}", can_id=f"{can_id:08X}", start_bit=0, length=8)
        plot_vm.upsert_signal(ViewSignal(
            signal=signal, selector=FrameSelector(selected_id=signal.can_id),
            color=QColor("#00ffff"), line_style="Solid", line_width=1,
        ))
    stage_names = ("merge", "emit_ids", "analyze_ids", "table_filter", "table_model", "real_time", "plot")
    stages = dict.fromkeys(stage_names, 0.0)
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
        filtered_df, _, _ = filt.apply(df_all, selected_ids=selected, ts_min=None, ts_max=None)
        s4 = time.perf_counter()
        table_model.set_dataframe(filtered_df)
        s5 = time.perf_counter()
        realtime_vm.ingest_df(chunk)
        realtime_vm._emit_if_dirty()
        s6 = time.perf_counter()
        if n == 1:
            plot_vm.set_dataframe(df_all)
            plot_vm.get_plot_data()
        else:
            plot_vm.ingest_raw_chunk(chunk)
            plot_vm.set_dataframe(df_all)
        s7 = time.perf_counter()
        app.processEvents()
        for key, dt in zip(stages, (s1 - s0, s2 - s1, s3 - s2, s4 - s3, s5 - s4, s6 - s5, s7 - s6)):
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
