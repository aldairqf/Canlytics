from __future__ import annotations

import unittest

import numpy as np
import polars as pl

from services.mux_detector import (
    MuxDetectorConfig,
    _confidence_from_evidence,
    _extend_adjacent_candidates,
    detect_muxes,
)


def synthetic_mux(seed=19, ids=3, frames=2400):
    rng = np.random.default_rng(seed)
    rows = []
    for ident in range(ids):
        for i in range(frames // ids):
            value = i % 40
            row = {"TS": i * 0.02, "ID": f"{ident:03X}", "LEN": 8}
            payload = rng.integers(0, 256, size=8, dtype=np.uint8)
            payload[0:2] = [(value >> 8) & 255, value & 255]
            payload[2] = (value * 5 + 17) & 255
            payload[3] = (value * 11 + 31) & 255
            payload[4] = (value * 17 + 53) & 255
            for j, byte in enumerate(payload):
                row[f"D{j}"] = int(byte)
            rows.append(row)
    return pl.DataFrame(rows)


def _frames_for_payload(payloads, can_id="400", timestamps=None, lengths=None):
    rows = []
    count = len(payloads)
    for i, payload in enumerate(payloads):
        row = {"TS": float(i if timestamps is None else timestamps[i]), "ID": can_id,
               "LEN": int(8 if lengths is None else lengths[i])}
        for byte in range(8):
            row[f"D{byte}"] = int(payload[byte])
        rows.append(row)
    return pl.DataFrame(rows)


def _round_robin_dlc(seed=7, cycles=800):
    rng = np.random.default_rng(seed)
    payloads, lengths = [], []
    for i in range(cycles * 4):
        value = i % 4
        frame = rng.integers(0, 256, size=8, dtype=np.uint8)
        frame[0] = value
        frame[1] = value * 31 + 5
        frame[4] = value * 17 + 8
        frame[5] = value * 11 + 6
        payloads.append(frame)
        lengths.append(4 if value == 3 else 8)
    return _frames_for_payload(payloads, lengths=lengths)


def _hierarchical(seed=11, cycles=100):
    rng = np.random.default_rng(seed)
    payloads = []
    for i in range(cycles * 90):
        outer, inner = i % 5, (i // 5) % 18
        frame = rng.integers(0, 256, size=8, dtype=np.uint8)
        frame[0] = outer
        frame[1] = inner
        frame[2] = outer * 43 + 9
        frame[3] = outer * 29 + 3
        frame[4] = outer * 19 + 7
        payloads.append(frame)
    return _frames_for_payload(payloads)


def _counter_plus_index(seed=29, cycles=100):
    rng = np.random.default_rng(seed)
    payloads = []
    for i in range(cycles * 8):
        counter, index = (i // 8) % 256, i % 8
        frame = rng.integers(0, 256, size=8, dtype=np.uint8)
        frame[0] = counter
        frame[1] = index
        frame[2] = index * 23 + 7
        frame[3] = index * 17 + 9
        frame[4] = index * 11 + 3
        frame[5] = index * 7 + 1
        payloads.append(frame)
    return _frames_for_payload(payloads)


class MuxDetectorTests(unittest.TestCase):
    def test_confidence_uses_coverage_margin_period_stability_and_extension_agreement(self):
        result = detect_muxes(synthetic_mux(ids=1, frames=2400))[0]

        self.assertEqual(result["confidence"], "high")
        self.assertGreaterEqual(result["coverage"], 0.97)
        self.assertGreaterEqual(result["extension_agreement"], 0.87)
        self.assertGreaterEqual(result["period_stability"], 0.8)
        self.assertIn("gain_margin", result)

    def test_confidence_distinguishes_medium_and_ambiguous_evidence(self):
        self.assertEqual(
            _confidence_from_evidence(
                coverage=0.998, gain_margin=-0.071, period_stability=0.918,
                extension_agreement=0.868, ambiguous=True,
            ),
            "medium",
        )
        self.assertEqual(
            _confidence_from_evidence(
                coverage=0.999, gain_margin=-0.006, period_stability=0.895,
                extension_agreement=0.882, ambiguous=True,
            ),
            "medium",
        )
        self.assertEqual(
            _confidence_from_evidence(
                coverage=1.0, gain_margin=-0.137, period_stability=0.457,
                extension_agreement=0.998, ambiguous=True,
            ),
            "low",
        )

    def test_no_mux_has_no_confidence(self):
        rng = np.random.default_rng(101)
        payloads = rng.integers(0, 256, size=(1200, 8), dtype=np.uint8)

        result = detect_muxes(_frames_for_payload(payloads))[0]

        self.assertFalse(result["has_mux"])
        self.assertIsNone(result["confidence"])

    def test_detects_multibyte_selector_and_is_deterministic(self):
        df = synthetic_mux()
        first = detect_muxes(df)
        second = detect_muxes(pl.concat([df.filter(pl.col("ID") == "002"), df.filter(pl.col("ID") == "000"), df.filter(pl.col("ID") == "001")]))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 3)
        self.assertTrue(all(item["has_mux"] for item in first))
        self.assertTrue(all(len(item["values"]) == 40 for item in first))

    def test_extension_keeps_full_four_byte_selector_with_rare_payload_child(self):
        payloads = []
        rng = np.random.default_rng(17)
        values = rng.choice(20, size=30_000, p=[0.5] + [0.5 / 19] * 19)
        rare = set(rng.choice(np.flatnonzero(values == 0), size=60, replace=False))
        for row, value in enumerate(values):
            frame = np.zeros(8, dtype=np.uint8)
            frame[0] = 0x20 if row in rare else 0x30
            frame[1] = value % 2
            frame[2] = value // 2
            frame[3] = (value * 61 + 7) & 255
            frame[4] = (value * 13 + 5) & 255
            frame[5] = (value * 17 + 3) & 255
            payloads.append(frame)
        result = detect_muxes(_frames_for_payload(payloads))[0]
        self.assertEqual(result["selector"], (0, 1, 2, 3))

    def test_selector_extension_repeats_neighbor_steps_until_four_bytes(self):
        candidates = [
            {"start": 2, "width": 1, "k": 10, "score": 0.9, "coverage": 0.99},
            {"start": 1, "width": 2, "k": 12, "score": 0.86, "coverage": 0.99, "extension_determinism": 0.99},
            {"start": 0, "width": 3, "k": 15, "score": 0.82, "coverage": 0.99, "extension_determinism": 0.99},
            {"start": 0, "width": 4, "k": 19, "score": 0.78, "coverage": 0.99, "extension_determinism": 0.99},
        ]
        selected = _extend_adjacent_candidates(candidates[0], candidates, MuxDetectorConfig())
        self.assertEqual((selected["start"], selected["width"]), (0, 4))

    def test_variable_payload_child_is_not_treated_as_selector_extension(self):
        base = {"start": 1, "width": 1, "k": 8, "score": 0.9, "coverage": 0.99}
        payload_child = {
            "start": 0, "width": 2, "k": 12, "score": 0.88, "coverage": 0.99,
            "extension_determinism": 0.85,
        }
        selected = _extend_adjacent_candidates(base, [base, payload_child], MuxDetectorConfig())
        self.assertIs(selected, base)
        redundant_payload = {
            "start": 1, "width": 2, "k": 8, "score": 0.9, "coverage": 0.99,
            "extension_determinism": 1.0,
        }
        selected = _extend_adjacent_candidates(base, [base, redundant_payload], MuxDetectorConfig())
        self.assertIs(selected, base)

    def test_extension_stops_when_total_cardinality_doubles(self):
        candidates = [
            {"start": 2, "width": 1, "k": 8, "score": 0.9, "coverage": 0.99},
            {"start": 1, "width": 2, "k": 14, "score": 0.86, "coverage": 0.99, "extension_determinism": 0.99},
            {"start": 0, "width": 3, "k": 17, "score": 0.82, "coverage": 0.99, "extension_determinism": 0.99},
            {"start": 0, "width": 4, "k": 20, "score": 0.78, "coverage": 0.99, "extension_determinism": 0.99},
        ]
        selected = _extend_adjacent_candidates(candidates[0], candidates, MuxDetectorConfig())
        self.assertEqual((selected["start"], selected["width"]), (1, 2))

    def test_correlated_payload_byte_does_not_expand_selector(self):
        payloads = []
        for repeat in range(1600):
            value = repeat % 8
            frame = np.zeros(8, dtype=np.uint8)
            frame[0] = value
            frame[1] = value * 31 + 5
            frame[2] = value * 17 + 9
            frame[3] = value * 11 + 3
            frame[4] = (repeat * 13 + value) & 255
            payloads.append(frame)
        result = detect_muxes(_frames_for_payload(payloads))[0]
        self.assertEqual(result["selector"], (0,))
        self.assertTrue(result["selector_ambiguous"])
        self.assertEqual(result["confidence"], "low")

    def test_direct_slow_signal_and_constant_bytes_are_not_mux(self):
        rows = []
        for i in range(1000):
            row = {"TS": i * 0.1, "ID": "100", "LEN": 8}
            for j in range(8):
                row[f"D{j}"] = (i // 200 if j == 0 else 0)
            rows.append(row)
        self.assertFalse(detect_muxes(pl.DataFrame(rows))[0]["has_mux"])

    def test_counter_plus_index_recommends_index_byte(self):
        result = detect_muxes(_counter_plus_index())[0]
        self.assertTrue(result["has_mux"])
        self.assertEqual(result["selector"], (1,))
        self.assertTrue(result["discarded"]["counter"] > 0)

    def test_pure_counter_is_rejected(self):
        rng = np.random.default_rng(31)
        payloads = []
        for i in range(1200):
            frame = rng.integers(0, 256, size=8, dtype=np.uint8)
            frame[0] = i % 16
            payloads.append(frame)
        result = detect_muxes(_frames_for_payload(payloads))[0]
        self.assertFalse(result["has_mux"])
        self.assertTrue(result["counter_like"])

    def test_round_robin_selector_with_short_dlc_value(self):
        result = detect_muxes(_round_robin_dlc())[0]
        self.assertTrue(result["has_mux"])
        self.assertEqual(result["selector"], (0,))
        self.assertEqual(len(result["values"]), 4)
        self.assertTrue(result["variable_dlc"])
        value_three = next(value for value in result["values"] if value["value"] == "03")
        self.assertEqual(value_three["dlc"], 4)

    def test_shorter_selector_window_is_kept_as_a_dlc_context_value(self):
        rng = np.random.default_rng(106)
        payloads, lengths = [], []
        for i in range(1200):
            value = i % 4
            frame = rng.integers(0, 256, size=8, dtype=np.uint8)
            frame[1] = value
            frame[2] = value * 31 + 5
            frame[3] = value * 17 + 3
            payloads.append(frame)
            lengths.append(2 if value == 3 else 8)
        result = detect_muxes(_frames_for_payload(payloads, lengths=lengths),
                              config=MuxDetectorConfig(min_gain=0.1),
                              forced_selectors={"400": (1, 2)})[0]
        self.assertEqual(len(result["values"]), 4)
        self.assertTrue(any("DLC 2" in row["value"] for row in result["values"]))

    def test_uniform_random_bytes_are_not_a_mux(self):
        rng = np.random.default_rng(101)
        payloads = rng.integers(0, 256, size=(2400, 8), dtype=np.uint8)
        result = detect_muxes(_frames_for_payload(payloads))[0]
        self.assertFalse(result["has_mux"])

    def test_independent_analog_sensor_does_not_hide_a_mux(self):
        rng = np.random.default_rng(102)
        payloads = []
        for i in range(3200):
            value = i % 16
            frame = rng.integers(0, 256, size=8, dtype=np.uint8)
            frame[0] = value
            frame[1] = value * 9 + 2
            frame[2:4] = rng.integers(0, 256, size=2, dtype=np.uint8)
            frame[4] = (value * 13 + 1) & 255
            frame[5] = (value * 7 + 3) & 255
            frame[6] = (value * 19 + 5) & 255
            payloads.append(frame)
        result = detect_muxes(_frames_for_payload(payloads))[0]
        self.assertTrue(result["has_mux"])
        self.assertEqual(result["selector"], (0,))

    def test_hierarchy_is_reported_without_selector_explosion(self):
        result = detect_muxes(_hierarchical())[0]
        self.assertTrue(result["has_mux"])
        self.assertTrue(result["hierarchy_suspected"])
        self.assertLess(len(result["selector"]), 4)

    def test_recalculation_can_force_a_contiguous_selector(self):
        result = detect_muxes(synthetic_mux(ids=1, frames=800), forced_selectors={"000": (1, 2)})[0]
        self.assertEqual(result["selector"], (1, 2))

    def test_progress_and_id_filter(self):
        calls = []
        result = detect_muxes(synthetic_mux(), can_ids=["001"], progress=lambda a, b: calls.append((a, b)))
        self.assertEqual([x["can_id"] for x in result], ["001"])
        self.assertEqual(calls, [(1, 1)])


if __name__ == "__main__":
    unittest.main()
