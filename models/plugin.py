from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PluginRecord:
    id: str
    name: str
    version: str
    source: str
    enabled: bool
    loaded: bool
    error: str = ""
    manifest_path: Path | None = None
    entry_point: str = ""
    valid: bool = True
