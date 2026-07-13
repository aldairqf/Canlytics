"""Convert a J1939 PGN map CSV (PGN / byte offset / scale / offset per row) into a DBC.

One :class:`~cantools.database.can.Message` is created per distinct PGN, with one
:class:`~cantools.database.can.Signal` per CSV row sharing that PGN. Only scale/offset
linear decoding is generated -- CSV "Notes" describing bitmask/enum meanings are not
turned into DBC value tables (``VAL_``). Byte order is read from a "Byte order" column
when present; otherwise every signal defaults to little-endian.
"""

from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import cantools
from cantools.database.can import Database, Message, Signal
from cantools.database.conversion import BaseConversion

from utils.j1939 import J1939

_BYTE_ORDER_HEADER_RE = re.compile(r"byte\s*order|bit\s*order", re.IGNORECASE)
_BYTE_ORDER_ALIASES = {
    "le": "little_endian",
    "little": "little_endian",
    "little_endian": "little_endian",
    "intel": "little_endian",
    "be": "big_endian",
    "big": "big_endian",
    "big_endian": "big_endian",
    "motorola": "big_endian",
}
_DEFAULT_BYTE_ORDER = "little_endian"


def read_pgn_csv_rows(csv_path: str | Path) -> list[dict[str, str]]:
    with open(csv_path, newline="", encoding="utf-8-sig", errors="replace") as handle:
        return list(csv.DictReader(handle))


def _find_byte_order_column(fieldnames: list[str]) -> str | None:
    for name in fieldnames:
        if name and _BYTE_ORDER_HEADER_RE.search(name):
            return name
    return None


def _resolve_byte_order(raw_value: str | None) -> str:
    if not raw_value:
        return _DEFAULT_BYTE_ORDER
    return _BYTE_ORDER_ALIASES.get(raw_value.strip().lower(), _DEFAULT_BYTE_ORDER)


def _sanitize_identifier(text: str, *, fallback: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", text.strip()).strip("_")
    if not cleaned:
        cleaned = fallback
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


def _unique_name(base: str, used: set[str]) -> str:
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def _float(value: str | None, default: float = 0.0) -> float:
    if value is None or not value.strip():
        return default
    return float(value)


def _int(value: str | None, default: int = 0) -> int:
    if value is None or not value.strip():
        return default
    return int(float(value))


def _group_rows_by_pgn(rows: list[dict[str, str]]) -> dict[int, list[dict[str, str]]]:
    grouped: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        pgn_raw = (row.get("PGN") or "").strip()
        if not pgn_raw:
            continue
        grouped.setdefault(_int(pgn_raw), []).append(row)
    return grouped


def _row_byte_span(row: dict[str, str]) -> tuple[int, int]:
    """(byte_offset, length_bytes) for a CSV row -- shared by
    build_database_from_rows (decode geometry) and find_overlapping_signals
    (overlap ranges), so the two can never silently disagree on how a row's
    bytes are read."""
    return _int(row.get("PGN Byte Offset")), _int(row.get("Parameter Length (Bytes)"), 1)


def build_database_from_rows(
    rows: list[dict[str, str]],
    *,
    priority_default: int = 6,
    source_address: int = 0x00,
) -> Database:
    byte_order_column = _find_byte_order_column(list(rows[0].keys())) if rows else None
    grouped = _group_rows_by_pgn(rows)

    used_signal_names: set[str] = set()
    messages: list[Message] = []
    for pgn in sorted(grouped):
        group_rows = grouped[pgn]
        priority = _int(group_rows[0].get("PGN Priority"), priority_default)
        length = max(_int(row.get("PGN Max Size"), 8) for row in group_rows)
        frame_id = J1939.pgn_to_frame_id(pgn, priority=priority, source_address=source_address)

        signals: list[Signal] = []
        for row in group_rows:
            byte_offset, length_bytes = _row_byte_span(row)
            scale = _float(row.get("Scale/Resolution"), 1.0) or 1.0
            offset = _float(row.get("Offset"), 0.0)
            unit = (row.get("Unit") or "").strip()
            byte_order = _resolve_byte_order(row.get(byte_order_column) if byte_order_column else None)
            description = (row.get("Description") or "").strip()
            name = _unique_name(
                _sanitize_identifier(description, fallback=f"SPN_{byte_offset}"),
                used_signal_names,
            )
            signals.append(
                Signal(
                    name=name,
                    start=byte_offset * 8,
                    length=length_bytes * 8,
                    byte_order=byte_order,
                    is_signed=False,
                    conversion=BaseConversion.factory(scale=scale, offset=offset),
                    unit=unit or None,
                )
            )

        messages.append(
            Message(
                frame_id=frame_id,
                name=f"PGN_{pgn}",
                length=length,
                signals=signals,
                is_extended_frame=True,
                # A CSV mapping is a flat list of independently-authored byte
                # offsets/lengths -- two rows overlapping is a data-entry issue
                # to flag (see find_overlapping_signals), not a reason to
                # reject the whole PGN. Strict mode would raise and abort the
                # entire conversion on the first overlap found. This also
                # relaxes cantools' "signal doesn't fit in message" check (a
                # signal extending past PGN Max Size) -- harmless here since
                # this app's own decoder (services/can_decoder.py) always
                # reads from the full 8-byte D0..D7 payload regardless of a
                # message's declared length, so such a signal still decodes
                # correctly; only a strict external DBC consumer would care.
                strict=False,
            )
        )

    return Database(messages=messages, strict=False)


@dataclass(frozen=True)
class SignalOverlap:
    pgn: int
    message_name: str
    signal_a: str
    signal_b: str


def find_overlapping_signals(rows: list[dict[str, str]]) -> list[SignalOverlap]:
    """Pairs of signals sharing the same PGN whose byte ranges overlap.

    Computed straight from the CSV's own byte_offset/length columns (every
    field here is byte-granular, so this is a plain range check -- no need to
    reproduce cantools' bit-numbering rules) so overlaps can be reported to
    the user instead of just being silently accepted by strict=False.
    """
    grouped = _group_rows_by_pgn(rows)

    overlaps: list[SignalOverlap] = []
    for pgn, group_rows in grouped.items():
        spans = []
        for row in group_rows:
            byte_offset, length_bytes = _row_byte_span(row)
            description = (row.get("Description") or "").strip() or f"SPN_{byte_offset}"
            spans.append((description, byte_offset, byte_offset + length_bytes))

        for i, (name_a, start_a, end_a) in enumerate(spans):
            for name_b, start_b, end_b in spans[i + 1:]:
                if start_a < end_b and start_b < end_a:
                    overlaps.append(
                        SignalOverlap(pgn=pgn, message_name=f"PGN_{pgn}", signal_a=name_a, signal_b=name_b)
                    )
    return overlaps


def convert_pgn_csv_to_dbc(
    csv_path: str | Path,
    dbc_path: str | Path,
    *,
    priority_default: int = 6,
    source_address: int = 0x00,
) -> tuple[Database, list[SignalOverlap]]:
    rows = read_pgn_csv_rows(csv_path)
    db = build_database_from_rows(
        rows,
        priority_default=priority_default,
        source_address=source_address,
    )
    cantools.database.dump_file(db, str(dbc_path))
    return db, find_overlapping_signals(rows)


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if len(args) != 2:
        print("usage: python -m services.pgn_csv_to_dbc <input.csv> <output.dbc>")
        return 2
    csv_path, dbc_path = args
    db, overlaps = convert_pgn_csv_to_dbc(csv_path, dbc_path)
    total_signals = sum(len(message.signals) for message in db.messages)
    print(f"Wrote {dbc_path}: {len(db.messages)} messages, {total_signals} signals")
    if overlaps:
        print(f"Warning: {len(overlaps)} overlapping signal pair(s):")
        for ov in overlaps:
            print(f"  {ov.message_name}: {ov.signal_a} overlaps {ov.signal_b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
