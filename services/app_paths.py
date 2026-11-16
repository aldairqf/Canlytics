from __future__ import annotations

import getpass
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from config.defaults import STATE_DIRECTORY_NAME

logger = logging.getLogger(__name__)
_RESOLVED_ROOTS: dict[str, Path] = {}
_RESOLVED_ROOTS_LOCK = threading.Lock()
_MIGRATION_LOCK_NAME = ".migration.lock"
_MIGRATION_MARKER_NAME = "migration.json"


def _default_state_root() -> Path:
    configured = os.environ.get("CANLYTICS_STATE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            return Path(appdata) / "Canlytics" / "state"
        return Path.home() / "AppData" / "Roaming" / "Canlytics" / "state"
    data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    if data_home:
        return Path(data_home).expanduser() / "canlytics" / "state"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Canlytics" / "state"
    return Path.home() / ".local" / "share" / "canlytics" / "state"


def _legacy_state_roots() -> tuple[Path, ...]:
    candidates: list[Path] = []
    try:
        candidates.append(Path.cwd() / STATE_DIRECTORY_NAME)
    except Exception:
        logger.exception("Could not inspect current directory for legacy state")
    if getattr(sys, "frozen", False):
        try:
            candidates.append(Path(sys.executable).resolve().parent / STATE_DIRECTORY_NAME)
        except Exception:
            logger.exception("Could not inspect executable directory for legacy state")
    else:
        try:
            candidates.append(Path(__file__).resolve().parent.parent / STATE_DIRECTORY_NAME)
        except Exception:
            logger.exception("Could not inspect repository directory for legacy state")
    return tuple(dict.fromkeys(candidates))


def _write_json_atomic(path: Path, data: dict) -> None:
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _find_legacy_state(destination: Path) -> Path | None:
    candidates: list[tuple[int, Path]] = []
    try:
        roots = _legacy_state_roots()
    except Exception:
        logger.exception("Could not enumerate legacy state locations")
        return None
    for source in roots:
        try:
            if source == destination or not source.is_dir():
                continue
            session_path = source / "session.json"
            if session_path.is_file():
                candidates.append((session_path.stat().st_mtime_ns, source))
        except Exception:
            logger.exception("Could not inspect legacy state candidate %s", source)
    return max(candidates, default=(0, None), key=lambda item: item[0])[1]


def _rewrite_legacy_paths(session: dict, source: Path, destination: Path) -> dict:
    entries = session.get("dbcs", [])
    if not isinstance(entries, list):
        return session
    try:
        source_root = source.resolve()
    except Exception:
        logger.exception("Could not resolve legacy state root %s", source)
        return session
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        stored_path = str(entry.get("path") or "").strip()
        if not stored_path:
            continue
        try:
            relative = Path(stored_path).resolve().relative_to(source_root)
        except (OSError, ValueError):
            continue
        entry["path"] = str(destination / relative)
    return session


def _copy_legacy_files(source: Path, destination: Path) -> tuple[bool, int]:
    failed = False
    copied = 0
    try:
        files = sorted(path for path in source.rglob("*") if path.is_file() and path != source / "session.json")
    except OSError:
        logger.exception("Could not enumerate legacy state files under %s", source)
        return True, copied
    for source_file in files:
        target = destination / source_file.relative_to(source)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(source_file, target)
                copied += 1
        except OSError:
            failed = True
            logger.exception("Could not copy legacy state file %s", source_file)
    return failed, copied


def _migration_marker(destination: Path, source: Path | None, status: str) -> None:
    marker_path = destination / _MIGRATION_MARKER_NAME
    if marker_path.exists():
        return
    try:
        _write_json_atomic(
            marker_path,
            {"source": str(source) if source is not None else None, "status": status, "timestamp": datetime.now(timezone.utc).isoformat()},
        )
    except OSError:
        logger.exception("Could not write state migration marker %s", marker_path)


def _migration_enabled() -> bool:
    value = os.environ.get("CANLYTICS_STATE_MIGRATION", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _migrate_once(destination: Path) -> None:
    marker_path = destination / _MIGRATION_MARKER_NAME
    if marker_path.exists():
        return
    lock_path = destination / _MIGRATION_LOCK_NAME
    lock_fd: int | None = None
    deadline = time.monotonic() + 0.25
    while lock_fd is None:
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > 60:
                    lock_path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if marker_path.exists() or time.monotonic() >= deadline:
                return
            time.sleep(0.025)
        except OSError:
            logger.exception("Could not lock state migration at %s", destination)
            return
    try:
        if marker_path.exists():
            return
        source: Path | None = None
        status = "existing_state" if (destination / "session.json").exists() else "disabled"
        if status != "existing_state" and _migration_enabled():
            source = _find_legacy_state(destination)
            status = "no_legacy_state"
            if source is not None:
                failed, copied = _copy_legacy_files(source, destination)
                if failed:
                    status = "partial"
                else:
                    try:
                        legacy_session = json.loads((source / "session.json").read_text(encoding="utf-8"))
                        if isinstance(legacy_session, dict):
                            migrated = _rewrite_legacy_paths(legacy_session, source, destination)
                            _write_json_atomic(destination / "session.json", migrated)
                            status = "migrated"
                        else:
                            status = "invalid_session"
                    except (OSError, json.JSONDecodeError):
                        logger.exception("Could not migrate legacy session file from %s", source)
                        status = "partial"
                if status == "migrated":
                    logger.warning("Migrated %d legacy state files from %s to %s", copied + 1, source, destination)
                else:
                    logger.warning("Legacy state migration from %s ended with status %s", source, status)
        _migration_marker(destination, source, status)
    finally:
        try:
            os.close(lock_fd)
        finally:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                logger.exception("Could not remove state migration lock %s", lock_path)


def _fallback_state_dir() -> Path:
    try:
        username = getpass.getuser()
    except Exception:
        username = "user"
    try:
        destination = Path(tempfile.gettempdir()) / f"Canlytics-{username}" / "state"
        destination.mkdir(parents=True, exist_ok=True)
        return destination
    except Exception:
        logger.exception("Could not create named temporary state directory")
    try:
        return Path(tempfile.mkdtemp(prefix="canlytics-state-"))
    except Exception:
        logger.exception("Could not create temporary state directory")
    try:
        return Path(os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir()) / "canlytics-state"
    except Exception:
        return Path("canlytics-state")


def resolve_state_dir() -> Path:
    """Return a cached per-user state path without allowing path errors to escape."""
    try:
        selected = _default_state_root()
    except Exception:
        logger.exception("Could not determine the configured state directory")
        selected = None
    key = str(selected) if selected is not None else "<fallback>"
    with _RESOLVED_ROOTS_LOCK:
        cached = _RESOLVED_ROOTS.get(key)
    if cached is not None:
        return cached
    try:
        if selected is None:
            raise OSError("state root is unavailable")
        selected.mkdir(parents=True, exist_ok=True)
        destination = selected
    except Exception:
        logger.exception("Could not create configured state directory %s", selected)
        destination = _fallback_state_dir()
    try:
        _migrate_once(destination)
    except Exception:
        logger.exception("Unexpected state migration error at %s", destination)
    with _RESOLVED_ROOTS_LOCK:
        _RESOLVED_ROOTS[key] = destination
    return destination
