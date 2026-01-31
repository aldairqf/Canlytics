from __future__ import annotations

from typing import Protocol

import polars as pl

from models.frame_selector import FrameSelector
from models.signal import Signal


class LogLoaderService(Protocol):
    """Contract for log loader implementations."""

    def load(self, normalize_time: bool = False) -> pl.DataFrame:
        ...


class DataService(Protocol):
    """Contract for log data operations."""

    def merge_frames(
        self,
        base: pl.DataFrame | None,
        incoming: pl.DataFrame,
        *,
        normalize: bool,
    ) -> pl.DataFrame:
        ...


class DbcService(Protocol):
    """Contract for DBC lookup/decoding services."""

    entries_changed: object

    def active_entries(self) -> list:
        ...

    def decode_frame(self, can_id: str, data_hex: str) -> list[dict]:
        ...

    def get_dbc_names(self, active_only: bool = False) -> list[str]:
        ...

    def get_message_names(self, dbc_name: str) -> list[str]:
        ...

    def get_signal_names(self, dbc_name: str, message_name: str) -> list[str]:
        ...

    def get_signal_definition(
        self,
        dbc_name: str,
        message_name: str,
        signal_name: str,
        *,
        scaled: bool = True,
    ) -> dict:
        ...

    def resolve_message_name(self, raw_id: str) -> str | None:
        ...


class DecoderService(Protocol):
    """Contract for decoding raw CAN signals into series."""

    def decode_signal(
        self,
        df: pl.DataFrame,
        signal: Signal,
        selector: FrameSelector,
    ) -> tuple[list[float], list[float]]:
        ...
