from __future__ import annotations

import copy
import math
import os
import re
import tempfile
from pathlib import Path

from cantools.database.can import Database, Message, Signal
from cantools.database.conversion import BaseConversion

from utils.can_id import can_id_to_int

_DBC_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BYTE_ORDERS = {"little_endian", "big_endian"}


class DbcValidationError(ValueError):
    """A working DBC edit violates a database or signal invariant."""


class WorkingDbc:
    """Editable Qt-free classic CAN database with validated mutations."""

    def __init__(
        self,
        database: Database | None = None,
        *,
        name: str = "Canlytics_Working",
        source_path: str | Path | None = None,
    ):
        if not _DBC_NAME.fullmatch(name):
            raise DbcValidationError("database name must be a valid DBC identifier")
        self._name = name
        self._source_path = Path(source_path).expanduser().resolve() if source_path is not None else None
        messages = copy.deepcopy(database.messages) if database is not None else []
        self._database = Database(
            messages=messages,
            nodes=copy.deepcopy(database.nodes) if database is not None else [],
            buses=copy.deepcopy(database.buses) if database is not None else [],
            version=database.version if database is not None else None,
            strict=False,
        )
        self._database.refresh()
        for message in self._database.messages:
            self._validate_message(message)

    @property
    def database(self) -> Database:
        return self._database

    def list_messages(self) -> list[Message]:
        return sorted(self._database.messages, key=lambda message: message.frame_id)

    def get_message(self, frame_id: int | str) -> Message:
        can_id = _parse_frame_id(frame_id)
        message = next((item for item in self._database.messages if item.frame_id == can_id), None)
        if message is None:
            raise KeyError(f"Message not found: {frame_id}")
        return message

    def create_message(
        self,
        name: str,
        frame_id: int | str,
        *,
        length: int = 8,
        is_extended_frame: bool | None = None,
        comment: str | None = None,
    ) -> Message:
        can_id = _parse_frame_id(frame_id)
        extended = can_id > 0x7FF if is_extended_frame is None else bool(is_extended_frame)
        self._validate_name(name, "message")
        self._validate_frame(can_id, length, extended)
        if any(message.name == name for message in self._database.messages):
            raise DbcValidationError(f"message name already exists: {name}")
        if any(message.frame_id == can_id for message in self._database.messages):
            raise DbcValidationError(f"CAN ID already exists: {can_id:X}")
        message = Message(
            frame_id=can_id,
            name=name,
            length=length,
            signals=[],
            is_extended_frame=extended,
            comment=comment,
            strict=False,
        )
        self._database.messages.append(message)
        self._database.refresh()
        return message

    def update_message(
        self,
        frame_id: int | str,
        *,
        name: str | None = None,
        new_frame_id: int | str | None = None,
        length: int | None = None,
        comment: str | None = None,
        is_extended_frame: bool | None = None,
    ) -> Message:
        message = self.get_message(frame_id)
        updated_name = name if name is not None else message.name
        updated_id = _parse_frame_id(new_frame_id) if new_frame_id is not None else message.frame_id
        updated_length = length if length is not None else message.length
        extended = (
            bool(is_extended_frame)
            if is_extended_frame is not None
            else message.is_extended_frame or updated_id > 0x7FF
        )
        self._validate_name(updated_name, "message")
        self._validate_frame(updated_id, updated_length, extended)
        if any(item is not message and item.name == updated_name for item in self._database.messages):
            raise DbcValidationError(f"message name already exists: {updated_name}")
        if any(item is not message and item.frame_id == updated_id for item in self._database.messages):
            raise DbcValidationError(f"CAN ID already exists: {updated_id:X}")
        candidate = copy.deepcopy(message)
        candidate.name = updated_name
        candidate.frame_id = updated_id
        candidate.length = updated_length
        candidate.is_extended_frame = extended
        if comment is not None:
            candidate.comment = comment
        self._validate_message(candidate)
        index = self._database.messages.index(message)
        self._database.messages[index] = candidate
        self._database.refresh()
        return candidate

    def delete_message(self, frame_id: int | str) -> None:
        message = self.get_message(frame_id)
        self._database.messages.remove(message)
        self._database.refresh()

    def create_signal(
        self,
        frame_id: int | str,
        name: str,
        *,
        start: int,
        length: int,
        byte_order: str = "little_endian",
        is_signed: bool = False,
        scale: float = 1.0,
        offset: float = 0.0,
        unit: str | None = None,
        minimum: float | None = None,
        maximum: float | None = None,
        comment: str | None = None,
        is_float: bool = False,
        is_multiplexer: bool = False,
        multiplexer_signal: str | None = None,
        multiplexer_ids: list[int] | None = None,
    ) -> Signal:
        message = self.get_message(frame_id)
        self._validate_name(name, "signal")
        if any(signal.name == name for signal in message.signals):
            raise DbcValidationError(f"signal name already exists: {name}")
        signal = Signal(
            name=name,
            start=start,
            length=length,
            byte_order=byte_order,
            is_signed=is_signed,
            conversion=BaseConversion.factory(scale=scale, offset=offset, is_float=is_float),
            unit=unit or None,
            minimum=minimum,
            maximum=maximum,
            comment=comment,
            is_multiplexer=is_multiplexer,
            multiplexer_signal=multiplexer_signal,
            multiplexer_ids=list(multiplexer_ids) if multiplexer_ids is not None else None,
        )
        self._validate_signal(message, signal)
        message.signals.append(signal)
        self._database.refresh()
        return signal

    def update_signal(
        self,
        frame_id: int | str,
        name: str,
        *,
        new_name: str | None = None,
        **changes: object,
    ) -> Signal:
        message = self.get_message(frame_id)
        current = message.get_signal_by_name(name)
        if current is None:
            raise KeyError(f"Signal not found: {name}")
        allowed = {
            "name", "start", "length", "byte_order", "is_signed", "scale", "offset", "unit",
            "minimum", "maximum", "comment", "is_float", "is_multiplexer", "multiplexer_signal",
            "multiplexer_ids",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise TypeError(f"unknown signal fields: {', '.join(sorted(unknown))}")
        values = {
            "name": new_name if new_name is not None else current.name,
            "start": current.start,
            "length": current.length,
            "byte_order": current.byte_order,
            "is_signed": current.is_signed,
            "scale": current.scale,
            "offset": current.offset,
            "unit": current.unit,
            "minimum": current.minimum,
            "maximum": current.maximum,
            "comment": current.comment,
            "is_float": current.is_float,
            "is_multiplexer": current.is_multiplexer,
            "multiplexer_signal": current.multiplexer_signal,
            "multiplexer_ids": current.multiplexer_ids,
        }
        values.update(changes)
        candidate = Signal(
            name=values["name"],
            start=values["start"],
            length=values["length"],
            byte_order=values["byte_order"],
            is_signed=values["is_signed"],
            conversion=BaseConversion.factory(
                scale=values["scale"], offset=values["offset"], is_float=values["is_float"],
            ),
            unit=values["unit"] or None,
            minimum=values["minimum"],
            maximum=values["maximum"],
            comment=values["comment"],
            is_multiplexer=values["is_multiplexer"],
            multiplexer_signal=values["multiplexer_signal"],
            multiplexer_ids=list(values["multiplexer_ids"]) if values["multiplexer_ids"] is not None else None,
        )
        self._validate_name(candidate.name, "signal")
        if any(item is not current and item.name == candidate.name for item in message.signals):
            raise DbcValidationError(f"signal name already exists: {candidate.name}")
        self._validate_signal(message, candidate, excluding=current)
        updated_message = copy.deepcopy(message)
        index = next(index for index, item in enumerate(message.signals) if item.name == name)
        updated_message.signals[index] = candidate
        if current.is_multiplexer and candidate.name != current.name:
            for item in updated_message.signals:
                if item.multiplexer_signal == current.name:
                    item.multiplexer_signal = candidate.name
        updated_message.refresh(strict=False)
        self._validate_message(updated_message)
        self._database.messages[self._database.messages.index(message)] = updated_message
        self._database.refresh()
        return candidate

    def delete_signal(self, frame_id: int | str, name: str) -> None:
        message = self.get_message(frame_id)
        signal = message.get_signal_by_name(name)
        if signal is None:
            raise KeyError(f"Signal not found: {name}")
        if signal.is_multiplexer and any(item.multiplexer_signal == name for item in message.signals):
            raise DbcValidationError("cannot delete a multiplexer while dependent signals exist")
        message.signals.remove(signal)
        self._database.refresh()

    def export(self, path: str | Path) -> Path:
        output = Path(path).expanduser()
        if output.suffix.lower() != ".dbc":
            raise DbcValidationError("working DBC export path must end in .dbc")
        if self._source_path is not None and output.resolve() == self._source_path:
            raise DbcValidationError("working DBC export cannot overwrite its source DBC")
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(self._database.as_dbc_string(sort_signals="default"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, output)
        except BaseException:
            Path(temporary_name).unlink(missing_ok=True)
            raise
        return output

    @staticmethod
    def _validate_name(name: str, kind: str) -> None:
        if not isinstance(name, str) or not _DBC_NAME.fullmatch(name):
            raise DbcValidationError(f"{kind} name must be a valid DBC identifier")

    @staticmethod
    def _validate_frame(frame_id: int, length: int, is_extended_frame: bool) -> None:
        if isinstance(frame_id, bool) or frame_id < 0 or frame_id > (0x1FFFFFFF if is_extended_frame else 0x7FF):
            raise DbcValidationError("CAN ID is outside the selected frame format")
        if isinstance(length, bool) or not isinstance(length, int) or not 0 <= length <= 8:
            raise DbcValidationError("classic CAN message length must be between 0 and 8 bytes")

    @staticmethod
    def _validate_message(message: Message) -> None:
        names: set[str] = set()
        for signal in message.signals:
            WorkingDbc._validate_name(signal.name, "signal")
            if signal.name in names:
                raise DbcValidationError(f"signal name already exists: {signal.name}")
            names.add(signal.name)
        for signal in message.signals:
            WorkingDbc._validate_signal(message, signal, excluding=signal)

    @staticmethod
    def _validate_signal(message: Message, signal: Signal, *, excluding: Signal | None = None) -> None:
        if signal.byte_order not in _BYTE_ORDERS:
            raise DbcValidationError("byte_order must be little_endian or big_endian")
        if isinstance(signal.start, bool) or not isinstance(signal.start, int):
            raise DbcValidationError("signal start must be an integer")
        if isinstance(signal.length, bool) or not isinstance(signal.length, int) or signal.length < 1:
            raise DbcValidationError("signal length must be a positive integer")
        if signal.is_float and signal.length not in {16, 32, 64}:
            raise DbcValidationError("floating-point signals must be 16, 32, or 64 bits")
        positions = _signal_bit_positions(signal.start, signal.length, signal.byte_order)
        if any(position >= message.length * 8 for position in positions):
            raise DbcValidationError("signal exceeds message length")
        if not math.isfinite(float(signal.scale)) or not math.isfinite(float(signal.offset)):
            raise DbcValidationError("signal scale and offset must be finite")
        if signal.minimum is not None and signal.maximum is not None and signal.minimum > signal.maximum:
            raise DbcValidationError("signal minimum must not exceed maximum")
        if any(value is not None and not math.isfinite(float(value)) for value in (signal.minimum, signal.maximum)):
            raise DbcValidationError("signal minimum and maximum must be finite")
        if signal.multiplexer_signal:
            selector = message.get_signal_by_name(signal.multiplexer_signal)
            if selector is None or not selector.is_multiplexer:
                raise DbcValidationError("multiplexer_signal must name a multiplexer in this message")
            if not signal.multiplexer_ids:
                raise DbcValidationError("multiplexer_ids must not be empty")
            if any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or value >= 1 << selector.length
                for value in signal.multiplexer_ids
            ):
                raise DbcValidationError("multiplexer ID is outside the selector's unsigned range")
        for existing in message.signals:
            if existing is excluding:
                continue
            if not positions.intersection(_signal_bit_positions(existing.start, existing.length, existing.byte_order)):
                continue
            if _mux_overlap_is_exclusive(signal, existing):
                continue
            raise DbcValidationError(f"signal overlaps {existing.name}")


def _parse_frame_id(frame_id: int | str) -> int:
    if isinstance(frame_id, bool) or not isinstance(frame_id, (int, str)):
        raise DbcValidationError(f"invalid CAN ID: {frame_id}")
    try:
        return can_id_to_int(frame_id) if isinstance(frame_id, str) else int(frame_id)
    except (TypeError, ValueError) as exc:
        raise DbcValidationError(f"invalid CAN ID: {frame_id}") from exc


def _signal_bit_positions(start: int, length: int, byte_order: str) -> set[int]:
    if start < 0 or start >= 64 or length < 1:
        raise DbcValidationError("signal bit range is outside classic CAN payload")
    positions: list[int] = []
    if byte_order == "little_endian":
        positions.extend(range(start, start + length))
    else:
        byte, bit = divmod(start, 8)
        for _ in range(length):
            positions.append(byte * 8 + bit)
            if bit > 0:
                bit -= 1
            else:
                byte += 1
                bit = 7
    if any(position < 0 or position >= 64 for position in positions):
        raise DbcValidationError("signal bit range is outside classic CAN payload")
    return set(positions)


def _mux_overlap_is_exclusive(first: Signal, second: Signal) -> bool:
    if first.is_multiplexer and second.multiplexer_signal == first.name:
        return True
    if second.is_multiplexer and first.multiplexer_signal == second.name:
        return True
    return bool(
        first.multiplexer_signal
        and first.multiplexer_signal == second.multiplexer_signal
        and first.multiplexer_ids
        and second.multiplexer_ids
        and set(first.multiplexer_ids).isdisjoint(second.multiplexer_ids)
    )
