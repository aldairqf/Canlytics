from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SendMode = Literal["single", "periodic"]
FrameSource = Literal["raw", "dbc"]


@dataclass
class DbcFrameSource:
    """De-normalized snapshot of how a payload was built from a DBC message --
    kept even if that DBC isn't loaded this session, so a restored entry stays
    sendable (data_hex is already resolved) even though the editor can't
    reconstruct the signal-value form until the DBC is reloaded."""

    dbc_name: str
    message_name: str
    signal_values: dict[str, float | int | str] = field(default_factory=dict)


@dataclass
class TransmitEntry:
    entry_id: str
    label: str = ""
    can_id: str = "000"
    extended: bool = False
    dlc: int = 8
    data_hex: str = "0000000000000000"
    source: FrameSource = "raw"
    dbc_source: DbcFrameSource | None = None
    mode: SendMode = "single"
    interval_ms: int = 100
    enabled: bool = True


@dataclass(frozen=True)
class TxLogRecord:
    ts: float
    entry_id: str
    label: str
    can_id: str
    data_hex: str
    mode: SendMode
    success: bool
    message: str = ""
