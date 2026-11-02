from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import can
import polars as pl

from services.can_data_parser import frame_dict, rows_to_df
from services.log_export import ExportCancelled, export_dataframe, select_export_frames


def _sample_df() -> pl.DataFrame:
    return rows_to_df([
        frame_dict(ts=1_700_000_000.25, bus="can0", can_id=0x123, data=bytes.fromhex("0102")),
        frame_dict(ts=1_700_000_000.375, bus="can0", can_id=0x18FF1234, data=bytes.fromhex("AABBCC")),
        frame_dict(ts=1_700_000_000.5, bus="can1", can_id=0x321, data=bytes.fromhex("FF")),
    ])


class SelectExportFramesTests(unittest.TestCase):
    def test_all_frames_preserves_input(self):
        source = _sample_df()
        self.assertTrue(select_export_frames(source, "all").equals(source))

    def test_current_filter_applies_selected_ids_and_active_time_range(self):
        selected = select_export_frames(
            _sample_df(), "filtered", selected_ids={"18FF1234", "321"},
            ts_min=1_700_000_000.3, ts_max=1_700_000_000.6,
        )
        self.assertEqual(selected["ID"].to_list(), ["18FF1234", "321"])

    def test_time_range_does_not_apply_current_id_selection(self):
        selected = select_export_frames(
            _sample_df(), "range", selected_ids={"123"},
            ts_min=1_700_000_000.3, ts_max=1_700_000_000.45,
        )
        self.assertEqual(selected["ID"].to_list(), ["18FF1234"])

    def test_range_requires_at_least_one_bound(self):
        with self.assertRaises(ValueError):
            select_export_frames(_sample_df(), "range")


class ExportDataFrameTests(unittest.TestCase):
    def test_all_supported_formats_round_trip_through_python_can(self):
        with tempfile.TemporaryDirectory() as directory:
            for suffix in (".log", ".asc", ".blf", ".trc", ".csv"):
                with self.subTest(suffix=suffix):
                    path = Path(directory) / f"capture{suffix}"
                    source = _sample_df().head(2) if suffix == ".csv" else _sample_df()
                    export_dataframe(source, path)
                    reader = can.ASCReader(path, relative_timestamp=False) if suffix == ".asc" else can.LogReader(path)
                    try:
                        messages = list(reader)
                    finally:
                        reader.stop()
                    self.assertEqual(len(messages), source.height)
                    self.assertEqual([m.arbitration_id for m in messages], [int(value, 16) for value in source["ID"].to_list()])
                    self.assertEqual([m.is_extended_id for m in messages], [int(value, 16) > 0x7FF for value in source["ID"].to_list()])
                    self.assertEqual([bytes(m.data) for m in messages], [bytes.fromhex(value) for value in source["DATA"].to_list()])
                    for actual, expected in zip(messages, source["TS"].to_list()):
                        self.assertAlmostEqual(actual.timestamp, expected, delta=0.001)

    def test_csv_rejects_multibus_capture_instead_of_losing_bus_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.csv"
            with self.assertRaisesRegex(ValueError, "cannot preserve bus identity"):
                export_dataframe(_sample_df(), path)
            self.assertFalse(path.exists())

    def test_cancel_keeps_existing_destination_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.log"
            path.write_bytes(b"existing export")
            with self.assertRaises(ExportCancelled):
                export_dataframe(_sample_df(), path, should_cancel=lambda: True)
            self.assertEqual(path.read_bytes(), b"existing export")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_writer_error_keeps_existing_destination_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.log"
            path.write_bytes(b"existing export")
            invalid = _sample_df().with_columns(pl.lit("not-hex").alias("DATA"))
            with self.assertRaises(ValueError):
                export_dataframe(invalid, path)
            self.assertEqual(path.read_bytes(), b"existing export")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_source_log_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.log"
            path.write_bytes(b"field data")
            with self.assertRaisesRegex(ValueError, "source CAN log"):
                export_dataframe(_sample_df(), path, protected_paths=[path])
            self.assertEqual(path.read_bytes(), b"field data")

    def test_progress_reports_completed_rows_and_total(self):
        updates = []
        with tempfile.TemporaryDirectory() as directory:
            export_dataframe(_sample_df(), Path(directory) / "capture.log", progress_callback=lambda done, total: updates.append((done, total)))
        self.assertEqual(updates[-1], (3, 3))


if __name__ == "__main__":
    unittest.main()
