from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import logging
import os
import re
import shutil
import sys
import stat
import tempfile
import tomllib
import uuid
import zipfile
from pathlib import PurePosixPath
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Callable

from canlytics_sdk import PluginAPI, PluginContext, SDK_API_VERSION
from models.plugin import PluginRecord

logger = logging.getLogger(__name__)
_PLUGIN_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$")
_ENTRY_POINT = re.compile(r"^[a-zA-Z_][\w.]*:[a-zA-Z_][\w]*$")
_MAX_PLUGIN_ARCHIVE_MEMBERS = 4096
_MAX_PLUGIN_ARCHIVE_MEMBER_BYTES = 50 * 1024 * 1024
_MAX_PLUGIN_ARCHIVE_TOTAL_BYTES = 100 * 1024 * 1024


class PluginManager:
    """Discovers and isolates trusted plugins without depending on Qt."""

    def __init__(
        self,
        state_path: str | Path,
        *,
        plugin_dirs: tuple[str | Path, ...] | None = None,
        entry_points_provider: Callable[[], list] | None = None,
    ):
        self._state_path = Path(state_path)
        self._plugin_dirs = tuple(Path(path) for path in plugin_dirs) if plugin_dirs is not None else self.default_plugin_dirs()
        self._entry_points_provider = entry_points_provider or self._installed_entry_points
        self._enabled = self._read_state()
        self._records: dict[str, PluginRecord] = {}
        self._apis: dict[str, PluginAPI] = {}
        self._modules: dict[str, ModuleType] = {}
        self._added_import_paths: set[str] = set()

    @staticmethod
    def default_plugin_dirs() -> tuple[Path, ...]:
        configured = os.environ.get("CANLYTICS_PLUGINS_DIR", "").strip()
        if configured:
            return (Path(configured).expanduser(),)
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            return (Path(appdata) / "Canlytics" / "plugins",)
        return (Path.home() / ".canlytics" / "plugins",)

    def discover(self) -> tuple[PluginRecord, ...]:
        records: dict[str, PluginRecord] = {}
        for root in self._plugin_dirs:
            if not root.is_dir():
                continue
            try:
                folders = sorted(root.iterdir())
            except OSError as exc:
                logger.exception("Failed to scan plugin folder %s", root)
                plugin_id = f"_folder_{hashlib.sha256(str(root).encode('utf-8')).hexdigest()[:12]}"
                records[plugin_id] = PluginRecord(
                    id=plugin_id, name=str(root), version="", source="folder",
                    enabled=False, loaded=False, error=f"Discovery failed: {exc}", valid=False,
                )
                continue
            for folder in folders:
                if not folder.is_dir():
                    continue
                record = self._discover_folder(folder)
                if record is not None:
                    self._insert_record(records, record)
        try:
            for entry_point in self._entry_points_provider():
                plugin_id = str(entry_point.name).strip()
                distribution = getattr(entry_point, "dist", None)
                version = str(getattr(distribution, "version", "unknown"))
                valid = bool(_PLUGIN_ID.fullmatch(plugin_id))
                record = PluginRecord(
                    id=plugin_id,
                    name=plugin_id,
                    version=version,
                    source="package",
                    enabled=self._enabled.get(plugin_id, False) if valid else False,
                    loaded=False,
                    entry_point=entry_point.value,
                    error="Invalid package plugin id" if not valid else "",
                    valid=valid,
                )
                self._insert_record(records, record)
        except Exception as exc:
            logger.exception("Failed to enumerate Canlytics plugin entry points")
            records["_entry_points"] = PluginRecord(
                id="_entry_points", name="Installed packages", version="", source="package",
                enabled=False, loaded=False, error=f"Discovery failed: {exc}", valid=False,
            )

        for plugin_id, old in self._records.items():
            if old.loaded and plugin_id in records:
                records[plugin_id] = replace(records[plugin_id], loaded=True, enabled=True)
        self._records = records
        return tuple(records.values())

    def records(self) -> tuple[PluginRecord, ...]:
        if not self._records:
            self.discover()
        return tuple(self._records.values())

    @property
    def plugin_dirs(self) -> tuple[Path, ...]:
        return self._plugin_dirs

    def import_folder(self, source: str | Path) -> PluginRecord:
        """Copy a validated plugin folder into the configured plugin directory."""
        source_input = Path(source).expanduser()
        if source_input.is_symlink():
            raise ValueError("Plugin folders cannot be symbolic links")
        source_path = source_input.resolve()
        if not source_path.is_dir():
            raise ValueError("Select a plugin folder")
        candidate = self._discover_folder(source_path)
        if candidate is None:
            raise ValueError("The selected folder does not contain plugin.toml")
        if not candidate.valid:
            raise ValueError(candidate.error)
        self.discover()
        existing = self._records.get(candidate.id)
        if existing is not None:
            installed_paths = {path.resolve() for path in self._plugin_dirs}
            if source_path.parent in installed_paths:
                return existing
            raise ValueError(f"A plugin with id '{candidate.id}' is already installed")
        if not self._plugin_dirs:
            raise RuntimeError("No plugin installation directory is configured")

        destination_root = self._plugin_dirs[0].expanduser().resolve()
        destination_root.mkdir(parents=True, exist_ok=True)
        destination = destination_root / candidate.id
        if destination.exists():
            raise FileExistsError(f"Plugin folder already exists: {destination}")
        if any(path.is_symlink() for path in source_path.rglob("*")):
            raise ValueError("Plugin folders cannot contain symbolic links")
        preference_error = self._set_preference(candidate.id, False)
        if preference_error:
            raise OSError(preference_error)
        staging = destination_root / f".{candidate.id}.importing-{uuid.uuid4().hex}"
        try:
            shutil.copytree(source_path, staging)
            staging.rename(destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        self.discover()
        return self._records[candidate.id]

    def import_archive(self, source: str | Path) -> PluginRecord:
        """Safely extract a Canlytics plugin ZIP and install its manifest folder."""
        archive_path = Path(source).expanduser().resolve()
        if not archive_path.is_file() or archive_path.suffix.lower() != ".zip":
            raise ValueError("Select a .zip plugin archive")
        with tempfile.TemporaryDirectory(prefix="canlytics-plugin-import-") as temporary:
            extraction_root = Path(temporary).resolve()
            with zipfile.ZipFile(archive_path) as archive:
                members = archive.infolist()
                if len(members) > _MAX_PLUGIN_ARCHIVE_MEMBERS:
                    raise ValueError("The plugin archive contains too many files")
                total_size = sum(member.file_size for member in members)
                if total_size > _MAX_PLUGIN_ARCHIVE_TOTAL_BYTES:
                    raise ValueError("The plugin archive is too large after extraction")
                for member in members:
                    if member.file_size > _MAX_PLUGIN_ARCHIVE_MEMBER_BYTES:
                        raise ValueError(f"The plugin archive contains an oversized file: {member.filename}")
                    relative_path = PurePosixPath(member.filename)
                    if (
                        not member.filename
                        or not relative_path.parts
                        or relative_path.is_absolute()
                        or ".." in relative_path.parts
                        or "\\" in member.filename
                        or any(":" in part for part in relative_path.parts)
                    ):
                        raise ValueError("The plugin archive contains an unsafe path")
                    mode = member.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        raise ValueError("Plugin archives cannot contain symbolic links")
                    target = extraction_root.joinpath(*relative_path.parts)
                    if not target.resolve().is_relative_to(extraction_root):
                        raise ValueError("The plugin archive contains an unsafe path")
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(member) as input_file, target.open("wb") as output_file:
                            shutil.copyfileobj(input_file, output_file)
            if (extraction_root / "plugin.toml").is_file():
                plugin_folder = extraction_root
            else:
                folders = [path for path in extraction_root.iterdir() if path.is_dir()]
                files = [path for path in extraction_root.iterdir() if path.is_file()]
                if len(folders) != 1 or files or not (folders[0] / "plugin.toml").is_file():
                    raise ValueError("The ZIP must contain plugin.toml at its root or one folder below")
                plugin_folder = folders[0]
            return self.import_folder(plugin_folder)

    def set_enabled(self, plugin_id: str, enabled: bool, context: PluginContext | None = None) -> PluginRecord:
        if not self._records:
            self.discover()
        record = self._records.get(plugin_id)
        if record is None:
            raise KeyError(f"Unknown plugin: {plugin_id}")
        if enabled and not record.valid:
            return record
        if not enabled:
            api = self._apis.pop(plugin_id, None)
            if api is not None:
                api.clear()
            module = self._modules.pop(plugin_id, None)
            shutdown = getattr(module, "shutdown", None) if module is not None else None
            if callable(shutdown):
                try:
                    shutdown()
                except Exception as exc:
                    logger.exception("Plugin %s shutdown failed", plugin_id)
                    record = replace(record, error=f"Shutdown failed: {exc}")
            shutdown_error = record.error if record.error.startswith("Shutdown failed:") else ""
            persistence_error = self._set_preference(plugin_id, False)
            errors = "; ".join(error for error in (shutdown_error, persistence_error) if error)
            return self._store(replace(record, enabled=False, loaded=False, error=errors))

        persistence_error = self._set_preference(plugin_id, True)
        if context is None:
            record = replace(record, enabled=True, loaded=False, error="A host context is required to enable this plugin")
            return self._store(record)
        if record.error.startswith("Duplicate plugin id"):
            return self._store(replace(record, enabled=True, loaded=False))
        try:
            register, module = self._resolve_register(record)
            api = PluginAPI(plugin_id)
            result = register(api, context)
            if result is not None:
                raise TypeError("Plugin register(api, context) must return None")
            self._apis[plugin_id] = api
            if module is not None:
                self._modules[plugin_id] = module
            record = replace(record, enabled=True, loaded=True, error=persistence_error)
        except Exception as exc:
            logger.exception("Plugin %s failed to load", plugin_id)
            error = f"{type(exc).__name__}: {exc}"
            if persistence_error:
                error = f"{error}; {persistence_error}"
            record = replace(record, enabled=True, loaded=False, error=error)
        return self._store(record)

    def extensions(self, kind: str) -> dict[str, Callable]:
        attribute = {"dbc_sources": "dbc_sources", "log_importers": "log_importers", "log_exporters": "log_exporters"}.get(kind)
        if attribute is None:
            raise ValueError(f"Unknown plugin extension kind: {kind}")
        result: dict[str, Callable] = {}
        for api in self._apis.values():
            for name, callback in getattr(api, attribute).items():
                result[f"{api.plugin_id}:{name}"] = callback
        return result

    def ui_extensions(self, kind: str) -> dict[str, tuple[str, Callable]]:
        """Return named UI callbacks paired with their owning plugin id."""
        if kind not in {"windows", "send_to_actions", "context_actions"}:
            raise ValueError(f"Unknown plugin UI extension kind: {kind}")
        result: dict[str, tuple[str, Callable]] = {}
        for plugin_id, api in self._apis.items():
            for name, callback in getattr(api, kind).items():
                result[f"{plugin_id}:{name}"] = (plugin_id, callback)
        return result

    def mcp_extensions(self) -> dict[str, tuple[str, Callable, str]]:
        """Return MCP callbacks with namespaced names and their owner plugin ids."""
        result: dict[str, tuple[str, Callable, str]] = {}
        for plugin_id, api in self._apis.items():
            for name, (callback, description) in api.mcp_tools.items():
                result[f"p{len(plugin_id)}_{plugin_id}_{name}"] = (plugin_id, callback, description)
        return result

    def live_chunk_listeners(self) -> tuple[tuple[str, Callable], ...]:
        return tuple(
            (plugin_id, callback)
            for plugin_id, api in self._apis.items()
            for callback in api.live_chunk_listeners
        )

    def shutdown(self) -> None:
        modules = tuple(self._modules.values())
        self._modules.clear()
        for module in modules:
            shutdown = getattr(module, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception:
                    logger.exception("Plugin shutdown failed")
        for api in self._apis.values():
            api.clear()
        self._apis.clear()
        for path in self._added_import_paths:
            try:
                sys.path.remove(path)
            except ValueError:
                pass
        self._added_import_paths.clear()

    def _discover_folder(self, folder: Path) -> PluginRecord | None:
        manifest_path = folder / "plugin.toml"
        if not manifest_path.is_file():
            return None
        plugin_id = folder.name
        try:
            with manifest_path.open("rb") as handle:
                data = tomllib.load(handle)
            metadata = data.get("plugin", data)
            plugin_id = str(metadata.get("id", "")).strip()
            name = str(metadata.get("name", "")).strip()
            version = str(metadata.get("version", "")).strip()
            api_version = metadata.get("api_version")
            entry_point = str(metadata.get("entry_point", "")).strip()
            if not _PLUGIN_ID.fullmatch(plugin_id):
                raise ValueError("Plugin id must use letters, numbers, '.', '_' or '-' and start with a letter or number")
            if not name or not version:
                raise ValueError("Plugin name and version are required")
            if isinstance(api_version, bool) or not isinstance(api_version, int) or api_version != SDK_API_VERSION:
                raise ValueError(f"Unsupported plugin API version: {api_version!r}; expected {SDK_API_VERSION}")
            if not _ENTRY_POINT.fullmatch(entry_point):
                raise ValueError("Entry point must use module:callable syntax")
            return PluginRecord(
                id=plugin_id, name=name, version=version, source="folder",
                enabled=self._enabled.get(plugin_id, False), loaded=False,
                manifest_path=manifest_path, entry_point=entry_point,
            )
        except Exception as exc:
            logger.warning("Invalid plugin manifest %s: %s", manifest_path, exc)
            return PluginRecord(
                id=plugin_id, name=folder.name, version="", source="folder",
                enabled=False, loaded=False,
                error=f"{type(exc).__name__}: {exc}", manifest_path=manifest_path, valid=False,
            )

    @staticmethod
    def _insert_record(records: dict[str, PluginRecord], record: PluginRecord) -> None:
        if record.id not in records:
            records[record.id] = record
            return
        previous = records[record.id]
        records[record.id] = replace(
            previous,
            enabled=False,
            loaded=False,
            error=f"Duplicate plugin id '{record.id}' from {previous.source} and {record.source}",
            valid=False,
        )

    def _resolve_register(self, record: PluginRecord) -> tuple[Callable, ModuleType | None]:
        if record.source == "package":
            self._add_import_paths(self._plugin_dirs)
            matches = [ep for ep in self._entry_points_provider() if ep.name == record.id]
            if len(matches) != 1:
                raise RuntimeError("Plugin package entry point is missing or duplicated")
            loaded = matches[0].load()
            descriptor = loaded if hasattr(loaded, "api_version") and hasattr(loaded, "register") else getattr(loaded, "PLUGIN", None)
            if descriptor is not None:
                if descriptor.api_version != SDK_API_VERSION or descriptor.id != record.id:
                    raise ValueError("Plugin descriptor id or API version does not match the host")
                register = descriptor.register
            elif getattr(loaded, "API_VERSION", None) == SDK_API_VERSION:
                register = getattr(loaded, "register", loaded)
            else:
                raise ValueError("Plugin package must expose a PluginDescriptor with a supported API version")
            if not callable(register):
                raise TypeError("Plugin entry point must resolve to a register(api, context) callable")
            return register, importlib.import_module(loaded.__module__) if hasattr(loaded, "__module__") else None

        if record.manifest_path is None:
            raise ValueError("Plugin manifest path is missing")
        folder = record.manifest_path.parent
        self._add_import_paths((folder,))
        module_name, callable_name = record.entry_point.split(":", 1)
        digest = hashlib.sha256(f"{record.id}:{folder}".encode("utf-8")).hexdigest()[:16]
        namespace = f"_canlytics_plugin_{digest}"
        package_init = folder / "__init__.py"
        if package_init.is_file():
            package_spec = importlib.util.spec_from_file_location(
                namespace, package_init, submodule_search_locations=[str(folder)]
            )
            if package_spec is None or package_spec.loader is None:
                raise ImportError(f"Cannot load plugin package: {package_init}")
            package = importlib.util.module_from_spec(package_spec)
            sys.modules[namespace] = package
            package_spec.loader.exec_module(package)
        else:
            from types import ModuleType
            package = ModuleType(namespace)
            package.__path__ = [str(folder)]
            package.__package__ = namespace
            sys.modules[namespace] = package
        try:
            module = importlib.import_module(f"{namespace}.{module_name}")
        except Exception:
            for loaded_name in tuple(sys.modules):
                if loaded_name == namespace or loaded_name.startswith(namespace + "."):
                    sys.modules.pop(loaded_name, None)
            raise
        register = getattr(module, callable_name)
        if not callable(register):
            raise TypeError("Plugin entry point is not callable")
        return register, module

    def _installed_entry_points(self) -> list:
        entries = importlib.metadata.entry_points()
        selected = entries.select(group="canlytics.plugins") if hasattr(entries, "select") else entries.get("canlytics.plugins", [])
        result: list = []
        seen: set[tuple[str, str, str, str]] = set()

        def add(entry_point) -> None:
            distribution = getattr(entry_point, "dist", None)
            key = (
                str(entry_point.name),
                str(entry_point.value),
                str(getattr(distribution, "name", "")),
                str(getattr(distribution, "version", "")),
            )
            if key not in seen:
                seen.add(key)
                result.append(entry_point)

        for entry_point in selected:
            add(entry_point)
        for root in self._plugin_dirs:
            if not root.is_dir():
                continue
            try:
                distributions = importlib.metadata.distributions(path=[str(root)])
                for distribution in distributions:
                    for entry_point in distribution.entry_points:
                        if entry_point.group == "canlytics.plugins":
                            add(entry_point)
            except OSError:
                logger.exception("Failed to scan plugin package metadata in %s", root)
        return result

    def _add_import_paths(self, paths: tuple[Path, ...] | list[Path]) -> None:
        for path in paths:
            value = str(path.resolve())
            if value not in sys.path:
                sys.path.insert(0, value)
                self._added_import_paths.add(value)

    def _read_state(self) -> dict[str, bool]:
        try:
            with self._state_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            raw = data.get("enabled", {})
            if isinstance(raw, dict):
                return {str(key): bool(value) for key, value in raw.items()}
        except FileNotFoundError:
            pass
        except Exception:
            logger.exception("Failed to read plugin state %s", self._state_path)
        return {}

    def _write_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        temporary.write_text(json.dumps({"enabled": self._enabled}, indent=2), encoding="utf-8")
        temporary.replace(self._state_path)

    def _set_preference(self, plugin_id: str, enabled: bool) -> str:
        self._enabled[plugin_id] = enabled
        try:
            self._write_state()
        except Exception as exc:
            logger.exception("Failed to save plugin preference for %s", plugin_id)
            return f"Could not save plugin preference: {exc}"
        return ""

    def _store(self, record: PluginRecord) -> PluginRecord:
        self._records[record.id] = record
        return record
