from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import TextIO

import polars as pl


ACTIVE_RECORDING_MARKER = "active_recording.json"


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return cleaned[:48] or "capture"


def make_recording_path(directory: str | Path, source: str, *, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S_%f")
    return Path(directory).expanduser() / f"canlytics_{stamp}_{_safe_component(source)}.log"


def find_interrupted_recording(directory: str | Path) -> tuple[Path, Path] | None:
    folder = Path(directory).expanduser().resolve()
    marker = folder / ACTIVE_RECORDING_MARKER
    if not marker.is_file():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        recording = Path(str(payload["path"])).resolve()
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if recording.parent != folder or recording.suffix.lower() != ".log" or not recording.is_file():
        return None
    return recording, marker


class ContinuousCandumpRecorder:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.marker_path = self.path.parent / ACTIVE_RECORDING_MARKER
        self._writer: TextIO | None = None

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._writer = self.path.open("w", encoding="utf-8", buffering=1)
        try:
            temporary = self.marker_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"path": str(self.path)}), encoding="utf-8")
            temporary.replace(self.marker_path)
        except Exception:
            self._writer.close()
            self._writer = None
            raise

    def write_chunk(self, dataframe: pl.DataFrame) -> int:
        if self._writer is None:
            raise RuntimeError("Recorder is not open")
        for timestamp, bus, can_id, data in dataframe.select(["TS", "Bus", "ID", "DATA"]).iter_rows():
            identifier = int(str(can_id), 16)
            frame_id = f"{identifier:08X}" if identifier > 0x7FF else f"{identifier:03X}"
            payload = bytes.fromhex(str(data or "")).hex().upper()
            self._writer.write(f"({float(timestamp or 0.0):.6f}) {str(bus or 'can0')} {frame_id}#{payload}\n")
        self._writer.flush()
        return self.path.stat().st_size

    def close(self, *, completed: bool) -> None:
        writer, self._writer = self._writer, None
        if writer is not None:
            writer.close()
        if completed:
            self.marker_path.unlink(missing_ok=True)


def dismiss_interrupted_recording(marker_path: str | Path) -> None:
    Path(marker_path).unlink(missing_ok=True)
