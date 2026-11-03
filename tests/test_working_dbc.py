from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cantools

from services.working_dbc import DbcValidationError, WorkingDbc


class WorkingDbcTests(unittest.TestCase):
    def setUp(self) -> None:
        self.working = WorkingDbc()
        self.message = self.working.create_message("VehicleStatus", 0x123, length=8)

    def test_crud_messages_and_signals(self) -> None:
        signal = self.working.create_signal(
            self.message.frame_id, "Speed", start=8, length=16, scale=0.25, offset=-10, unit="km/h",
        )
        self.assertEqual(signal.name, "Speed")
        updated = self.working.update_signal(self.message.frame_id, "Speed", new_name="VehicleSpeed", start=16)
        self.assertEqual(updated.name, "VehicleSpeed")
        self.assertEqual(self.working.get_message(self.message.frame_id).get_signal_by_name("VehicleSpeed").start, 16)
        self.working.delete_signal(self.message.frame_id, "VehicleSpeed")
        self.assertEqual(self.working.get_message(self.message.frame_id).signals, [])
        self.working.update_message(self.message.frame_id, name="Status", length=4)
        self.assertEqual(self.working.get_message(self.message.frame_id).name, "Status")
        self.working.delete_message(self.message.frame_id)
        self.assertEqual(self.working.database.messages, [])

    def test_validates_names_ids_lengths_and_signal_ranges(self) -> None:
        for kwargs in (
            {"name": "bad name", "frame_id": 0x124},
            {"name": "Duplicate", "frame_id": 0x123},
            {"name": "TooLong", "frame_id": 0x124, "length": 9},
            {"name": "OutOfRange", "frame_id": 0x20000000},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(DbcValidationError):
                self.working.create_message(**kwargs)
        for kwargs in (
            {"name": "bad signal", "start": 0, "length": 1},
            {"name": "OutOfRange", "start": 63, "length": 2},
            {"name": "WrongOrder", "start": 0, "length": 1, "byte_order": "middle"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(DbcValidationError):
                self.working.create_signal(self.message.frame_id, **kwargs)

    def test_rejects_overlaps_using_little_and_big_endian_bit_geometry(self) -> None:
        self.working.create_signal(self.message.frame_id, "Little", start=0, length=8)
        with self.assertRaises(DbcValidationError):
            self.working.create_signal(self.message.frame_id, "Overlap", start=7, length=2)

        self.working.create_signal(self.message.frame_id, "Motorola", start=15, length=8, byte_order="big_endian")
        with self.assertRaises(DbcValidationError):
            self.working.create_signal(self.message.frame_id, "OverlapBe", start=8, length=1, byte_order="big_endian")

    def test_allows_disjoint_mux_cases_and_selector_overlap(self) -> None:
        self.working.create_signal(
            self.message.frame_id, "Mux", start=0, length=2, is_multiplexer=True,
        )
        self.working.create_signal(
            self.message.frame_id, "CaseA", start=8, length=8,
            multiplexer_signal="Mux", multiplexer_ids=[0],
        )
        self.working.create_signal(
            self.message.frame_id, "CaseB", start=8, length=8,
            multiplexer_signal="Mux", multiplexer_ids=[1],
        )
        self.working.update_signal(self.message.frame_id, "Mux", new_name="Selector")
        renamed = self.working.get_message(self.message.frame_id)
        self.assertEqual(renamed.get_signal_by_name("CaseA").multiplexer_signal, "Selector")
        with self.assertRaises(DbcValidationError):
            self.working.create_signal(
                self.message.frame_id, "CaseA2", start=8, length=8,
                multiplexer_signal="Selector", multiplexer_ids=[0],
            )
        with self.assertRaises(DbcValidationError):
            self.working.delete_signal(self.message.frame_id, "Selector")
        with self.assertRaises(DbcValidationError):
            self.working.create_signal(
                self.message.frame_id, "InvalidMux", start=16, length=8,
                multiplexer_signal="Selector", multiplexer_ids=[4],
            )

    def test_failed_signal_update_leaves_original_database_unchanged(self) -> None:
        self.working.create_signal(self.message.frame_id, "A", start=0, length=8)
        self.working.create_signal(self.message.frame_id, "B", start=8, length=8)
        with self.assertRaises(DbcValidationError):
            self.working.update_signal(self.message.frame_id, "B", start=4)
        message = self.working.get_message(self.message.frame_id)
        self.assertEqual(message.get_signal_by_name("B").start, 8)

    def test_message_shrink_rejects_existing_signal_outside_new_length(self) -> None:
        self.working.create_signal(self.message.frame_id, "Tail", start=56, length=8)
        with self.assertRaises(DbcValidationError):
            self.working.update_message(self.message.frame_id, length=4)

    def test_low_identifier_update_preserves_extended_frame_format(self) -> None:
        message = self.working.create_message("ExtendedStatus", 0x100, is_extended_frame=True)
        updated = self.working.update_message(message.frame_id, new_frame_id=0x101)
        self.assertTrue(updated.is_extended_frame)
        explicitly_standard = self.working.update_message(
            updated.frame_id, is_extended_frame=False,
        )
        self.assertFalse(explicitly_standard.is_extended_frame)

    def test_rejects_invalid_float_sizes(self) -> None:
        for length in (8, 24, 48):
            with self.subTest(length=length), self.assertRaises(DbcValidationError):
                self.working.create_signal(
                    self.message.frame_id, f"Float{length}", start=0, length=length, is_float=True,
                )
        self.working.create_signal(
            self.message.frame_id, "Float32", start=0, length=32, is_float=True,
        )
        encoded = self.working.database.encode_message("VehicleStatus", {"Float32": 22.5})
        decoded = self.working.database.decode_message(self.message.frame_id, encoded)
        self.assertAlmostEqual(decoded["Float32"], 22.5)

    def test_export_refuses_to_overwrite_source_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.dbc"
            source.write_text("source data", encoding="utf-8")
            original_database = cantools.database.Database()
            guarded = WorkingDbc(original_database, source_path=source)
            with self.assertRaises(DbcValidationError):
                guarded.export(source)
            self.assertEqual(source.read_text(encoding="utf-8"), "source data")

    def test_export_round_trip_preserves_decode(self) -> None:
        self.working.create_signal(
            self.message.frame_id, "Speed", start=0, length=16, scale=0.5, offset=-20,
            unit="km/h", is_signed=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "working.dbc"
            self.working.export(output)
            loaded = cantools.database.load_file(str(output))
        encoded = loaded.encode_message("VehicleStatus", {"Speed": 42.0})
        decoded = loaded.decode_message(self.message.frame_id, encoded)
        self.assertAlmostEqual(decoded["Speed"], 42.0)
        self.assertEqual(loaded.get_message_by_name("VehicleStatus").signals[0].unit, "km/h")


if __name__ == "__main__":
    unittest.main()
