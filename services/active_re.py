from __future__ import annotations

import struct
from dataclasses import dataclass
from math import floor, isfinite
from typing import Any, Iterable

import polars as pl

from services.can_send import ResolvedFrame
from utils.j1939 import J1939

_VALUE_TOLERANCE = 1e-6


@dataclass(frozen=True)
class SignalGeometry:
    start_bit: int
    length: int
    little_endian: bool = True
    signed: bool = False
    is_float: bool = False


@dataclass(frozen=True)
class MuxSelector:
    geometry: SignalGeometry
    value: int


@dataclass(frozen=True)
class DbcRampSpec:
    can_id: int
    extended: bool
    base_data: bytes
    geometry: SignalGeometry
    scale: float
    offset: float
    mux: MuxSelector | None = None


def normalize_can_ids(values: Iterable[str | int] | None) -> set[int]:
    """Convert hex strings or ints into a set of integer CAN IDs."""
    ids: set[int] = set()
    for value in values or ():
        if isinstance(value, str):
            text = value.strip()
            ids.add(int(text[2:] if text[:2].lower() == "0x" else text, 16))
        else:
            ids.add(int(value))
    return ids


def resolve_time_bounds(
    time_range: tuple[float, float] | None,
    markers: tuple[float, float] | None,
    origin: float = 0.0,
) -> tuple[float, float] | None:
    """Return sorted inclusive bounds shifted by origin, or None when no time filter applies."""
    bounds = markers if markers is not None else time_range
    if bounds is None:
        return None
    start, end = sorted((float(bounds[0]), float(bounds[1])))
    return start + origin, end + origin


def select_replay_subset(
    dataframe: pl.DataFrame,
    *,
    can_ids: Iterable[str | int] | None = None,
    time_range: tuple[float, float] | None = None,
    markers: tuple[float, float] | None = None,
    time_origin: float = 0.0,
) -> pl.DataFrame:
    """Return an ordered replay subset filtered by IDs and an optional inclusive time range."""
    selected = dataframe
    ids = normalize_can_ids(can_ids)
    if ids:
        parsed = pl.col("ID").cast(pl.String).str.replace("^0[xX]", "").str.to_integer(base=16, strict=False)
        selected = selected.filter(parsed.is_in(sorted(ids)))
    bounds = resolve_time_bounds(time_range, markers, time_origin)
    if bounds is not None:
        selected = selected.filter(pl.col("TS").cast(pl.Float64).is_between(bounds[0], bounds[1], closed="both"))
    return selected


def ramp_values(start: float, stop: float, step: float) -> list[float]:
    """Return start + i*step values that include the stop value."""
    if not isfinite(step) or step == 0 or not all(isfinite(v) for v in (start, stop)):
        raise ValueError("Ramp values and a nonzero step must be finite")
    span = (stop - start) / step
    if span < -_VALUE_TOLERANCE:
        raise ValueError("Step direction does not reach the stop value")
    span = max(span, 0.0)
    nearest = round(span)
    on_grid = abs(span - nearest) <= _VALUE_TOLERANCE
    steps = nearest if on_grid else floor(span)
    values = [start + index * step for index in range(steps + 1)]
    if on_grid:
        values[-1] = stop
    else:
        values.append(stop)
    return values


def generate_signal_ramp(
    *, can_id: str | int, base_data: bytes, geometry: SignalGeometry,
    start: float, stop: float, step: float, scale: float = 1.0, offset: float = 0.0,
    extended: bool = False, maximum_frames: int = 10000, mux: MuxSelector | None = None,
    run_id: str = "",
) -> tuple[ResolvedFrame, ...]:
    """Encode a finite physical-value ramp into classic CAN frames."""
    if not 1 <= len(base_data) <= 8:
        raise ValueError("Base payload must contain 1 to 8 bytes")
    if geometry.length <= 0 or geometry.length > 64 or geometry.start_bit < 0:
        raise ValueError("Invalid signal geometry")
    if not all(isfinite(v) for v in (scale, offset)) or scale == 0:
        raise ValueError("Scale must be finite and nonzero, and offset finite")
    payload_bits = len(base_data) * 8
    positions = _bit_positions(geometry, payload_bits)
    mux_positions = _bit_positions(mux.geometry, payload_bits) if mux is not None else ()
    if isfinite(step) and step and abs((stop - start) / step) > maximum_frames:
        raise ValueError("Ramp exceeds the configured frame count")
    values = ramp_values(start, stop, step)
    if len(values) > maximum_frames:
        raise ValueError("Ramp exceeds the configured frame count")
    numeric_id = _parse_id(can_id)
    prefix = f"active-re:{run_id}:" if run_id else "active-re:"
    frames: list[ResolvedFrame] = []
    for index, physical in enumerate(values):
        raw = _encode_raw(physical, geometry, scale, offset)
        payload = bytearray(base_data)
        if mux is not None:
            _write_bits(payload, mux_positions, mux.value & ((1 << mux.geometry.length) - 1))
        _write_bits(payload, positions, raw)
        frames.append(ResolvedFrame(f"{prefix}{index}", numeric_id, bytes(payload), extended))
    return tuple(frames)


def resolve_dbc_signal(
    dbc_manager: Any, dbc_name: str, message_name: str, signal_name: str,
    *, priority: int = 6, source_address: int = 0xFE,
) -> DbcRampSpec:
    """Build ramp parameters (full CAN ID, geometry, type, mux) for a DBC signal."""
    definition = dbc_manager.get_signal_definition(dbc_name, message_name, signal_name)
    message = next(m for m in dbc_manager.get_messages(dbc_name) if m.name == message_name)
    type_data = str(definition.get("type_data", "uint"))
    geometry = SignalGeometry(int(definition["start_bit"]), int(definition["length"]), bool(definition["le"]),
                              signed=type_data == "int", is_float=type_data.startswith("float"))
    mux = None
    if definition.get("mux_value") is not None:
        selector = _mux_selector_signal(message, message.get_signal_by_name(signal_name))
        if selector is not None:
            mux = MuxSelector(SignalGeometry(int(selector.start), int(selector.length),
                                             getattr(selector, "byte_order", "little_endian") == "little_endian"),
                              int(definition["mux_value"]))
    frame_id = int(message.frame_id)
    extended = bool(getattr(message, "is_extended_frame", frame_id > 0x7FF)) or frame_id > 0x7FF
    entry = dbc_manager.get_entry(dbc_name)
    if entry is not None and entry.mode == "j1939":
        can_id, extended = _j1939_full_id(frame_id, extended, priority, source_address), True
    else:
        can_id = frame_id & 0x1FFFFFFF if extended else frame_id
    return DbcRampSpec(can_id, extended, bytes(int(message.length)), geometry,
                       float(definition["scale"]), float(definition["offset"]), mux)


def _j1939_full_id(frame_id: int, extended: bool, priority: int, source_address: int) -> int:
    if extended:
        frame_id &= 0x1FFFFFFF
        pgn = J1939.extract_pgn(frame_id)
        if pgn is not None:
            full = J1939.pgn_to_frame_id(pgn, priority=(frame_id >> 26) & 0x7, source_address=frame_id & 0xFF)
            destination = (frame_id & 0xFF00) if ((frame_id >> 16) & 0xFF) < 0xF0 else 0
            return full | destination
    return J1939.pgn_to_frame_id(frame_id & 0x3FFFF, priority=priority, source_address=source_address)


def _mux_selector_signal(message: Any, signal: Any) -> Any:
    name = getattr(signal, "multiplexer_signal", None)
    if name:
        try:
            return message.get_signal_by_name(name)
        except KeyError:
            pass
    return next((s for s in message.signals if getattr(s, "is_multiplexer", False)), None)


def _parse_id(can_id: str | int) -> int:
    return next(iter(normalize_can_ids((can_id,))))


def _encode_raw(physical: float, geometry: SignalGeometry, scale: float, offset: float) -> int:
    raw_value = (physical - offset) / scale
    length = geometry.length
    if geometry.is_float:
        if length not in (32, 64):
            raise ValueError("Float signals must be 32 or 64 bits long")
        try:
            packed = struct.pack(">f" if length == 32 else ">d", raw_value)
        except OverflowError as exc:
            raise ValueError(f"Signal value {physical} is outside its representable range") from exc
        return int.from_bytes(packed, "big")
    raw = int(round(raw_value))
    low, high = (-(1 << (length - 1)), (1 << (length - 1)) - 1) if geometry.signed else (0, (1 << length) - 1)
    if abs(raw_value - raw) > _VALUE_TOLERANCE or raw < low or raw > high:
        raise ValueError(f"Signal value {physical} is outside its representable range")
    return raw & ((1 << length) - 1)


def _write_bits(payload: bytearray, positions: tuple[int, ...], raw: int) -> None:
    for raw_index, payload_index in enumerate(positions):
        bit = (raw >> raw_index) & 1
        byte_index, bit_index = divmod(payload_index, 8)
        payload[byte_index] = (payload[byte_index] & ~(1 << bit_index)) | (bit << bit_index)


def _bit_positions(geometry: SignalGeometry, payload_bits: int) -> tuple[int, ...]:
    """Return payload bit positions ordered from the signal LSB to its MSB."""
    if geometry.little_endian:
        positions = tuple(range(geometry.start_bit, geometry.start_bit + geometry.length))
    else:
        msb_first = []
        position = geometry.start_bit
        for _ in range(geometry.length):
            msb_first.append(position)
            position = position + 15 if position % 8 == 0 else position - 1
        positions = tuple(reversed(msb_first))
    if any(position >= payload_bits for position in positions):
        raise ValueError("Signal geometry exceeds payload length")
    return positions
