from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.can_data_parser import (
    FORMAT_ASC, FORMAT_BLF, FORMAT_CSV, FORMAT_TRC, FRAME_SCHEMA, detect_log_format,
    frame_dict, load_can_dataframe, rows_to_df,
)
from services.log_export import export_dataframe


def _sample_df():
    return rows_to_df([
        frame_dict(ts=1_700_000_000.25, bus="can0", can_id=0x123, data=bytes.fromhex("0102")),
        frame_dict(ts=1_700_000_000.375, bus="can0", can_id=0x18FF1234, data=bytes.fromhex("AABBCC")),
        frame_dict(ts=1_700_000_000.5, bus="can1", can_id=0x321, data=bytes.fromhex("FF")),
    ])


class StandardLogImportTests(unittest.TestCase):
    def test_round_trips_asc_blf_trc_and_csv(self):
        expected_formats = {
            ".asc": FORMAT_ASC,
            ".blf": FORMAT_BLF,
            ".trc": FORMAT_TRC,
            ".csv": FORMAT_CSV,
        }
        with tempfile.TemporaryDirectory() as directory:
            for suffix, log_format in expected_formats.items():
                with self.subTest(suffix=suffix):
                    source = _sample_df().head(2) if suffix == ".csv" else _sample_df()
                    path = Path(directory) / f"capture{suffix}"
                    export_dataframe(source, path)

                    self.assertEqual(detect_log_format(path), log_format)
                    loaded = load_can_dataframe(path)

                    self.assertEqual(loaded.columns, list(FRAME_SCHEMA))
                    self.assertEqual(loaded.schema, FRAME_SCHEMA)
                    self.assertEqual(loaded["ID"].to_list(), source["ID"].to_list())
                    self.assertEqual(loaded["DATA"].to_list(), source["DATA"].to_list())
                    expected_buses = ["can0", "can0"] if suffix == ".csv" else ["can0", "can0", "can1"]
                    self.assertEqual(loaded["Bus"].to_list(), expected_buses)
                    for actual, expected in zip(loaded["TS"].to_list(), source["TS"].to_list()):
                        self.assertAlmostEqual(actual, expected, delta=0.001)

    def test_normalizes_absolute_timestamps_for_asc(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.asc"
            export_dataframe(_sample_df().head(2), path)

            loaded = load_can_dataframe(path, normalize_time=True)

        self.assertEqual(loaded["TS"].to_list(), [0.0, 0.125])

    def test_binary_extensions_are_detected_without_text_sniffing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.blf"
            path.write_bytes(b"\x00\xFF\x00\xFE")

            self.assertEqual(detect_log_format(path), FORMAT_BLF)

    def test_rejects_can_fd_instead_of_silently_reclassifying_it(self):
        cases = (
            (bytes(range(8)), True),
            (bytes(range(9)), False),
        )
        for payload, is_fd in cases:
            with self.subTest(payload_size=len(payload), is_fd=is_fd):
                reader = _FakeReader(SimpleNamespace(
                    is_error_frame=False, is_remote_frame=False, is_fd=is_fd,
                    data=payload, channel=0, timestamp=1.0, arbitration_id=0x123,
                ))
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "capture.blf"
                    path.touch()
                    with patch("can.BLFReader", return_value=reader):
                        with self.assertRaisesRegex(ValueError, "CAN FD frames"):
                            load_can_dataframe(path)
                self.assertTrue(reader.stopped)

    def test_rejects_error_and_remote_frames_outside_the_table_contract(self):
        for flags in (
            {"is_error_frame": True, "is_remote_frame": False},
            {"is_error_frame": False, "is_remote_frame": True},
        ):
            with self.subTest(flags=flags):
                reader = _FakeReader(SimpleNamespace(
                    **flags, is_fd=False, data=b"", channel=0, timestamp=1.0,
                    arbitration_id=0x123,
                ))
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "capture.blf"
                    path.touch()
                    with patch("can.BLFReader", return_value=reader):
                        with self.assertRaisesRegex(ValueError, "error or remote frames"):
                            load_can_dataframe(path)
                self.assertTrue(reader.stopped)


class _FakeReader:
    def __init__(self, message):
        self._message = message
        self.stopped = False

    def __iter__(self):
        return iter((self._message,))

    def stop(self):
        self.stopped = True


if __name__ == "__main__":
    unittest.main()
