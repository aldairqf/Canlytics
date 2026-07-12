"""Signal Coverage scan: which DBC signals actually carry data in the loaded log."""

from __future__ import annotations

import dataclasses
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
from utils.dbc_payload import DbcPayload
from utils.j1939 import J1939


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
    # Last sample in this stat set, in log/capture order -- the current value
    # when the df is still accumulating live, the last logged reading otherwise.
    # Same field serves both: the scan always reads whatever is in the df at
    # analysis time, live or offline.
    last_value: float


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
    def identity_key(self) -> tuple[str, str, str, str]:
        """Uniquely identifies this row across scans/refreshes -- the same
        DBC signal observed on the same concrete CAN id (can_id, not PGN, so a
        j1939 PGN broadcast by multiple source addresses stays distinguished).
        Single source of truth for "is this the same row" -- also used to
        sort the full scan's output and to key live-refresh lookups in
        views/signal_coverage_window.py."""
        return (self.dbc_name, self.message_name, self.signal_name, self.can_id)

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

    items.sort(key=lambda item: item.identity_key)
    return items


def refresh_last_values(items: list[SignalCoverageItem], new_df: pl.DataFrame) -> list[SignalCoverageItem]:
    """Re-derive only ``last_value`` for items whose CAN ID appears in
    ``new_df`` -- the incremental counterpart to build_signal_coverage_report(),
    used to keep the "last value" column live as frames keep arriving (streaming
    or a growing log) without re-running the full scan. frame_count/unique/min/
    max/mean are left exactly as of the last full scan; only last_value moves.

    Deliberately plain Python/DbcPayload.extract_bits, not Polars: the full
    scan's vectorized with_columns()/extract_signals_raw_batch() path pays a
    fixed per-call cost (query planning + .collect(), roughly half a
    millisecond) that's worth it when decoding an entire log, but ``new_df``
    here is always a handful of freshly-arrived rows -- paying that fixed
    cost once per distinct CAN id, on every incoming chunk while streaming,
    is what made this sluggish against a large DBC. A row-by-row Python loop
    over a few rows is microseconds, not milliseconds.

    An item whose stats_real is None (every sample seen so far was the "not
    available" sentinel) is left with stats_real=None even if new_df's data for
    it is real -- promoting it to "has real data" needs the rest of stats_real
    (frame_count, min/max/mean) recomputed too, which only a full scan does.

    Returns a list the same length as ``items``; entries untouched by ``new_df``
    are the same object (by identity) as the input, so callers can diff by
    identity to find what actually changed.
    """
    if new_df is None or new_df.is_empty() or not items:
        return items

    rows_by_can_id: dict[int, list[dict]] = {}
    for row in new_df.iter_rows(named=True):
        can_id_int = _hex_to_int(row.get("ID"))
        if can_id_int is None:
            continue
        rows_by_can_id.setdefault(can_id_int, []).append(row)
    if not rows_by_can_id:
        return items

    updated = list(items)
    for idx, item in enumerate(items):
        can_id_int = _hex_to_int(item.can_id)
        if can_id_int is None:
            continue
        rows = rows_by_can_id.get(can_id_int)
        if not rows:
            continue

        new_item = _refresh_item_from_rows(item, rows)
        if new_item is not None:
            updated[idx] = new_item

    return updated


def _hex_to_int(value) -> int | None:
    if not value:
        return None
    try:
        return int(value, 16)
    except (TypeError, ValueError):
        return None


def _row_payload(row: dict) -> bytes:
    return bytes(int(row.get(f"D{i}") or 0) & 0xFF for i in range(8))


def _refresh_item_from_rows(item: SignalCoverageItem, rows: list[dict]) -> SignalCoverageItem | None:
    decode_target = Signal(
        name=item.signal_name,
        start_bit=item.start_bit,
        length=item.length,
        le=item.byte_order == "little_endian",
        scale=item.scale,
        offset=item.offset,
        mux_start=item.mux_start,
        mux_bytes=item.mux_bytes,
        mux_value=item.mux_value,
        type_data=item.value_type,
    )
    le = item.byte_order == "little_endian"
    sentinel_raw = (1 << item.length) - 1

    last_raw = None
    last_real_raw = None
    for row in rows:
        payload = _row_payload(row)
        if item.mux_bytes > 0:
            mux_value = DbcPayload.mux_value(payload, item.mux_start, item.mux_bytes)
            if item.mux_value is not None and mux_value != int(item.mux_value):
                continue
        raw = DbcPayload.extract_bits(payload, item.start_bit, item.length, le)
        last_raw = raw
        if raw != sentinel_raw:
            last_real_raw = raw

    if last_raw is None:
        return None  # no row matched (every row filtered out by mux)

    # mode="bam" selects convert_raw_signal_values()'s per-scalar conversion
    # path -- unrelated to whether this signal is actually BAM-mode; it's the
    # same uint/int/float32 + scale/offset math, just for one raw value
    # instead of a numpy array.
    stats_all = dataclasses.replace(
        item.stats_all, last_value=convert_raw_signal_values(decode_target, [last_raw], mode="bam")[0]
    )
    stats_real = item.stats_real
    if stats_real is not None and last_real_raw is not None:
        stats_real = dataclasses.replace(
            stats_real, last_value=convert_raw_signal_values(decode_target, [last_real_raw], mode="bam")[0]
        )

    return dataclasses.replace(item, stats_all=stats_all, stats_real=stats_real)


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

    pgn_display = J1939.format_pgn(selector.pgn) if match_mode == "j1939" else None
    is_pdu1 = J1939.is_pdu1(selector.pgn) if match_mode == "j1939" else None

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


def _compute_stats(values_array: np.ndarray) -> SignalStats:
    unique_count = int(np.unique(values_array).size)
    return SignalStats(
        frame_count=int(values_array.size),
        unique_count=unique_count,
        min_value=float(values_array.min()),
        max_value=float(values_array.max()),
        mean_value=float(values_array.mean()),
        is_changing=unique_count >= 2,
        last_value=float(values_array[-1]),
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
