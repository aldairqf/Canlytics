from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import polars as pl

from models.j1939 import (
    J1939AnalysisSnapshot,
    J1939DiagnosticSnapshot,
    J1939Dm1,
    J1939Dtc,
    J1939Identifier,
    J1939Node,
)
from services.j1939_transport import J1939TransportMessage, assemble_transport_messages
from utils.can_bytes import parse_hex_bytes
from utils.can_id import can_id_to_int
from utils.j1939 import J1939

DM1_PGN = 0xFECA
ADDRESS_CLAIMED_PGN = 0xEE00

_KNOWN_PGN_NAMES = {
    0xEA00: "Request",
    0xEB00: "Transport Protocol - Data Transfer",
    0xEC00: "Transport Protocol - Connection Management",
    0xEE00: "Address Claimed",
    0xFECA: "Active Diagnostic Trouble Codes (DM1)",
}


def decode_j1939_identifier(frame_id: int) -> J1939Identifier | None:
    """Decode the priority, 18-bit PGN and addresses from an extended CAN ID."""
    return J1939.decode_identifier(frame_id)


def pgn_name(pgn: int) -> str | None:
    """Return a built-in protocol label when one is defined by this app."""
    return _KNOWN_PGN_NAMES.get(int(pgn))


def decode_dm1(payload: bytes | bytearray | memoryview) -> J1939Dm1 | None:
    """Decode the DM1 lamp bytes and complete 4-byte diagnostic trouble codes."""
    data = bytes(payload)
    if len(data) < 2:
        return None
    lamp_status, flash_status = data[0], data[1]
    dtcs = []
    body = data[2:]
    for offset in range(0, len(body) - 3, 4):
        raw = int.from_bytes(body[offset:offset + 4], byteorder="little")
        if raw in (0, 0xFFFFFFFF):
            continue
        dtcs.append(
            J1939Dtc(
                spn=(raw & 0xFFFF) | (((raw >> 21) & 0x7) << 16),
                fmi=(raw >> 16) & 0x1F,
                conversion_method=(raw >> 31) & 1,
                occurrence_count=(raw >> 24) & 0x7F,
            )
        )
    return J1939Dm1(
        protect_lamp=lamp_status & 0x3,
        amber_warning_lamp=(lamp_status >> 2) & 0x3,
        red_stop_lamp=(lamp_status >> 4) & 0x3,
        malfunction_indicator_lamp=(lamp_status >> 6) & 0x3,
        flash_status=flash_status,
        dtcs=tuple(dtcs),
        truncated=(len(body) % 4 != 0 and any(value != 0xFF for value in body[len(body) // 4 * 4:])),
    )


def analyze_j1939_dataframe(
    dataframe: pl.DataFrame,
    *,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> J1939AnalysisSnapshot:
    """Build a read-only node and latest DM1 snapshot from an offline/log frame table."""
    required = {"TS", "ID", "DATA"}
    if dataframe is None or dataframe.is_empty() or not required.issubset(dataframe.columns):
        return J1939AnalysisSnapshot((), ())
    total = dataframe.height * 2
    progress_step = max(1, dataframe.height // 200)
    nodes: dict[int, J1939Node] = {}
    latest_dm1: dict[int, J1939DiagnosticSnapshot] = {}
    for row_index, (timestamp, raw_id, data_hex) in enumerate(dataframe.select(["TS", "ID", "DATA"]).iter_rows(), start=1):
        _check_cancel(should_cancel)
        if timestamp is not None and raw_id is not None:
            try:
                identifier = decode_j1939_identifier(can_id_to_int(raw_id))
            except (TypeError, ValueError):
                identifier = None
            if identifier is not None:
                node = nodes.get(identifier.source_address)
                if node is None:
                    nodes[identifier.source_address] = J1939Node(
                        source_address=identifier.source_address,
                        timestamp=float(timestamp),
                    )
                else:
                    nodes[identifier.source_address] = replace(node, timestamp=float(timestamp))
                payload = parse_hex_bytes(data_hex)
                if identifier.pgn == ADDRESS_CLAIMED_PGN:
                    claimed_node = decode_address_claim(identifier.source_address, payload, float(timestamp))
                    if claimed_node is not None:
                        nodes[identifier.source_address] = claimed_node
                elif identifier.pgn == DM1_PGN:
                    dm1 = decode_dm1(payload)
                    if dm1 is not None:
                        latest_dm1[identifier.source_address] = J1939DiagnosticSnapshot(
                            identifier.source_address,
                            float(timestamp),
                            dm1,
                        )
        if on_progress is not None and (row_index % progress_step == 0 or row_index == dataframe.height):
            on_progress(row_index, total)
    _check_cancel(should_cancel)

    def consume_transport_message(message: J1939TransportMessage) -> None:
        dm1 = decode_dm1(message.data)
        if dm1 is None:
            return
        previous = latest_dm1.get(message.source_address)
        if previous is None or message.timestamp >= previous.timestamp:
            latest_dm1[message.source_address] = J1939DiagnosticSnapshot(
                message.source_address,
                message.timestamp,
                dm1,
            )

    assemble_transport_messages(
        dataframe,
        DM1_PGN,
        should_cancel=should_cancel,
        on_message=consume_transport_message,
        on_progress=lambda done, _total: on_progress(dataframe.height + done, total)
        if on_progress is not None
        else None,
    )
    _check_cancel(should_cancel)
    return J1939AnalysisSnapshot(
        nodes=tuple(sorted(nodes.values(), key=lambda node: node.source_address)),
        diagnostics=tuple(sorted(latest_dm1.values(), key=lambda item: item.source_address)),
    )


def _check_cancel(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel is not None and should_cancel():
        raise InterruptedError("J1939 analysis canceled")


def decode_address_claim(
    source_address: int,
    payload: bytes | bytearray | memoryview,
    timestamp: float,
) -> J1939Node | None:
    """Decode the 64-bit NAME carried by an Address Claimed PGN."""
    data = bytes(payload)
    if len(data) < 8 or not 0 <= int(source_address) <= 0xFF:
        return None
    name = int.from_bytes(data[:8], byteorder="little")
    return J1939Node(
        source_address=int(source_address),
        timestamp=float(timestamp),
        identity_number=name & 0x1FFFFF,
        manufacturer_code=(name >> 21) & 0x7FF,
        ecu_instance=(name >> 32) & 0x7,
        function_instance=(name >> 35) & 0x1F,
        function=(name >> 40) & 0xFF,
        vehicle_system=(name >> 49) & 0x7F,
        vehicle_system_instance=(name >> 56) & 0xF,
        industry_group=(name >> 60) & 0x7,
        arbitrary_address_capable=bool((name >> 63) & 1),
        claimed=True,
    )
