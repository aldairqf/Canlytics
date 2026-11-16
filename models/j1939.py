from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class J1939Identifier:
    priority: int
    pgn: int
    source_address: int
    destination_address: int | None
    edp: int
    data_page: int
    pdu_format: int
    pdu_specific: int


@dataclass(frozen=True)
class J1939Dtc:
    spn: int
    fmi: int
    conversion_method: int
    occurrence_count: int


@dataclass(frozen=True)
class J1939Dm1:
    protect_lamp: int
    amber_warning_lamp: int
    red_stop_lamp: int
    malfunction_indicator_lamp: int
    flash_status: int
    dtcs: tuple[J1939Dtc, ...]
    truncated: bool = False


@dataclass(frozen=True)
class J1939Node:
    source_address: int
    timestamp: float
    identity_number: int | None = None
    manufacturer_code: int | None = None
    ecu_instance: int | None = None
    function_instance: int | None = None
    function: int | None = None
    vehicle_system: int | None = None
    vehicle_system_instance: int | None = None
    industry_group: int | None = None
    arbitrary_address_capable: bool | None = None
    claimed: bool = False


@dataclass(frozen=True)
class J1939DiagnosticSnapshot:
    source_address: int
    timestamp: float
    dm1: J1939Dm1


@dataclass(frozen=True)
class J1939AnalysisSnapshot:
    nodes: tuple[J1939Node, ...]
    diagnostics: tuple[J1939DiagnosticSnapshot, ...]
