from pathlib import Path
import polars as pl

from services.can_data_parser import load_can_dataframe


class CANLog:
    def __init__(self, path: str | Path, *, source_tz_offset_minutes: int | None = None):
        self.path = Path(path)
        self.source_tz_offset_minutes = source_tz_offset_minutes
        if not self.path.exists():
            raise FileNotFoundError(self.path)

    def load(self, normalize_time: bool = False) -> pl.DataFrame:
        return load_can_dataframe(
            self.path,
            normalize_time=normalize_time,
            source_tz_offset_minutes=self.source_tz_offset_minutes,
        )
