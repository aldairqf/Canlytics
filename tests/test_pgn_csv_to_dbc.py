"""Characterization tests for services/pgn_csv_to_dbc.py."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import cantools

from services.pgn_csv_to_dbc import (
    build_database_from_rows,
    convert_pgn_csv_to_dbc,
    read_pgn_csv_rows,
)
from utils.j1939 import J1939

_SAMPLE_CSV_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "csv" / "j1939_generic_map.csv"

_BASE_COLUMNS = [
    "PGN",
    "PGN Priority",
    "PGN Max Size",
    "PGN Byte Offset",
    "Parameter Length (Bytes)",
    "Description",
    "Scale/Resolution",
    "Offset",
    "Unit",
    "Notes",
]


def _row(pgn, priority, byte_offset, length_bytes, description, scale, offset, unit="", notes="", max_size=8):
    return {
        "PGN": str(pgn),
        "PGN Priority": str(priority),
        "PGN Max Size": str(max_size),
        "PGN Byte Offset": str(byte_offset),
        "Parameter Length (Bytes)": str(length_bytes),
        "Description": description,
        "Scale/Resolution": str(scale),
        "Offset": str(offset),
        "Unit": unit,
        "Notes": notes,
    }


class BuildDatabaseFromRowsTests(unittest.TestCase):
    def test_one_message_per_pgn(self):
        rows = [
            _row(61443, 3, 2, 1, "Percent Load", 1, 0, "%"),
            _row(65262, 6, 0, 1, "Engine Coolant Temperature", 1, -40, "Deg C"),
            _row(65262, 6, 1, 1, "Fuel Temperature", 1, -40, "Deg C"),
        ]
        db = build_database_from_rows(rows)
        self.assertEqual(len(db.messages), 2)
        by_name = {m.name: m for m in db.messages}
        self.assertEqual(len(by_name["PGN_61443"].signals), 1)
        self.assertEqual(len(by_name["PGN_65262"].signals), 2)

    def test_frame_id_encodes_pgn_recoverably(self):
        rows = [_row(65262, 6, 0, 1, "Engine Coolant Temperature", 1, -40, "Deg C")]
        db = build_database_from_rows(rows)
        message = db.messages[0]
        self.assertTrue(message.is_extended_frame)
        self.assertEqual(J1939.extract_pgn(message.frame_id), 65262)

    def test_description_sanitized_to_valid_identifier(self):
        rows = [_row(61443, 3, 2, 1, "Engine Oil Pressure (gauge) #1", 1, 0, "kPa")]
        db = build_database_from_rows(rows)
        signal = db.messages[0].signals[0]
        self.assertEqual(signal.name, "Engine_Oil_Pressure_gauge_1")

    def test_duplicate_signal_names_are_disambiguated(self):
        rows = [
            _row(61443, 3, 0, 1, "Status", 1, 0),
            _row(65262, 6, 0, 1, "Status", 1, 0),
        ]
        db = build_database_from_rows(rows)
        names = sorted(s.name for m in db.messages for s in m.signals)
        self.assertEqual(names, ["Status", "Status_2"])

    def test_defaults_to_little_endian_when_no_byte_order_column(self):
        rows = [_row(61443, 3, 0, 2, "Ground Speed", 0.0078125, -250, "km/h")]
        db = build_database_from_rows(rows)
        self.assertEqual(db.messages[0].signals[0].byte_order, "little_endian")

    def test_respects_byte_order_column_when_present(self):
        row = _row(61443, 3, 0, 2, "Ground Speed", 1, 0)
        row["Byte Order"] = "BE"
        db = build_database_from_rows([row])
        self.assertEqual(db.messages[0].signals[0].byte_order, "big_endian")

    def test_scale_and_offset_are_applied(self):
        rows = [_row(65262, 6, 0, 1, "Engine Coolant Temperature", 1, -40, "Deg C")]
        db = build_database_from_rows(rows)
        signal = db.messages[0].signals[0]
        self.assertEqual(signal.scale, 1)
        self.assertEqual(signal.offset, -40)
        self.assertFalse(signal.is_signed)

    def test_start_bit_and_length_from_byte_offset(self):
        rows = [_row(64917, 6, 1, 2, "Torque Converter Oil Outlet Temperature", 0.03125, -273, "Deg C")]
        db = build_database_from_rows(rows)
        signal = db.messages[0].signals[0]
        self.assertEqual(signal.start, 8)
        self.assertEqual(signal.length, 16)

    def test_message_length_from_pgn_max_size(self):
        rows = [_row(61443, 3, 2, 1, "Percent Load", 1, 0, max_size=8)]
        db = build_database_from_rows(rows)
        self.assertEqual(db.messages[0].length, 8)

    def test_ignores_notes_column_no_value_table(self):
        rows = [_row(65265, 6, 0, 1, "Parking Brake", 1, 0, notes="0=Disengaged, 1=Engaged")]
        db = build_database_from_rows(rows)
        self.assertIsNone(db.messages[0].signals[0].choices)


class DecodeRoundTripTests(unittest.TestCase):
    """Build -> dump -> reload with cantools, then decode a synthetic frame."""

    def test_scaled_decode_matches_scale_and_offset(self):
        rows = [
            _row(65262, 6, 0, 1, "Engine Coolant Temperature", 1, -40, "Deg C"),
            _row(65262, 6, 1, 1, "Fuel Temperature", 1, -40, "Deg C"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            dbc_path = Path(tmp) / "out.dbc"
            db = build_database_from_rows(rows)
            cantools.database.dump_file(db, str(dbc_path))
            reloaded = cantools.database.load_file(str(dbc_path))
            message = reloaded.messages[0]
            decoded = message.decode(bytes([100, 90, 0, 0, 0, 0, 0, 0]))
        self.assertEqual(decoded["Engine_Coolant_Temperature"], 60)
        self.assertEqual(decoded["Fuel_Temperature"], 50)

    def test_matches_regardless_of_priority_and_source_address(self):
        rows = [_row(61443, 3, 2, 1, "Percent Load", 1, 0, "%")]
        db = build_database_from_rows(rows)
        original_id = db.messages[0].frame_id
        different_priority_and_source = J1939.pgn_to_frame_id(61443, priority=1, source_address=0xEE)
        self.assertNotEqual(original_id, different_priority_and_source)
        self.assertEqual(J1939.extract_pgn(original_id), J1939.extract_pgn(different_priority_and_source))


class ReadPgnCsvRowsTests(unittest.TestCase):
    def test_reads_header_and_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "map.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=_BASE_COLUMNS)
                writer.writeheader()
                writer.writerow(_row(61443, 3, 2, 1, "Percent Load", 1, 0, "%"))
            rows = read_pgn_csv_rows(csv_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Description"], "Percent Load")


class ConvertPgnCsvToDbcTests(unittest.TestCase):
    def test_writes_loadable_dbc_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "map.csv"
            dbc_path = Path(tmp) / "map.dbc"
            with open(csv_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=_BASE_COLUMNS)
                writer.writeheader()
                writer.writerow(_row(61443, 3, 2, 1, "Percent Load", 1, 0, "%"))
            convert_pgn_csv_to_dbc(csv_path, dbc_path)
            reloaded = cantools.database.load_file(str(dbc_path))
        self.assertEqual(len(reloaded.messages), 1)
        self.assertEqual(reloaded.messages[0].signals[0].name, "Percent_Load")


@unittest.skipUnless(_SAMPLE_CSV_FIXTURE.is_file(), "j1939_generic_map.csv fixture missing")
class SampleJ1939MapFixtureTests(unittest.TestCase):
    """Pins conversion of a larger, multi-PGN CSV (standard J1939 PGN/SPN naming,
    no proprietary data) against known scale/offset math -- a regression net for
    the synthetic per-behavior tests above, which each only exercise one row."""

    @classmethod
    def setUpClass(cls):
        cls.rows = read_pgn_csv_rows(_SAMPLE_CSV_FIXTURE)
        cls.db = build_database_from_rows(cls.rows)

    def test_every_row_becomes_a_signal(self):
        total_signals = sum(len(m.signals) for m in self.db.messages)
        self.assertEqual(total_signals, len(self.rows))

    def test_every_message_is_pgn_recoverable(self):
        for message in self.db.messages:
            expected_pgn = int(message.name.removeprefix("PGN_"))
            self.assertEqual(J1939.extract_pgn(message.frame_id), expected_pgn)

    def test_engine_coolant_temperature_decodes_with_offset(self):
        message = next(m for m in self.db.messages if m.name == "PGN_65262")
        decoded = message.decode(bytes([100, 0, 0, 0, 0, 0, 0, 0]))
        self.assertEqual(decoded["Engine_Coolant_Temperature"], 60)

    def test_actual_engine_rpm_decodes_with_scale(self):
        message = next(m for m in self.db.messages if m.name == "PGN_61444")
        decoded = message.decode(bytes([0, 0, 0, 0x40, 0x1F, 0, 0, 0]))
        self.assertEqual(decoded["Actual_Engine_RPM"], 1000.0)


if __name__ == "__main__":
    unittest.main()
