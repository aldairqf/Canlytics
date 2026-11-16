from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.can_data_parser import load_can_dataframe
from services.mux_detector import detect_muxes


def _mapping(value: str) -> tuple[str, Path]:
    name, separator, path = value.partition("=")
    if not separator or not name or not path:
        raise argparse.ArgumentTypeError("Use MACHINE=PATH")
    return name, Path(path)


def _truth(directories: list[tuple[str, Path]]) -> tuple[dict[tuple[str, str], set[tuple[int, ...]]], set[tuple[str, str]]]:
    mux: dict[tuple[str, str], set[tuple[int, ...]]] = defaultdict(set)
    direct: set[tuple[str, str]] = set()
    for machine, root in directories:
        for path in root.rglob("*.conf"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            for item in payload.get("signals", []):
                signal = item.get("signal", item)
                can_id = str(signal.get("can_id", "")).upper()
                if not can_id:
                    continue
                width = int(signal.get("mux_bytes") or 0)
                start = int(signal.get("mux_start") or 0)
                if width > 0:
                    mux[(machine, can_id)].add(tuple(range(start, start + width)))
                else:
                    direct.add((machine, can_id))
    return dict(mux), direct


def _selector(result: dict[str, object]) -> tuple[int, ...]:
    return tuple(int(value) for value in result["selector"])


def _fmt(selector: tuple[int, ...] | None) -> str:
    if selector is None:
        return "—"
    if not selector:
        return "sin mux"
    return f"B{selector[0]}+{len(selector)}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare mux recommendations with read-only plot configs.")
    parser.add_argument("--truth-dir", action="append", type=_mapping, default=[], metavar="MACHINE=DIR")
    parser.add_argument("--log", action="append", type=_mapping, default=[], metavar="MACHINE=LOG")
    args = parser.parse_args(argv)
    truth, direct = _truth(args.truth_dir)
    for machine, path in args.log:
        dataframe = load_can_dataframe(path)
        results = detect_muxes(dataframe)
        by_id = {str(row["can_id"]).upper(): row for row in results}
        print("Recomendations by evidence:")
        print("ID       selector     confidence coverage dG     stable ext.")
        for row in results:
            if not row["has_mux"]:
                continue
            extension = row.get("extension_agreement")
            extension_text = f"{extension:.3f}" if extension is not None else "-"
            print(f"{row['can_id']:<8} {_fmt(_selector(row)):<12} "
                  f"{row.get('confidence') or '-':<10} {float(row.get('coverage', 0.0)):>5.3f} "
                  f"{float(row.get('gain_margin', 0.0)):>6.3f} "
                  f"{float(row.get('period_stability', 0.0)):>6.3f} {extension_text:>5}")
        expected = {can_id: selectors for (owner, can_id), selectors in truth.items() if owner == machine}
        expected_direct = {can_id for owner, can_id in direct if owner == machine}
        exact = overlap_sum = scored = 0
        false_positives: list[str] = []
        print(f"\n{machine}: {path.name} ({dataframe.height:,} tramas)")
        print("ID       verdad       recomendado   IoU    conf.    cov.    dG     estable ext.")
        for can_id in sorted(expected):
            if can_id not in by_id:
                continue
            row = by_id[can_id]
            predicted = _selector(row)
            target_set = expected[can_id]
            best_exact = predicted in target_set
            best_overlap = max((len(set(predicted) & set(target)) / len(set(predicted) | set(target))
                                if predicted or target else 1.0) for target in target_set)
            exact += int(best_exact)
            overlap_sum += best_overlap
            scored += 1
            extension = row.get("extension_agreement")
            extension_text = f"{extension:.3f}" if extension is not None else "—"
            print(f"{can_id:<8} {','.join(_fmt(item) for item in sorted(target_set)):<12} {_fmt(predicted):<12} "
                  f"{best_overlap:>4.2f}  {row.get('confidence') or '—':<7} "
                  f"{float(row.get('coverage', 0.0)):>5.3f} "
                  f"{float(row.get('gain_margin', 0.0)):>6.3f} "
                  f"{float(row.get('period_stability', 0.0)):>7.3f} {extension_text:>5}")
        for can_id in sorted(expected_direct - set(expected)):
            row = by_id.get(can_id)
            if row and row["has_mux"]:
                false_positives.append(f"{can_id} {_fmt(_selector(row))}")
        print(f"Metrics: exact {exact}/{scored}; mean overlap {overlap_sum / scored if scored else 0:.3f}; "
              f"FP in direct signals: {', '.join(false_positives) or 'none'}")
        recommended = [
            f"{row['can_id']} {_fmt(_selector(row))} ({row.get('confidence') or '—'})"
            for row in results if row["has_mux"]
        ]
        print("Recomendados (ID selector): " + (", ".join(recommended) or "ninguno"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
