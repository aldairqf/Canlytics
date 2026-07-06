from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cantools
from PySide6.QtCore import QObject, Signal as QtSignal

from services.signal_formatting import format_signal_value, normalize_display_text
from utils.can_id import can_id_to_int


@dataclass(frozen=True)
class DbcEntry:
    name: str
    path: str
    active: bool
    mode: str
    db: cantools.database.Database


class DbcManager(QObject):
    entries_changed = QtSignal()

    def __init__(self):
        super().__init__()
        self._entries: dict[str, DbcEntry] = {}
        self._paths: dict[str, str] = {}
        self._order: list[str] = []
        self._message_cache_exact: dict[str, dict[int, str]] = {}
        self._message_cache_pgn: dict[str, dict[int, str]] = {}
        self._message_obj_cache_exact: dict[str, dict[int, object]] = {}
        self._message_obj_cache_pgn: dict[str, dict[int, object]] = {}
        self._version = 0

    @staticmethod
    def _normalize_id(frame_id: int) -> int:
        return int(frame_id) & 0x1FFFFFFF

    def list_entries(self) -> list[DbcEntry]:
        entries = []
        for name in self._order:
            entry = self._entries.get(name)
            if entry:
                entries.append(entry)
        for name, entry in self._entries.items():
            if name not in self._order:
                entries.append(entry)
        return entries

    def get_entry(self, name: str) -> DbcEntry | None:
        return self._entries.get(name)

    def load_dbc(self, path: str) -> DbcEntry:
        path_obj = Path(path)
        resolved = str(path_obj.resolve())

        if resolved in self._paths:
            return self._entries[self._paths[resolved]]

        db = self.load_database(resolved)
        return self.add_loaded_db(resolved, db)

    def add_loaded_db(
        self,
        path: str,
        db,
        *,
        preferred_name: str | None = None,
        active: bool = True,
        mode: str = "exact",
    ) -> DbcEntry:
        path_obj = Path(path)
        resolved = str(path_obj.resolve())

        if resolved in self._paths:
            return self._entries[self._paths[resolved]]

        name = preferred_name or getattr(db, "name", None) or path_obj.stem
        name = self._unique_name(name)

        entry = DbcEntry(
            name=name,
            path=resolved,
            active=active,
            mode=mode,
            db=db,
        )
        self._entries[name] = entry
        self._paths[resolved] = name
        self._order.append(name)
        self._touch()
        return entry

    def load_database(self, path: str) -> cantools.database.Database:
        try:
            db = cantools.database.load_file(path)
        except Exception:
            db = cantools.database.load_file(path, strict=False)
        self._sanitize_db(db)
        return db

    def _sanitize_db(self, db) -> None:
        for message in getattr(db, "messages", []) or []:
            try:
                length = int(getattr(message, "length", 0) or 0)
            except Exception:
                length = 0
            if length > 0:
                continue
            min_len = 0
            for sig in getattr(message, "signals", []) or []:
                try:
                    end_bits = int(getattr(sig, "start", 0)) + int(getattr(sig, "length", 0))
                    min_len = max(min_len, (end_bits + 7) // 8)
                except Exception:
                    continue
            if min_len <= 0:
                min_len = 8
            try:
                setattr(message, "length", int(min_len))
            except Exception:
                pass

    def set_active(self, names: set[str]):
        updated = {}
        for name, entry in self._entries.items():
            updated[name] = DbcEntry(
                name=entry.name,
                path=entry.path,
                active=name in names,
                mode=entry.mode,
                db=entry.db,
            )
        self._entries = updated
        self._touch()

    def set_entry_mode(self, name: str, mode: str):
        entry = self._entries.get(name)
        if not entry:
            return
        updated = DbcEntry(
            name=entry.name,
            path=entry.path,
            active=entry.active,
            mode=mode,
            db=entry.db,
        )
        self._entries[name] = updated
        self._touch()

    def active_entries(self) -> list[DbcEntry]:
        return [entry for entry in self._entries.values() if entry.active]

    def set_order(self, names: list[str]):
        self._order = [name for name in names if name in self._entries]
        self._touch()

    def remove_entry(self, name: str) -> None:
        entry = self._entries.pop(name, None)
        if not entry:
            return
        self._paths.pop(entry.path, None)
        self._order = [n for n in self._order if n != name]
        self._touch()

    def get_dbc_names(self, active_only: bool = False) -> list[str]:
        entries = self.active_entries() if active_only else self.list_entries()
        return [entry.name for entry in entries]

    def get_message_names(self, dbc_name: str) -> list[str]:
        entry = self._entries.get(dbc_name)
        if not entry:
            return []
        return sorted(message.name for message in entry.db.messages)

    def get_signal_names(self, dbc_name: str, message_name: str) -> list[str]:
        message = self._get_message(dbc_name, message_name)
        if not message:
            return []
        return sorted(signal.name for signal in message.signals)

    def get_signal_definition(
        self,
        dbc_name: str,
        message_name: str,
        signal_name: str,
        *,
        scaled: bool = True,
    ) -> dict:
        entry = self._entries.get(dbc_name)
        message = self._get_message(dbc_name, message_name)
        if not message:
            raise KeyError("Message not found")

        signal = message.get_signal_by_name(signal_name)
        if not signal:
            raise KeyError("Signal not found")

        byte_order = getattr(signal, "byte_order", "little_endian")
        is_float = bool(getattr(signal, "is_float", False))
        is_signed = bool(getattr(signal, "is_signed", False))

        scale = float(signal.scale or 1.0)
        offset = float(signal.offset or 0.0)
        if not scaled:
            scale = 1.0
            offset = 0.0

        mux_start, mux_bytes, mux_value = self._get_mux_info(message, signal)
        match_mode = entry.mode if entry else "exact"
        try:
            message_length = int(getattr(message, "length", 0) or 0)
        except Exception:
            message_length = 0
        if match_mode == "j1939" and message_length > 8:
            match_mode = "bam"

        msg_id = self._normalize_id(int(message.frame_id))
        pgn = None
        if entry and entry.mode == "j1939":
            pgn = self._get_pgn(msg_id)

        return {
            "name": signal.name,
            "can_id": f"{(pgn if pgn is not None else msg_id):X}",
            "id_match": match_mode,
            "pgn": pgn,
            "start_bit": int(signal.start),
            "length": int(signal.length),
            "le": byte_order == "little_endian",
            "scale": scale,
            "offset": offset,
            "mux_start": mux_start,
            "mux_bytes": mux_bytes,
            "mux_value": mux_value,
            "type_data": "float32" if is_float else ("int" if is_signed else "uint"),
        }

    def _get_message(self, dbc_name: str, message_name: str):
        entry = self._entries.get(dbc_name)
        if not entry:
            return None
        try:
            return entry.db.get_message_by_name(message_name)
        except KeyError:
            return None

    def _get_mux_info(self, message, signal) -> tuple[int, int, int | None]:
        mux_value = None
        mux_start = 0
        mux_bytes = 0

        mux_ids = getattr(signal, "multiplexer_ids", None)
        if mux_ids:
            mux_ids_list = list(mux_ids)
            mux_value = mux_ids_list[0] if mux_ids_list else None

        if mux_ids:
            mux_signal_name = getattr(signal, "multiplexer_signal", None)
            mux_signal = None
            if mux_signal_name:
                try:
                    mux_signal = message.get_signal_by_name(mux_signal_name)
                except KeyError:
                    mux_signal = None
            if mux_signal is None:
                mux_signal = next(
                    (s for s in message.signals if getattr(s, "is_multiplexer", False)),
                    None,
                )
            if mux_signal:
                mux_start = int(mux_signal.start // 8)
                mux_bytes = max(1, int((mux_signal.length + 7) // 8))

        return mux_start, mux_bytes, mux_value

    # J1939 is always carried on 29-bit extended frames; an id that fits in an
    # 11-bit standard frame (<= 0x7FF) cannot be a real J1939 PDU. Without this
    # guard, pf/ps/dp all read as zero for such an id and it resolves to PGN 0
    # (e.g. TSC1) for practically every standard-id frame on the bus, silently
    # labeling unrelated non-J1939 traffic with whatever message owns PGN 0.
    _STANDARD_ID_MAX = 0x7FF

    @classmethod
    def _get_pgn(cls, frame_id: int) -> int | None:
        frame_id = int(frame_id) & 0x1FFFFFFF
        if frame_id <= cls._STANDARD_ID_MAX:
            return None

        dp = (frame_id >> 24) & 0x01
        pf = (frame_id >> 16) & 0xFF
        ps = (frame_id >> 8) & 0xFF

        if pf < 240:
            return (dp << 16) | (pf << 8)

        return (dp << 16) | (pf << 8) | ps
    def resolve_message_name(self, raw_id: str) -> str | None:
        if not raw_id:
            return None
        try:
            id_int = can_id_to_int(raw_id)
            id_int = self._normalize_id(id_int)
        except ValueError:
            return None

        ordered_names = self._order or [entry.name for entry in self.list_entries()]
        for name in ordered_names:
            entry = self._entries.get(name)
            if not entry or not entry.active:
                continue
            if entry.mode == "j1939":
                pgn = self._get_pgn(id_int)
                message_name = self._get_message_name_j1939(entry, pgn)
            else:
                message_name = self._get_message_name_exact(entry, id_int)
            if message_name:
                return message_name
        return None

    def resolve_message(self, raw_id: str):
        if not raw_id:
            return None
        try:
            id_int = can_id_to_int(raw_id)
            id_int = self._normalize_id(id_int)
        except ValueError:
            return None

        ordered_names = self._order or [entry.name for entry in self.list_entries()]
        for name in ordered_names:
            entry = self._entries.get(name)
            if not entry or not entry.active:
                continue
            if entry.mode == "j1939":
                pgn = self._get_pgn(id_int)
                message = self._get_message_obj_j1939(entry, pgn)
                if message:
                    return entry, message, pgn
            else:
                message = self._get_message_obj_exact(entry, id_int)
                if message:
                    return entry, message, None
        return None

    def get_message_by_pgn(self, pgn: int):
        for entry in self.active_entries():
            if entry.mode != "j1939":
                continue
            message = self._get_message_obj_j1939(entry, int(pgn))
            if message:
                return entry, message
        return None

    def decode_frame(self, raw_id: str, data_hex: str | None) -> list[dict]:
        resolved = self.resolve_message(raw_id)
        if not resolved or not data_hex:
            return []
        entry, message, _pgn = resolved
        try:
            data_bytes = bytes.fromhex(str(data_hex))
        except ValueError:
            return []

        if len(data_bytes) < message.length:
            data_bytes = data_bytes.ljust(message.length, b"\x00")
        elif len(data_bytes) > message.length:
            data_bytes = data_bytes[: message.length]

        try:
            decoded = message.decode(data_bytes, decode_choices=False)
        except Exception:
            return []

        items = []
        for signal in message.signals:
            if signal.name not in decoded:
                continue
            value = decoded[signal.name]
            value_str = format_signal_value(value)
            unit = normalize_display_text(getattr(signal, "unit", None))
            try:
                signal_def = self.get_signal_definition(
                    entry.name,
                    message.name,
                    signal.name,
                    scaled=True,
                )
            except Exception:
                signal_def = None
            items.append({
                "name": normalize_display_text(signal.name),
                "value": value_str,
                "unit": unit,
                "signal_def": signal_def,
            })
        return items

    def _get_message_name_exact(self, entry: DbcEntry, frame_id: int) -> str | None:
        cache = self._message_cache_exact.get(entry.name)
        if cache is None:
            cache = {}
            for message in entry.db.messages:
                cache.setdefault(self._normalize_id(int(message.frame_id)), message.name)
            self._message_cache_exact[entry.name] = cache
        return cache.get(frame_id)

    def _get_message_name_j1939(self, entry: DbcEntry, pgn: int) -> str | None:
        cache = self._message_cache_pgn.get(entry.name)
        if cache is None:
            cache = {}
            for message in entry.db.messages:
                cache.setdefault(self._get_pgn(int(message.frame_id)), message.name)
            self._message_cache_pgn[entry.name] = cache
        return cache.get(pgn)

    def _get_message_obj_exact(self, entry: DbcEntry, frame_id: int):
        cache = self._message_obj_cache_exact.get(entry.name)
        if cache is None:
            cache = {}
            for message in entry.db.messages:
                cache.setdefault(self._normalize_id(int(message.frame_id)), message)
            self._message_obj_cache_exact[entry.name] = cache
        return cache.get(frame_id)

    def _get_message_obj_j1939(self, entry: DbcEntry, pgn: int):
        cache = self._message_obj_cache_pgn.get(entry.name)
        if cache is None:
            cache = {}
            for message in entry.db.messages:
                cache.setdefault(self._get_pgn(int(message.frame_id)), message)
            self._message_obj_cache_pgn[entry.name] = cache
        return cache.get(pgn)

    def _clear_cache(self):
        self._message_cache_exact.clear()
        self._message_cache_pgn.clear()
        self._message_obj_cache_exact.clear()
        self._message_obj_cache_pgn.clear()

    def _touch(self):
        self._clear_cache()
        self._version += 1
        self.entries_changed.emit()

    @property
    def version(self) -> int:
        return self._version

    def _unique_name(self, name: str) -> str:
        candidate = name
        index = 1
        while candidate in self._entries:
            candidate = f"{name}_{index}"
            index += 1
        return candidate
