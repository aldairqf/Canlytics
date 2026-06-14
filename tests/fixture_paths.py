"""Discovery helpers for the optional real DBC/log fixtures.

Fixtures live under ``tests/fixtures/{dbc,logs}/`` and are committed to the repo.
They are optional: when a folder is empty the corresponding tests skip instead of
failing, so the suite still runs in any environment. See tests/fixtures/README.md.
"""

from __future__ import annotations

from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
DBC_DIR = FIXTURES_DIR / "dbc"
LOGS_DIR = FIXTURES_DIR / "logs"

_IGNORED_NAMES = {".gitkeep", "README.md"}


def _list_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        p
        for p in directory.iterdir()
        if p.is_file() and p.name not in _IGNORED_NAMES and not p.name.startswith(".")
    )


def dbc_files() -> list[Path]:
    return [p for p in _list_files(DBC_DIR) if p.suffix.lower() == ".dbc"]


def log_files() -> list[Path]:
    return _list_files(LOGS_DIR)


def dbc_file(name: str) -> Path | None:
    """Return a specific DBC fixture by file name (e.g. 'j1939_clean.dbc'), or None."""
    path = DBC_DIR / name
    return path if path.is_file() else None
