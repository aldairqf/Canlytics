from __future__ import annotations

from pathlib import Path


def register(api, context) -> None:
    api.register_log_exporter("CSV snapshot", export_snapshot)


def export_snapshot(dataframe, path: str) -> str:
    target = Path(path)
    dataframe.write_csv(target)
    return str(target)
