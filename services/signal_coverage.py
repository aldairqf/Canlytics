"""Pure logic for the Signal Coverage scan: which DBC signals actually carry data.

A DBC message can define many signals; only some of them may ever hold real values
in a given log. This walks every signal of every active DBC entry, decodes it
against the loaded dataframe, and reports only the ones that have at least one
sample -- with per-signal stats. Qt-free and testable, same layer as
services/mux_detector.py and services/candidate_interpretations.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import polars as pl

from models.frame_selector import FrameSelector
from models.signal import Signal
from services.can_decoder import (
    convert_raw_signal_values,
    extract_signal_raw,
    extract_signals_raw_batch,
    partition_by_id,
    partition_by_pgn,
    with_data_int,
    with_id_columns,
)
from services.signal_formatting import normalize_display_text


class SignalCoverageCanceled(Exception):
    pass


@dataclass(frozen=True)
class SignalStats:
    frame_count: int
    unique_count: int
    min_value: float
    max_value: float
    mean_value: float
    is_changing: bool


@dataclass(frozen=True)
class SignalCoverageItem:
    dbc_name: str
    message_name: str
    signal_name: str
    can_id: str
    # The PGN, formatted (e.g. "0x0200") -- only set for j1939/bam; a PGN can be
    # broadcast by more than one CAN ID (source address), so it's tracked
    # separately from can_id rather than the two being conflated into one field.
    pgn: str | None
    # True for PDU1 (point-to-point, addressed to a destination -- the byte
    # that follows PF in the CAN ID is a destination address, not part of the
    # PGN); False for PDU2 (broadcast, that byte is a PGN group extension).
    # None for exact mode, where PDU1/PDU2 doesn't apply.
    is_pdu1: bool | None
    match_mode: str
    unit: str
    description: str
    start_bit: int
    length: int
    byte_order: str
    value_type: str
    scale: float
    offset: float
    mux_info: str | None
    # Raw mux geometry (0/0/None when not muxed) -- kept alongside mux_info's
    # display string so a row can be sent to a plot (see
    # views/signal_coverage_window.py) without a second DBC lookup.
    mux_start: int
    mux_bytes: int
    mux_value: int | None
    stats_all: SignalStats
    # None when every captured sample is the "not available" sentinel (all raw
    # bits set) -- there is no "real data" stat set to show for that signal.
    stats_real: SignalStats | None

    @property
    def byte_aligned(self) -> bool:
        # Both ends must land on a byte boundary -- a 2-bit flag that starts at
        # bit 0 is still a sub-byte bitfield, not a clean whole-byte SPN, even
        # though its start bit alone is a multiple of 8.
        return self.start_bit % 8 == 0 and self.length % 8 == 0

    @property
    def decoding_summary(self) -> str:
        endian = "LE" if self.byte_order == "little_endian" else "BE"
        summary = f"{endian} · bit {self.start_bit} · {self.length} bit · {self.value_type}"
        if self.scale != 1.0 or self.offset != 0.0:
            summary += f" · x{self.scale:g}+{self.offset:g}"
        if self.mux_info:
            summary += f" · {self.mux_info}"
        return summary


def build_signal_coverage_report(
    df: pl.DataFrame,
    dbc_manager,
    *,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[SignalCoverageItem]:
    if df is None or df.is_empty():
        return []

    # Parse the ID column (and derive its J1939 PGN) once for the whole scan --
    # every message's filter below reuses these columns instead of re-parsing
    # the full log per message, which is what made scans of DBCs with
    # thousands of signals slow.
    df = with_id_columns(df)

    # A DBC can define far more messages than actually appear in a given log
    # (e.g. a generic j1939.dbc against one machine's capture). Filtering the
    # full log once per message -- most of which match zero rows -- means
    # thousands of full-table scans. Partition the log by PGN/id ONCE instead,
    # so each message's frames are an O(1) dict lookup (or a free miss).
    partitions_by_pgn = partition_by_pgn(df)
    partitions_by_id = partition_by_id(df)

    message_specs = [
        (entry, message)
        for entry in dbc_manager.active_entries()
        for message in entry.db.messages
    ]
    total = sum(len(message.signals) for _, message in message_specs)

    items: list[SignalCoverageItem] = []
    done = 0
    for entry, message in message_specs:
        done = _process_message(
            df, dbc_manager, entry, message,
            partitions_by_pgn=partitions_by_pgn,
            partitions_by_id=partitions_by_id,
            should_cancel=should_cancel,
            on_progress=on_progress,
            done=done,
            total=total,
            items=items,
        )

    items.sort(key=lambda item: (item.dbc_name, item.message_name, item.signal_name, item.can_id))
    return items


def _resolve_signal(dbc_manager, entry, message, signal):
    try:
        sig_def = dbc_manager.get_signal_definition(entry.name, message.name, signal.name)
    except KeyError:
        return None

    # For j1939/bam, get_signal_definition()'s "can_id" is the PGN (used for
    # display), not a real frame id. Feeding it to Signal.can_id/selected_id
    # would make _filter_by_selector narrow to "frame id == PGN", which never
    # matches a real frame -- only "exact" mode's can_id is a real frame id.
    match_mode = sig_def["id_match"]
    selector_id = sig_def["can_id"] if match_mode == "exact" else None

    decode_target = Signal(
        name=sig_def["name"],
        can_id=selector_id,
        start_bit=sig_def["start_bit"],
        length=sig_def["length"],
        le=sig_def["le"],
        scale=sig_def["scale"],
        offset=sig_def["offset"],
        mux_bytes=sig_def["mux_bytes"],
        mux_start=sig_def["mux_start"],
        mux_value=sig_def["mux_value"],
        type_data=sig_def["type_data"],
    )
    selector = FrameSelector(selected_id=selector_id, mode=match_mode, pgn=sig_def["pgn"])
    return signal, sig_def, decode_target, selector


def _process_message(df, dbc_manager, entry, message, *, partitions_by_pgn, partitions_by_id, should_cancel, on_progress, done, total, items) -> int:
    resolved = [_resolve_signal(dbc_manager, entry, message, signal) for signal in message.signals]

    def _tick():
        nonlocal done
        _raise_if_canceled(should_cancel)
        done += 1
        if on_progress is not None:
            on_progress(done, total)

    first = next((r for r in resolved if r is not None), None)
    if first is None:
        for _ in resolved:
            _tick()
        return done

    match_mode = first[3].mode
    if match_mode == "bam":
        # BAM (multi-packet J1939) signals are not scanned for now -- reassembly
        # re-scans the whole log per message and is far more expensive than the
        # direct exact/j1939 decode path at DBC scale. Skip rather than pay
        # that cost; mux and non-mux exact/j1939 signals are unaffected.
        for _ in resolved:
            _tick()
        return done

    # Every signal in a message shares the same id/PGN/mode. A j1939 PGN can be
    # broadcast by more than one CAN ID (source address/ECU) -- each gets its
    # own dataframe and its own SignalCoverageItem per signal below, instead of
    # silently merging different sources' samples into one row.
    selector = first[3]
    id_groups = _lookup_id_groups(match_mode, selector, partitions_by_pgn, partitions_by_id)
    if not id_groups:
        for _ in resolved:
            _tick()
        return done

    pgn_display = _format_pgn(selector.pgn) if match_mode == "j1939" else None
    is_pdu1 = _is_pdu1(selector.pgn) if match_mode == "j1939" else None

    # Non-muxed signals of a message+source read the same rows, so their raw-bit
    # columns can be computed in ONE with_columns() call instead of one call
    # per signal -- each Polars call has fixed overhead that dominates once a
    # DBC has thousands of signals. Muxed signals may each need to filter to a
    # different MUX case, so they keep the individual path.
    batch_entries = [r for r in resolved if r is not None and r[1]["mux_bytes"] == 0]
    muxed_entries = [r for r in resolved if r is not None and r[1]["mux_bytes"] > 0]

    for can_id_int, group_df in id_groups.items():
        prepared = with_data_int(group_df)
        can_id_display = _format_hex_id(can_id_int)

        if batch_entries:
            batch_results = extract_signals_raw_batch(prepared, [r[2] for r in batch_entries])
            for (signal, sig_def, decode_target, sig_selector), (_, raw_values) in zip(batch_entries, batch_results):
                item = _finish_item(raw_values, entry, message, signal, sig_def, decode_target, sig_selector, can_id_display, pgn_display, is_pdu1)
                if item is not None:
                    items.append(item)

        for signal, sig_def, decode_target, sig_selector in muxed_entries:
            _, raw_values = extract_signal_raw(prepared, decode_target)
            item = _finish_item(raw_values, entry, message, signal, sig_def, decode_target, sig_selector, can_id_display, pgn_display, is_pdu1)
            if item is not None:
                items.append(item)

    # One tick per DBC-defined signal, not per (signal x source) -- total was
    # computed from signal definitions before any source was known, so ticking
    # per id_group would overshoot it when a PGN has multiple active sources.
    for _ in resolved:
        _tick()

    return done


def _lookup_id_groups(match_mode, selector, partitions_by_pgn, partitions_by_id):
    """Every distinct CAN ID observed for this message, each as its own
    dataframe. Exact mode always resolves to a single id; j1939 resolves to
    however many source addresses actually broadcast that PGN in the log."""
    if match_mode == "j1939":
        if selector.pgn is None:
            return {}
        filtered = partitions_by_pgn.get(selector.pgn)
        if filtered is None or filtered.is_empty():
            return {}
        groups = filtered.partition_by("_ID_INT", as_dict=True)
        return {(key[0] if isinstance(key, tuple) else key): group for key, group in groups.items()}

    key = selector.selected_id_int()
    if key is None:
        return {}
    filtered = partitions_by_id.get(key)
    if filtered is None or filtered.is_empty():
        return {}
    return {key: filtered}


def _format_hex_id(value: int) -> str:
    return f"{value:X}"


def _format_pgn(pgn: int | None) -> str | None:
    """Format the same way views/signal/tabs/decode_tab.py's PGN field does
    (``0x0200``) so it reads as a PGN rather than a bare, oddly short number
    next to real CAN IDs."""
    if pgn is None:
        return None
    return f"0x{pgn:04X}"


def _is_pdu1(pgn: int | None) -> bool | None:
    """PDU1 vs PDU2 is decided by the PF byte -- and PF always lands in the
    PGN's bits 8-15 regardless of format (PDU1's PGN is dp<<16|pf<<8, PDU2's
    is dp<<16|pf<<8|ps), so it can be recovered from the PGN alone without
    re-deriving it from a specific CAN ID."""
    if pgn is None:
        return None
    pf = (pgn >> 8) & 0xFF
    return pf < 240


def _compute_stats(values_array: np.ndarray) -> SignalStats:
    unique_count = int(np.unique(values_array).size)
    return SignalStats(
        frame_count=int(values_array.size),
        unique_count=unique_count,
        min_value=float(values_array.min()),
        max_value=float(values_array.max()),
        mean_value=float(values_array.mean()),
        is_changing=unique_count >= 2,
    )


def _finish_item(raw_values, entry, message, signal, sig_def, decode_target, selector, can_id: str, pgn: str | None, is_pdu1: bool | None):
    # Whether to exclude "not available" (all raw bits set) samples is a
    # display-time choice (see views/signal_coverage_window.py's filters
    # dialog), not a scan-time one -- both stat sets are computed once here
    # from the same raw extraction pass so toggling the filter never re-scans.
    if not raw_values:
        return None

    raw_array = np.asarray(raw_values, dtype=np.uint64)
    sentinel_raw = (1 << sig_def["length"]) - 1
    real_mask = raw_array != sentinel_raw

    values = convert_raw_signal_values(decode_target, raw_values, mode=selector.mode)
    values_array = np.asarray(values, dtype=np.float64)

    stats_all = _compute_stats(values_array)
    stats_real = _compute_stats(values_array[real_mask]) if real_mask.any() else None

    mux_info = None
    if sig_def["mux_bytes"] > 0:
        mux_info = f"mux={sig_def['mux_value']}" if sig_def["mux_value"] is not None else "mux"

    return SignalCoverageItem(
        dbc_name=entry.name,
        message_name=message.name,
        signal_name=signal.name,
        can_id=can_id,
        pgn=pgn,
        is_pdu1=is_pdu1,
        match_mode=sig_def["id_match"],
        unit=normalize_display_text(getattr(signal, "unit", None)) or "",
        description=normalize_display_text(getattr(signal, "comment", None)) or "",
        start_bit=sig_def["start_bit"],
        length=sig_def["length"],
        byte_order="little_endian" if sig_def["le"] else "big_endian",
        value_type=sig_def["type_data"],
        scale=sig_def["scale"],
        offset=sig_def["offset"],
        mux_info=mux_info,
        mux_start=sig_def["mux_start"],
        mux_bytes=sig_def["mux_bytes"],
        mux_value=sig_def["mux_value"],
        stats_all=stats_all,
        stats_real=stats_real,
    )


def _raise_if_canceled(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel is not None and should_cancel():
        raise SignalCoverageCanceled()
