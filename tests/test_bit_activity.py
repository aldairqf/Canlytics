from __future__ import annotations

import unittest
import random

import polars as pl

from services.bit_activity import BitActivityAccumulator


def frames(rows: list[tuple[str, int, tuple[int, ...]]]) -> pl.DataFrame:
    records = []
    for can_id, length, payload in rows:
        padded = (*payload, *(0 for _ in range(8 - len(payload))))
        records.append({"ID": can_id, "LEN": length, **{f"D{i}": padded[i] for i in range(8)}})
    return pl.DataFrame(records, schema={"ID": pl.Utf8, "LEN": pl.UInt8, **{f"D{i}": pl.UInt8 for i in range(8)}})


class BitActivityAccumulatorTests(unittest.TestCase):
    def test_chunk_boundaries_match_full_seed(self) -> None:
        all_frames = frames([
            ("123", 2, (0x00, 0x00)),
            ("456", 1, (0xFF,)),
            ("123", 2, (0x01, 0x00)),
            ("123", 1, (0x03,)),
            ("456", 2, (0x00, 0x01)),
        ])
        incremental = BitActivityAccumulator()
        incremental.ingest(all_frames.slice(0, 2))
        incremental.ingest(all_frames.slice(2, 1))
        incremental.ingest(all_frames.slice(3, 2))

        seeded = BitActivityAccumulator()
        seeded.seed(all_frames)
        self.assertEqual(incremental.snapshot(), seeded.snapshot())

    def test_ids_keep_independent_previous_payloads(self) -> None:
        tracker = BitActivityAccumulator()
        tracker.seed(frames([
            ("123", 1, (0x00,)),
            ("456", 1, (0xFF,)),
            ("123", 1, (0x01,)),
        ]))
        by_id = {item.can_id: item for item in tracker.snapshot()}

        self.assertEqual(by_id["123"].bit_flip_counts[0], 1)
        self.assertEqual(by_id["123"].bit_comparison_counts[0], 1)
        self.assertEqual(by_id["456"].bit_comparison_counts, (0,) * 8)

    def test_variable_dlc_counts_only_pairs_with_observed_bits(self) -> None:
        tracker = BitActivityAccumulator()
        tracker.seed(frames([
            ("123", 1, (0x00,)),
            ("123", 2, (0x00, 0xFF)),
            ("123", 2, (0x00, 0x00)),
        ]))
        result = tracker.snapshot()[0]

        self.assertEqual(result.bit_comparison_counts[0], 2)
        self.assertEqual(result.bit_comparison_counts[8], 1)
        self.assertEqual(result.flip_rates[8], 1.0)

    def test_segment_sample_count_uses_bits_available_in_that_segment(self) -> None:
        tracker = BitActivityAccumulator()
        tracker.seed(frames([
            *(('123', 1, (0x00,)) for _ in range(98)),
            ('123', 2, (0x00, 0x00)),
            ('123', 2, (0x00, 0x00)),
        ]))
        result = tracker.snapshot()[0]

        high_byte = next(item for item in result.suggestions if item.start_bit == 8)
        self.assertEqual(high_byte.sample_count, 2)

    def test_magnitude_and_boundaries_follow_read_order(self) -> None:
        tracker = BitActivityAccumulator()
        tracker.seed(frames([("123", 1, (value,)) for value in range(9)]))
        result = tracker.snapshot()[0]

        self.assertAlmostEqual(result.flip_rates[0], 1.0)
        self.assertAlmostEqual(result.flip_rates[1], 0.5)
        self.assertAlmostEqual(result.magnitudes[1], -0.30103, places=4)
        self.assertEqual(result.boundaries, ())
        self.assertIn(("counter", 0, 4), {
            (item.kind, item.start_bit, item.length) for item in result.suggestions
        })

    def test_counter_suffix_length_is_measured_from_low_order_bits(self) -> None:
        tracker = BitActivityAccumulator()
        tracker.seed(frames([
            ("123", 8, (value, 0, 0, 0, 0, 0, 0, 0))
            for value in range(256)
        ]))
        result = tracker.snapshot()[0]

        self.assertIn(("counter", 0, 6), {
            (item.kind, item.start_bit, item.length) for item in result.suggestions
        })
        self.assertIn(("constant", 8, 56), {
            (item.kind, item.start_bit, item.length) for item in result.suggestions
        })

    def test_constant_and_crc_like_payloads_receive_preliminary_classes(self) -> None:
        constant = frames([("123", 1, (0xA5,))] * 20)
        randomizer = random.Random(42)
        crc_like = frames([("456", 1, (randomizer.randrange(256),)) for _ in range(256)])
        tracker = BitActivityAccumulator()
        tracker.seed(pl.concat([constant, crc_like]))
        by_id = {item.can_id: item for item in tracker.snapshot()}

        self.assertEqual(by_id["123"].suggestions[0].kind, "constant")
        self.assertIn("crc", {item.kind for item in by_id["456"].suggestions})

    def test_byte_histograms_count_values_and_dlc(self) -> None:
        tracker = BitActivityAccumulator()
        tracker.seed(frames([
            ("123", 2, (0xAA, 0x11)),
            ("123", 1, (0xAA,)),
            ("123", 2, (0xBB, 0x11)),
        ]))
        histograms = tracker.snapshot()[0].byte_histograms

        self.assertEqual(histograms[0].sample_count, 3)
        self.assertEqual(histograms[0].counts[0xAA], 2)
        self.assertEqual(histograms[0].counts[0xBB], 1)
        self.assertEqual(histograms[1].sample_count, 2)
        self.assertEqual(histograms[1].counts[0x11], 2)

    def test_empty_and_single_sample_have_no_unearned_activity(self) -> None:
        tracker = BitActivityAccumulator()
        self.assertEqual(tracker.ingest(frames([])), ())
        progress: list[tuple[int, int]] = []
        self.assertEqual(
            tracker.ingest(
                frames([("", 1, (0x00,))]),
                on_progress=lambda done, total: progress.append((done, total)),
            ),
            (),
        )
        self.assertEqual(progress, [(1, 1)])
        tracker.seed(frames([("123", 1, (0x00,))]))
        result = tracker.snapshot()[0]

        self.assertEqual(result.flip_rates, (None,) * 8)
        self.assertEqual(result.suggestions[0].kind, "insufficient")


if __name__ == "__main__":
    unittest.main()
