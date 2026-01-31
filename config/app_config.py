from __future__ import annotations

import json
import os
from pathlib import Path

_config = None


def _load_config():
    path = os.environ.get("CANANALYZE_CONFIG")
    if path:
        config_path = Path(path)
    else:
        config_path = Path(__file__).resolve().parent / "app_config.json"

    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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
