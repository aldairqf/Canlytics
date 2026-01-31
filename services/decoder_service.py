from __future__ import annotations

import polars as pl

from models.frame_selector import FrameSelector
from models.signal import Signal
from services.can_decoder import decode_signal


class SignalDecoderService:

    def decode_signal(
        self,
        df: pl.DataFrame,
        signal: Signal,
        selector: FrameSelector,
    ) -> tuple[list[float], list[float]]:
        return decode_signal(df, signal, selector)
