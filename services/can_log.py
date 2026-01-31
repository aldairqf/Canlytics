from pathlib import Path
import polars as pl

class CANLog:
    """Load CAN logs from candump-style text files."""
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(self.path)

    def load(self, normalize_time: bool = False) -> pl.DataFrame:
        df = pl.read_csv(
            self.path,
            has_header=False,
            new_columns=["raw"],
        )

        pattern = r"\(([\d\.]+)\)\s+(\w+)\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]{0,16})"

        df = df.with_columns(
            pl.col("raw").str.extract(pattern, 1).alias("TS"),
            pl.col("raw").str.extract(pattern, 2).alias("Bus"),
            pl.col("raw").str.extract(pattern, 3).alias("ID"),
            pl.col("raw").str.extract(pattern, 4).alias("DATA"),
        ).drop_nulls(["TS", "Bus", "ID"])

        df = df.with_columns(
            pl.col("TS").cast(pl.Float64),
            pl.col("ID").str.to_uppercase(),
            pl.col("DATA").fill_null("").str.to_uppercase().alias("DATA"),
            pl.col("DATA")
            .map_elements(lambda x: len(x)//2 if x else 0)
            .alias("LEN")
        )

        df = df.with_columns(
            pl.col("DATA").str.pad_end(16, "0"),
        )

        for i in range(8):
            df = df.with_columns(
                pl.col("DATA").str.slice(i * 2, 2).alias(f"B{i}")
            )

        for i in range(8):
            df = df.with_columns(
                pl.col(f"B{i}").str.to_integer(base=16).alias(f"D{i}")
            )

        if normalize_time and df.height > 0:
            t0 = df.select(pl.first("TS")).item()
            df = df.with_columns(
                (pl.col("TS") - t0).round(6).alias("TS")
            )

        return df.drop("raw")
