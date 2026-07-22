"""Characterization tests for services/can_send.py."""

from __future__ import annotations

import os
import tempfile
import unittest

import cantools

from models.can_send import TransmitEntry
from services.can_send import (
    ResolvedFrame,
    TransmitEntryError,
    build_cansend_command,
    encode_dbc_payload,
    resolve_transmit_entry,
)

MINIMAL_DBC = """VERSION ""

NS_ :

BS_:

BU_: ECU

BO_ 256 TestMsg: 8 ECU
 SG_ Counter : 0|8@1+ (1,0) [0|100] "" ECU
 SG_ Temp : 8|8@1+ (0.5,-40) [-40|87.5] "C" ECU
"""


class ResolveTransmitEntryTests(unittest.TestCase):
    def test_valid_entry_resolves(self):
        entry = TransmitEntry(entry_id="a", can_id="18FEF100", extended=True, dlc=4, data_hex="01020304")
        frame = resolve_transmit_entry(entry)
        self.assertEqual(frame, ResolvedFrame(entry_id="a", can_id=0x18FEF100, data=b"\x01\x02\x03\x04", extended=True))

    def test_standard_id_not_extended(self):
        entry = TransmitEntry(entry_id="a", can_id="100", extended=False, dlc=0, data_hex="")
        frame = resolve_transmit_entry(entry)
        self.assertEqual(frame.can_id, 0x100)
        self.assertFalse(frame.extended)
        self.assertEqual(frame.data, b"")

    def test_invalid_can_id_raises(self):
        entry = TransmitEntry(entry_id="a", can_id="ZZZ", dlc=0, data_hex="")
        with self.assertRaises(TransmitEntryError):
            resolve_transmit_entry(entry)

    def test_dlc_out_of_range_raises(self):
        entry = TransmitEntry(entry_id="a", can_id="100", dlc=9, data_hex="0102030405060708" + "09")
        with self.assertRaises(TransmitEntryError):
            resolve_transmit_entry(entry)

    def test_odd_length_hex_raises(self):
        entry = TransmitEntry(entry_id="a", can_id="100", dlc=1, data_hex="0")
        with self.assertRaises(TransmitEntryError):
            resolve_transmit_entry(entry)

    def test_malformed_hex_raises(self):
        entry = TransmitEntry(entry_id="a", can_id="100", dlc=1, data_hex="ZZ")
        with self.assertRaises(TransmitEntryError):
            resolve_transmit_entry(entry)

    def test_dlc_mismatch_raises(self):
        entry = TransmitEntry(entry_id="a", can_id="100", dlc=4, data_hex="0102")
        with self.assertRaises(TransmitEntryError):
            resolve_transmit_entry(entry)


class BuildCansendCommandTests(unittest.TestCase):
    def test_standard_id_padded_to_3_digits(self):
        cmd = build_cansend_command("can0", 0x100, b"\x01\x02", extended=False)
        self.assertEqual(cmd, "cansend can0 100#0102")

    def test_extended_id_padded_to_8_digits(self):
        cmd = build_cansend_command("can0", 0x18FEF100, b"\x01\x02", extended=True)
        self.assertEqual(cmd, "cansend can0 18FEF100#0102")

    def test_empty_data(self):
        cmd = build_cansend_command("vcan0", 0x1, b"", extended=False)
        self.assertEqual(cmd, "cansend vcan0 001#")


class EncodeDbcPayloadTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".dbc")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(MINIMAL_DBC)
        self.db = cantools.database.load_file(self.path)
        self.message = self.db.get_message_by_name("TestMsg")

    def tearDown(self):
        os.remove(self.path)

    def test_encodes_known_signals(self):
        hex_text = encode_dbc_payload(self.message, {"Counter": 5, "Temp": 20.0})
        data = bytes.fromhex(hex_text)
        decoded = self.message.decode(data)
        self.assertEqual(decoded["Counter"], 5)
        self.assertEqual(decoded["Temp"], 20.0)

    def test_partial_values_padded(self):
        # Only Counter given -- padding=True should still yield a full 8-byte frame.
        hex_text = encode_dbc_payload(self.message, {"Counter": 3})
        self.assertEqual(len(bytes.fromhex(hex_text)), self.message.length)

    def test_out_of_declared_range_value_not_strict(self):
        # Counter's declared range is [0, 100] but its 8-bit width allows up to 255 --
        # strict=False must accept 200 without raising (fault-injection use case).
        hex_text = encode_dbc_payload(self.message, {"Counter": 200, "Temp": 20.0})
        decoded = self.message.decode(bytes.fromhex(hex_text), decode_choices=False)
        self.assertEqual(decoded["Counter"], 200)


if __name__ == "__main__":
    unittest.main()
