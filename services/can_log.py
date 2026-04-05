from pathlib import Path
import polars as pl

from services.can_data_parser import load_can_dataframe


class CANLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(self.path)

    def load(self, normalize_time: bool = False) -> pl.DataFrame:
        return load_can_dataframe(self.path, normalize_time=normalize_time)
