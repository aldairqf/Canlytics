from __future__ import annotations

import unittest

import polars as pl

from services.j1939_transport import assemble_transport_messages
from services.j1939_transmit import build_transport_frames


class J1939TransmitTests(unittest.TestCase):
    def test_bam_frames_round_trip_through_existing_reassembler(self):
        payload = bytes(range(20))
        frames = build_transport_frames(0xFECA, payload, 0x0A)
        rows = [(float(i), f"{frame.can_id:08X}", frame.data.hex().upper()) for i, frame in enumerate(frames)]
        result = assemble_transport_messages(pl.DataFrame(rows, schema=[("TS", pl.Float64), ("ID", pl.String), ("DATA", pl.String)], orient="row"), 0xFECA)
        self.assertEqual(result[0].data, payload)
        self.assertEqual(result[0].protocol, "BAM")

    def test_rts_frames_are_accepted_by_existing_cts_reassembler(self):
        payload = bytes(range(20))
        frames = build_transport_frames(0xFECA, payload, 0x0A, 0x0B)
        rows = [(0.0, f"{frames[0].can_id:08X}", frames[0].data.hex().upper())]
        for start, count in ((1, 2), (3, 1)):
            rows.append((float(start), "18EC0A0B", bytes((0x11, count, start, 0xFF, 0xFF, 0xCA, 0xFE, 0)).hex().upper()))
            rows.extend((float(i + 3), f"{frames[i].can_id:08X}", frames[i].data.hex().upper()) for i in range(start, min(start + 2, len(frames))))
        result = assemble_transport_messages(pl.DataFrame(rows, schema=[("TS", pl.Float64), ("ID", pl.String), ("DATA", pl.String)], orient="row"), 0xFECA)
        self.assertEqual(result[0].data, payload)
        self.assertEqual(result[0].protocol, "CMDT")


if __name__ == "__main__":
    unittest.main()
