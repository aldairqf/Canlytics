"""Characterization tests for services/can_data_parser.py."""

from __future__ import annotations

import os
import tempfile
import unittest

from services.can_data_parser import (
    FRAME_SCHEMA,
    frame_dict,
    load_can_dataframe,
    normalize_can_id,
    parse_candump_line,
    parse_kvaser_memorator_line,
    rows_to_df,
)


class NormalizeCanIdTests(unittest.TestCase):
    def test_int_to_upper_hex(self):
        self.assertEqual(normalize_can_id(256), "100")

    def test_string_is_trimmed_uppercased_and_x_suffix_removed(self):
        self.assertEqual(normalize_can_id("  18fef100  "), "18FEF100")
        self.assertEqual(normalize_can_id("1abx"), "1AB")


class FrameDictTests(unittest.TestCase):
    def test_basic_mapping(self):
        row = frame_dict(ts=1.0, bus="bus0", can_id="1", data=b"\x01\x02")
        self.assertEqual(row["TS"], 1.0)
        self.assertEqual(row["Bus"], "bus0")
        self.assertEqual(row["ID"], "1")
        self.assertEqual(row["DATA"], "0102")
        self.assertEqual(row["LEN"], 2)
        self.assertEqual(row["B0"], "01")
        self.assertEqual(row["B1"], "02")
        self.assertEqual(row["B2"], "00")
        self.assertEqual(row["D0"], 1)
        self.assertEqual(row["D1"], 2)
        self.assertEqual(row["D2"], 0)

    def test_payload_truncated_to_eight_bytes(self):
        row = frame_dict(ts=0.0, bus="b", can_id="1", data=bytes(range(1, 11)))
        self.assertEqual(row["LEN"], 8)
        self.assertEqual(row["DATA"], "0102030405060708")


class ParseCandumpLineTests(unittest.TestCase):
    def test_compact(self):
        row = parse_candump_line("(1234.567890) can0 18FEF100#0102030405060708")
        self.assertAlmostEqual(row["TS"], 1234.56789)
        self.assertEqual(row["Bus"], "can0")
        self.assertEqual(row["ID"], "18FEF100")
        self.assertEqual(row["DATA"], "0102030405060708")
        self.assertEqual(row["LEN"], 8)
        self.assertEqual(row["D7"], 8)

    def test_spaced_honors_declared_length(self):
        row = parse_candump_line("(1.0) can1 123 [3] 11 22 33")
        self.assertEqual(row["ID"], "123")
        self.assertEqual(row["DATA"], "112233")
        self.assertEqual(row["LEN"], 3)
        self.assertEqual(row["B0"], "11")
        self.assertEqual(row["B3"], "00")
        self.assertEqual(row["D0"], 0x11)
        self.assertEqual(row["D3"], 0)

    def test_non_matching_returns_none(self):
        self.assertIsNone(parse_candump_line("not a candump line"))
        self.assertIsNone(parse_candump_line(""))


class ParseKvaserLineTests(unittest.TestCase):
    def test_basic(self):
        row = parse_kvaser_memorator_line(
            "   0.001000  1  18FEF100x  R  8  01 02 03 04 05 06 07 08"
        )
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["TS"], 0.001)
        self.assertEqual(row["ID"], "18FEF100")
        self.assertEqual(row["DATA"], "0102030405060708")
        self.assertEqual(row["LEN"], 8)

    def test_trigger_lines_ignored(self):
        self.assertIsNone(parse_kvaser_memorator_line("Trigger something"))


class RowsToDfTests(unittest.TestCase):
    def test_schema_and_height(self):
        rows = [
            frame_dict(ts=0.0, bus="b", can_id="100", data=b"\x01"),
            frame_dict(ts=1.0, bus="b", can_id="200", data=b"\x02\x03"),
        ]
        df = rows_to_df(rows)
        self.assertEqual(df.columns, list(FRAME_SCHEMA.keys()))
        self.assertEqual(df.height, 2)
        self.assertEqual(df["ID"].to_list(), ["100", "200"])


class LoadCanDataframeTests(unittest.TestCase):
    def test_loads_compact_candump_file(self):
        content = "(0.000000) can0 100#0102\n(0.001000) can0 200#AABBCC\n"
        fd, path = tempfile.mkstemp(suffix=".log")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
            df = load_can_dataframe(path)
        finally:
            os.remove(path)

        self.assertEqual(df.height, 2)
        self.assertEqual(df["ID"].to_list(), ["100", "200"])
        self.assertEqual(df["LEN"].to_list(), [2, 3])
        self.assertEqual(df["D0"].to_list(), [1, 0xAA])

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_can_dataframe("does-not-exist-12345.log")


if __name__ == "__main__":
    unittest.main()
