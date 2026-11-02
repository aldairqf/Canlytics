from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import can
import polars as pl

from services.can_data_parser import frame_dict, rows_to_df, load_can_dataframe
from services.continuous_recorder import (
    ACTIVE_RECORDING_MARKER,
    ContinuousCandumpRecorder,
    find_interrupted_recording,
    make_recording_path,
)


class ContinuousCandumpRecorderTests(unittest.TestCase):
    def test_recording_flushes_each_chunk_and_closes_marker_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = make_recording_path(directory, "ssh host/can0", now=datetime(2026, 11, 1))
            recorder = ContinuousCandumpRecorder(path)
            recorder.start()
            first = rows_to_df([frame_dict(ts=2.0, bus="can0", can_id=0x123, data=b"\x01")])
            second = rows_to_df([frame_dict(ts=1.0, bus="can1", can_id=0x124, data=b"\x02")])
            self.assertGreater(recorder.write_chunk(first), 0)
            self.assertIsNotNone(find_interrupted_recording(directory))
            recorder.write_chunk(second)
            recorder.close(completed=True)
            self.assertFalse((Path(directory) / ACTIVE_RECORDING_MARKER).exists())
            loaded = load_can_dataframe(path)
            self.assertEqual(loaded.select(["Bus", "ID", "DATA"]).rows(), [
                ("can0", "123", "01"), ("can1", "124", "02")
            ])
            self.assertEqual(loaded["TS"].to_list(), [2.0, 1.0])
            reader = can.LogReader(path)
            try:
                messages = list(reader)
            finally:
                reader.stop()
            self.assertEqual([message.timestamp for message in messages], [2.0, 1.0])
            self.assertEqual([message.channel for message in messages], ["can0", "can1"])

    def test_failed_write_keeps_interrupted_recording_recoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.log"
            recorder = ContinuousCandumpRecorder(path)
            recorder.start()
            invalid = pl.DataFrame({"TS": [1.0], "Bus": ["can0"], "ID": ["123"], "DATA": ["not-hex"]})
            with self.assertRaises(ValueError):
                recorder.write_chunk(invalid)
            recorder.close(completed=False)
            found = find_interrupted_recording(directory)
            self.assertEqual(found, (path.resolve(), (Path(directory) / ACTIVE_RECORDING_MARKER).resolve()))

    def test_marker_cannot_reference_a_log_outside_recording_folder(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            path = Path(outside) / "field.log"
            path.write_text("data", encoding="utf-8")
            marker = Path(directory) / ACTIVE_RECORDING_MARKER
            marker.write_text(json.dumps({"path": str(path)}), encoding="utf-8")
            self.assertIsNone(find_interrupted_recording(directory))

    def test_filename_sanitizes_source_and_includes_timestamp(self):
        path = make_recording_path("~/recordings", "ssh host/iface", now=datetime(2026, 11, 1, 2, 3, 4))
        self.assertIn("20261101_020304_000000", path.name)
        self.assertIn("ssh_host_iface", path.name)
        self.assertEqual(path.suffix, ".log")


if __name__ == "__main__":
    unittest.main()
