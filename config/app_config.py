from __future__ import annotations

import json

from config.defaults import DEFAULT_OPTIONS
from config.env import get_config_path
from config.ui_text import UI_STRINGS

_config = None


def _merge_section(base: dict, override: dict) -> dict:
    merged = dict(base)
    merged.update(override)
    return merged


def _load_config():
    data = {"options": DEFAULT_OPTIONS, "strings": UI_STRINGS}
    config_path = get_config_path()
    if config_path is None:
        return data

    with config_path.open("r", encoding="utf-8") as handle:
        override = json.load(handle)

    return {
        "options": _merge_section(data["options"], override.get("options", {})),
        "strings": _merge_section(data["strings"], override.get("strings", {})),
    }


def get_config():
    global _config
    if _config is None:
        _config = _load_config()
    return _config


def get_option(name, default=None):
    return get_config().get("options", {}).get(name, default)


def get_text(name, default=None):
    if default is None:
        default = name
    return get_config().get("strings", {}).get(name, default)
