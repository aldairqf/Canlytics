from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from services.dbc_manager import DbcManager


class SessionStateStore:
    def __init__(self, root: Path | None = None):
        self._root = Path(root or Path.cwd() / ".canalyzer_state")
        self._dbcs_dir = self._root / "dbcs"
        self._state_path = self._root / "session.json"

    def get_recent_logs(self) -> list[str]:
        return [str(path) for path in self._read().get("recent_logs", []) if path]

    def get_recent_dbcs(self) -> list[str]:
        return [str(path) for path in self._read().get("recent_dbcs", []) if path]

    def add_recent_log(self, path: str) -> None:
        data = self._read()
        data["recent_logs"] = self._push_recent(data.get("recent_logs", []), path)
        self._write(data)

    def add_recent_dbc(self, path: str) -> None:
        data = self._read()
        data["recent_dbcs"] = self._push_recent(data.get("recent_dbcs", []), path)
        self._write(data)

    def sync_dbc_manager(self, manager: DbcManager) -> None:
        data = self._read()
        snapshots = []
        for index, entry in enumerate(manager.list_entries()):
            stored_path = self._store_dbc_copy(entry.path)
            snapshots.append(
                {
                    "name": entry.name,
                    "path": stored_path,
                    "active": bool(entry.active),
                    "mode": entry.mode,
                    "order": index,
                }
            )
        data["dbcs"] = snapshots
        self._write(data)

    def restore_dbc_manager(self, manager: DbcManager) -> None:
        saved = self.get_saved_dbcs()
        if not saved:
            return

        restored_names: list[str] = []
        active_names: set[str] = set()

        for item in sorted(saved, key=lambda row: int(row.get("order", 0))):
            stored_path = str(item.get("path") or "").strip()
            if not stored_path:
                continue
            path_obj = Path(stored_path)
            if not path_obj.exists():
                continue
            try:
                db = manager.load_database(str(path_obj))
                entry = manager.add_loaded_db(
                    str(path_obj),
                    db,
                    preferred_name=str(item.get("name") or path_obj.stem),
                    active=bool(item.get("active", True)),
                    mode=str(item.get("mode") or "exact"),
                )
            except Exception:
                continue
            restored_names.append(entry.name)
            if entry.active:
                active_names.add(entry.name)

        if restored_names:
            manager.set_order(restored_names)
            manager.set_active(active_names)

    def get_saved_dbcs(self) -> list[dict]:
        data = self._read()
        return list(data.get("dbcs", []) or [])

    def is_cached_dbc_path(self, path: str) -> bool:
        try:
            return Path(path).resolve().parent == self._dbcs_dir.resolve()
        except Exception:
            return False

    def _store_dbc_copy(self, path: str) -> str:
        source = Path(path)
        if not source.exists():
            return str(source)

        self._dbcs_dir.mkdir(parents=True, exist_ok=True)
        try:
            if source.resolve().parent == self._dbcs_dir.resolve():
                return str(source.resolve())
        except Exception:
            pass
        digest = hashlib.sha1(str(source.resolve()).encode("utf-8", errors="ignore")).hexdigest()[:12]
        target = self._dbcs_dir / f"{source.stem}_{digest}{source.suffix or '.dbc'}"
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return str(target)

    # ------------------------------------------------------------------
    # Signal tags (user-defined names for candidate signals)
    # ------------------------------------------------------------------

    @property
    def signal_tags_path(self) -> Path:
        return self._root / "signal_tags.json"

    def get_signal_tags(self) -> dict[str, str]:
        path = self.signal_tags_path
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def set_signal_tag(self, label: str, name: str) -> None:
        tags = self.get_signal_tags()
        tags[label] = name
        self._root.mkdir(parents=True, exist_ok=True)
        self.signal_tags_path.write_text(json.dumps(tags, indent=2), encoding="utf-8")

    def remove_signal_tag(self, label: str) -> None:
        tags = self.get_signal_tags()
        tags.pop(label, None)
        self._root.mkdir(parents=True, exist_ok=True)
        self.signal_tags_path.write_text(json.dumps(tags, indent=2), encoding="utf-8")

    def _read(self) -> dict:
        if not self._state_path.exists():
            return {"recent_logs": [], "recent_dbcs": [], "dbcs": []}
        try:
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception:
            return {"recent_logs": [], "recent_dbcs": [], "dbcs": []}

    def _write(self, data: dict) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def _push_recent(items: list[str], path: str, *, limit: int = 10) -> list[str]:
        normalized = str(Path(path))
        result = [normalized]
        for item in items:
            if str(item) == normalized:
                continue
            result.append(str(item))
        return result[:limit]
