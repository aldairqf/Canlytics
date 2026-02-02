from __future__ import annotations

import os
from pathlib import Path

CONFIG_PATH_ENV = "CANANALYZE_CONFIG"


def get_config_path() -> Path | None:
    path = os.environ.get(CONFIG_PATH_ENV)
    if not path:
        return None
    return Path(path)
