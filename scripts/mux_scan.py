from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.can_data_parser import load_can_dataframe
from services.mux_detector import detect_muxes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan a CAN log for mux selectors (read-only).")
    parser.add_argument("log", type=Path, help="candump/Kvaser/ASC/BLF/TRC/CSV log path")
    args = parser.parse_args(argv)
    df = load_can_dataframe(args.log)
    results = detect_muxes(df)
    print(f"Log: {args.log}")
    print(f"Frames: {df.height:,} | CAN IDs: {len(results)}")
    print(f"{'ID':>10}  {'Selector':<14} {'K':>5}  {'Confidence':<10}  Notes")
    for item in results:
        selector = item["selector"]
        label = "none" if not selector else f"byte {selector[0]}" if len(selector) == 1 else f"bytes {selector[0]}-{selector[-1]}"
        values = item["values"]
        notes = []
        if item["counter_like"]:
            notes.append("counter-like")
        if item["variable_dlc"]:
            notes.append("variable DLC")
        if item["hierarchy_suspected"]:
            notes.append("hierarchy suspected")
        if not item["has_mux"]:
            notes.append("no mux above threshold")
        print(f"{item['can_id']:>10}  {label:<14} {len(values):>5}  {item['confidence']:<10}  {', '.join(notes) or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
