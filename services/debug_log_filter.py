"""Pure filter logic for the live debug log window (Debug Mode/Logging).

Qt-free so the level/tag filtering can be pinned by tests without a QPlainTextEdit.
Parses services/app_logging.py's LOG_FORMAT ("... LEVEL/logger.name: message").
"""

from __future__ import annotations

LEVEL_ORDER = ["DEBUG", "INFO", "WARNING", "ERROR"]

DEFAULT_VISIBLE_LEVELS = frozenset({"INFO", "WARNING", "ERROR"})


def extract_level(line: str) -> str | None:
    for level in LEVEL_ORDER:
        if f" {level}/" in line:
            return level
    return None


def passes_filter(line: str, *, visible_levels: set[str], tag_filter: str) -> bool:
    level = extract_level(line)
    if level is None or level not in visible_levels:
        return False
    tag = tag_filter.strip()
    if tag and tag not in line:
        return False
    return True
