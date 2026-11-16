from __future__ import annotations

import unittest

from services.j1939_analysis import (
    ADDRESS_CLAIMED_PGN,
    decode_address_claim,
    decode_dm1,
    decode_j1939_identifier,
    pgn_name,
)


class J1939IdentifierTests(unittest.TestCase):
    def test_main_window_module_imports(self):
        import views.main_window

    def test_decodes_pdu1_priority_source_and_destination(self):
        decoded = decode_j1939_identifier(0x0CEF0A0B)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.priority, 3)
        self.assertEqual(decoded.pgn, 0xEF00)
        self.assertEqual(decoded.source_address, 0x0B)
        self.assertEqual(decoded.destination_address, 0x0A)

    def test_pdu2_has_no_destination_and_keeps_group_extension(self):
        decoded = decode_j1939_identifier(0x18FEE311)
        self.assertEqual(decoded.pgn, 0xFEE3)
        self.assertIsNone(decoded.destination_address)

    def test_extended_data_page_is_preserved(self):
        decoded = decode_j1939_identifier(0x1AFEE311)
        self.assertEqual(decoded.pgn, 0x2FEE3)
        self.assertEqual(decoded.edp, 1)

    def test_standard_or_invalid_identifiers_are_ignored(self):
        for frame_id in (0x7FF, 0x20000000, -1):
            with self.subTest(frame_id=frame_id):
                self.assertIsNone(decode_j1939_identifier(frame_id))

    def test_known_protocol_pgn_names_are_available(self):
        self.assertEqual(pgn_name(ADDRESS_CLAIMED_PGN), "Address Claimed")
        self.assertIsNone(pgn_name(0x12345))


class J1939Dm1Tests(unittest.TestCase):
    def test_decodes_lamps_and_multiple_dtc_fields(self):
        payload = bytes.fromhex("9E 4E 39 30 07 8C 31 D4 03 05")
        result = decode_dm1(payload)
        self.assertIsNotNone(result)
        self.assertEqual(result.protect_lamp, 2)
        self.assertEqual(result.amber_warning_lamp, 3)
        self.assertEqual(result.red_stop_lamp, 1)
        self.assertEqual(result.malfunction_indicator_lamp, 2)
        self.assertEqual(
            [(dtc.spn, dtc.fmi, dtc.conversion_method, dtc.occurrence_count) for dtc in result.dtcs],
            [(12345, 7, 1, 12), (54321, 3, 0, 5)],
        )
        self.assertFalse(result.truncated)

    def test_decodes_standard_dm1_vector_and_three_high_spn_bits(self):
        standard = decode_dm1(bytes.fromhex("00 FF 64 00 01 01 FF FF"))
        high_spn = decode_dm1(bytes.fromhex("00 FF 00 F0 E0 00 FF FF"))
        self.assertEqual((standard.dtcs[0].spn, standard.dtcs[0].fmi,
                          standard.dtcs[0].occurrence_count, standard.dtcs[0].conversion_method),
                         (100, 1, 1, 0))
        self.assertEqual(high_spn.dtcs[0].spn, 520192)

    def test_no_dtc_and_truncated_payload_are_distinguished(self):
        no_dtc = decode_dm1(bytes([0, 0, 255, 255, 255, 255, 255, 255]))
        zero_dtc = decode_dm1(bytes([0, 0, 0, 0, 0, 0, 0, 0]))
        truncated = decode_dm1(bytes([0, 0, 1, 2, 3]))
        self.assertEqual(no_dtc.dtcs, ())
        self.assertEqual(zero_dtc.dtcs, ())
        self.assertFalse(no_dtc.truncated)
        self.assertTrue(truncated.truncated)
        self.assertIsNone(decode_dm1(b"\x00"))


class AnalyzeJ1939DataframeTests(unittest.TestCase):
    def test_snapshot_collects_latest_node_and_dm1_per_source(self):
        import polars as pl

        from services.j1939_analysis import analyze_j1939_dataframe

        name = 0x12345 | (0x234 << 21) | (0x80 << 40)
        dtc = bytes.fromhex("39 30 07 0C")
        dataframe = pl.DataFrame(
            {
                "TS": [1.0, 2.0, 3.0, 4.0],
                "ID": ["18EEFF80", "18FECA80", "18FECA80", "18FEE300"],
                "DATA": [
                    name.to_bytes(8, "little").hex().upper(),
                    bytes([0, 0]).hex(),
                    (bytes([0, 0]) + dtc + b"\xFF\xFF").hex().upper(),
                    "0102030405060708",
                ],
            }
        )
        progress = []
        snapshot = analyze_j1939_dataframe(
            dataframe,
            on_progress=lambda done, total: progress.append((done, total)),
        )
        self.assertEqual([node.source_address for node in snapshot.nodes], [0x00, 0x80])
        self.assertFalse(snapshot.nodes[0].claimed)
        self.assertEqual(snapshot.nodes[1].timestamp, 3.0)
        self.assertTrue(snapshot.nodes[1].claimed)
        self.assertEqual([record.source_address for record in snapshot.diagnostics], [0x80])
        self.assertEqual(snapshot.diagnostics[0].timestamp, 3.0)
        self.assertEqual(snapshot.diagnostics[0].dm1.dtcs[0].spn, 12345)
        self.assertEqual(progress[-1], (8, 8))

    def test_snapshot_decodes_dm1_reassembled_from_bam_and_cmdt(self):
        import polars as pl

        from services.j1939_analysis import analyze_j1939_dataframe

        dtc = bytes.fromhex("39 30 07 04")
        payload = (bytes([0, 0]) + dtc + b"\xFF\xFF\xFF").hex().upper()
        sessions = (
            (
                "BAM",
                ["18ECFF0A", "18EBFF0A", "18EBFF0A"],
                ["20090002FFCAFE00", "01" + payload[:14], "02" + payload[14:] + "FFFFFFFFFF"],
            ),
            (
                "CMDT",
                ["0CEC0B0A", "18EC0A0B", "18EB0B0A", "18EB0B0A"],
                ["1009000202CAFE00", "110201FFFFCAFE00", "01" + payload[:14], "02" + payload[14:] + "FFFFFFFFFF"],
            ),
        )
        for protocol, ids, data in sessions:
            with self.subTest(protocol=protocol):
                dataframe = pl.DataFrame(
                    {
                        "TS": [index / 10 for index in range(len(ids))],
                        "ID": ids,
                        "DATA": data,
                    }
                )
                snapshot = analyze_j1939_dataframe(dataframe)
                self.assertEqual(len(snapshot.diagnostics), 1)
                self.assertEqual(snapshot.diagnostics[0].source_address, 0x0A)
                self.assertEqual(snapshot.diagnostics[0].dm1.dtcs[0].spn, 12345)


class J1939AddressClaimTests(unittest.TestCase):
    def test_decodes_all_name_components_from_address_claim(self):
        fields = {
            "identity": 0x12345,
            "manufacturer": 0x234,
            "ecu": 5,
            "function_instance": 17,
            "function": 0x80,
            "vehicle_system": 0x45,
            "vehicle_instance": 7,
            "industry": 3,
            "arbitrary": 1,
        }
        name = (
            fields["identity"]
            | (fields["manufacturer"] << 21)
            | (fields["ecu"] << 32)
            | (fields["function_instance"] << 35)
            | (fields["function"] << 40)
            | (fields["vehicle_system"] << 49)
            | (fields["vehicle_instance"] << 56)
            | (fields["industry"] << 60)
            | (fields["arbitrary"] << 63)
        )
        node = decode_address_claim(0x80, name.to_bytes(8, "little"), 12.5)
        self.assertEqual(node.source_address, 0x80)
        self.assertEqual(node.timestamp, 12.5)
        self.assertEqual(node.identity_number, fields["identity"])
        self.assertEqual(node.manufacturer_code, fields["manufacturer"])
        self.assertEqual(node.ecu_instance, fields["ecu"])
        self.assertEqual(node.function_instance, fields["function_instance"])
        self.assertEqual(node.function, fields["function"])
        self.assertEqual(node.vehicle_system, fields["vehicle_system"])
        self.assertEqual(node.vehicle_system_instance, fields["vehicle_instance"])
        self.assertEqual(node.industry_group, fields["industry"])
        self.assertTrue(node.arbitrary_address_capable)
        self.assertIsNone(decode_address_claim(0x80, b"short", 0.0))


if __name__ == "__main__":
    unittest.main()
