from __future__ import annotations

from dataclasses import dataclass

from models.can_send import TransmitEntry
from utils.can_id import can_id_to_int


class TransmitEntryError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedFrame:
    entry_id: str
    can_id: int
    data: bytes
    extended: bool


def resolve_transmit_entry(entry: TransmitEntry) -> ResolvedFrame:
    """The single choke point both the raw-hex and DBC-assisted editors funnel
    through before a frame ever reaches the send path. Validates strictly
    (unlike utils.can_bytes.parse_hex_bytes, which is lenient for display) --
    a TX tool should refuse a malformed frame rather than silently pad it."""
    try:
        can_id_int = can_id_to_int(entry.can_id)
    except ValueError as exc:
        raise TransmitEntryError(f"Invalid CAN ID '{entry.can_id}'") from exc

    if not (0 <= entry.dlc <= 8):
        raise TransmitEntryError("DLC must be between 0 and 8 (classic CAN)")

    text = str(entry.data_hex or "").strip()
    if len(text) % 2 != 0:
        raise TransmitEntryError(f"Data hex must have an even number of digits: '{entry.data_hex}'")
    try:
        data = bytes.fromhex(text)
    except ValueError as exc:
        raise TransmitEntryError(f"Invalid hex data '{entry.data_hex}'") from exc

    if len(data) != entry.dlc:
        raise TransmitEntryError(
            f"DLC mismatch: {entry.dlc} declared but {len(data)} byte(s) of data"
        )

    return ResolvedFrame(entry_id=entry.entry_id, can_id=can_id_int, data=data, extended=bool(entry.extended))


def encode_dbc_payload(message, signal_values: dict) -> str:
    """Wraps cantools.Message.encode(...) for the DBC-assisted editor's Apply
    step. strict=False (unlike the decode path) since pushing an
    out-of-declared-range value is a legitimate TX/fault-injection use case.
    cantools requires every signal to have a value regardless of `padding`
    (that flag only controls unused BIT padding, not missing signals) --
    default any signal the caller didn't supply to its minimum (or 0)."""
    complete_values = dict(signal_values)
    for signal in message.signals:
        if signal.name not in complete_values:
            complete_values[signal.name] = signal.minimum if signal.minimum is not None else 0
    return message.encode(complete_values, scaling=True, padding=True, strict=False).hex().upper()


def build_cansend_command(iface: str, can_id: int, data: bytes, extended: bool) -> str:
    """can-utils' cansend infers standard-vs-extended purely from the ID
    string's hex digit count (<=3 digits => 11-bit, up to 8 => 29-bit) -- pad
    explicitly rather than f"{id:X}" so the wrong width can't silently send
    the wrong frame type."""
    width = 8 if extended else 3
    return f"cansend {iface} {can_id:0{width}X}#{data.hex().upper()}"
