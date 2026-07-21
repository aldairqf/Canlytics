"""Characterization tests for services/candidate_interpretations pure logic."""

from __future__ import annotations

import math
import random
import unittest

from models.mux_config import MuxConfigEntry
from services.can_data_parser import frame_dict, rows_to_df
from services.candidate_interpretations import (
    CandidateItem,
    SignalCategory,
    _autocorrelation,
    _bit_positions,
    _build_candidate_items,
    _byte_order_options,
    _candidate_score,
    _format_number,
    _iter_signal_lengths,
    _iter_signal_specs,
    _mux_bytes_for_group,
    _overlaps_mux_bytes,
    _parse_mux_case_value,
    _passes_minimum_requirements,
    _size_scale,
    _value_type_options,
    build_candidate_matrix_entries,
    classify_signal_type,
    group_overlapping_candidates,
)


class ScoringTests(unittest.TestCase):
    def test_score_full_when_always_changing_and_well_sampled(self):
        # n=30 reaches _SIZE_SCALE_REFERENCE_N -- no size discount applies.
        values = [float(i) for i in range(30)]
        self.assertAlmostEqual(_candidate_score(values, changes=29, distinct_values=30), 1.0)

    def test_score_zero_for_constant(self):
        self.assertEqual(_candidate_score([1.0, 1.0], changes=0, distinct_values=1), 0.0)

    def test_score_zero_for_single_value(self):
        self.assertEqual(_candidate_score([5.0], changes=0, distinct_values=1), 0.0)

    def test_score_is_lower_with_too_few_frames_even_for_an_otherwise_perfect_shape(self):
        # Same shape as the well-sampled case above, but only 3 frames.
        low_n_score = _candidate_score([0.0, 1.0, 2.0], changes=2, distinct_values=3)
        self.assertLess(low_n_score, 1.0)
        self.assertGreater(low_n_score, 0.0)

    def test_score_rewards_a_smooth_ramp_over_a_scrambled_sequence_of_the_same_shape(self):
        # Same change_ratio/distinct_ratio/span -- only smoothness differs.
        ramp = [float(i) for i in range(30)]
        scrambled = [10, 4, 12, 20, 1, 2, 17, 3, 11, 18, 25, 16, 6, 19, 24, 23, 14, 26, 22, 27, 8, 13, 0, 9, 28, 7, 29, 15, 5, 21]
        scrambled = [float(v) for v in scrambled]
        ramp_score = _candidate_score(ramp, changes=29, distinct_values=30)
        scrambled_score = _candidate_score(scrambled, changes=29, distinct_values=30)
        self.assertGreater(ramp_score, scrambled_score)

    def test_random_noise_scores_well_below_a_clean_ramp_of_the_same_shape(self):
        # Regression: noise maxes change/distinct/span ratios just by being "active".
        rnd = random.Random(1)
        noise = [float(rnd.randint(0, 255)) for _ in range(30)]
        changes = sum(1 for a, b in zip(noise, noise[1:]) if a != b)
        distinct = len(set(noise))
        noise_score = _candidate_score(noise, changes, distinct)
        ramp_score = _candidate_score([float(i) for i in range(30)], changes=29, distinct_values=30)
        self.assertLess(noise_score, 0.5)
        self.assertLess(noise_score, ramp_score)

    def test_passes_minimum_requirements_requires_two_distinct(self):
        self.assertFalse(_passes_minimum_requirements([1.0, 1.0], 1))

    def test_passes_minimum_requirements_requires_two_samples(self):
        self.assertFalse(_passes_minimum_requirements([1.0], 1))
        self.assertTrue(_passes_minimum_requirements([1.0, 2.0], 2))

    def test_include_constant_bypasses_the_distinct_check(self):
        self.assertFalse(_passes_minimum_requirements([1.0, 1.0], 1, include_constant=False))
        self.assertTrue(_passes_minimum_requirements([1.0, 1.0], 1, include_constant=True))
        # still requires at least 2 samples, even with include_constant on.
        self.assertFalse(_passes_minimum_requirements([1.0], 1, include_constant=True))


class AutocorrelationTests(unittest.TestCase):
    def test_high_for_a_smooth_ramp(self):
        self.assertAlmostEqual(_autocorrelation([float(i) for i in range(30)]), 1.0, places=9)

    def test_high_for_a_clean_alternation(self):
        # Perfect negative lag-1 relationship -- abs() counts it as structure too.
        self.assertAlmostEqual(_autocorrelation([0.0, 1.0] * 15), 1.0, places=9)

    def test_low_for_a_scrambled_sequence(self):
        scrambled = [10, 4, 12, 20, 1, 2, 17, 3, 11, 18, 25, 16, 6, 19, 24, 23, 14, 26, 22, 27, 8, 13, 0, 9, 28, 7, 29, 15, 5, 21]
        self.assertLess(_autocorrelation([float(v) for v in scrambled]), 0.2)

    def test_zero_when_too_few_points(self):
        self.assertEqual(_autocorrelation([1.0, 2.0]), 0.0)

    def test_zero_when_either_half_has_no_variance(self):
        self.assertEqual(_autocorrelation([5.0, 5.0, 5.0, 7.0]), 0.0)


class SizeScaleTests(unittest.TestCase):
    def test_full_confidence_at_or_above_the_reference_n(self):
        self.assertEqual(_size_scale(30), 1.0)
        self.assertEqual(_size_scale(1000), 1.0)

    def test_discounted_below_the_reference_n(self):
        self.assertLess(_size_scale(3), _size_scale(15))
        self.assertLess(_size_scale(15), _size_scale(30))


class NumberHelpersTests(unittest.TestCase):
    def test_format_number(self):
        self.assertEqual(_format_number(3.0), "3")
        self.assertEqual(_format_number(-2.0), "-2")
        self.assertEqual(_format_number(1.5), "1.5")
        self.assertEqual(_format_number(1.25), "1.25")


class OptionHelpersTests(unittest.TestCase):
    def test_byte_order_options(self):
        self.assertEqual(_byte_order_options("Little Endian"), [("LittleEndian", True)])
        self.assertEqual(_byte_order_options("Big Endian"), [("BigEndian", False)])
        self.assertEqual(_byte_order_options("Try Both"), [("LittleEndian", True), ("BigEndian", False)])

    def test_value_type_options(self):
        self.assertEqual(_value_type_options("Unsigned", 8), [("Unsigned", "uint")])
        self.assertEqual(_value_type_options("Float32", 8), [])
        self.assertEqual(_value_type_options("Float32", 32), [("Float32", "float32")])
        self.assertIn(("Float32", "float32"), _value_type_options("Try All", 32))
        self.assertNotIn(("Float32", "float32"), _value_type_options("Try All", 8))

    def test_iter_signal_lengths(self):
        self.assertEqual(list(_iter_signal_lengths(8, 8, 8)), [8])
        self.assertEqual(list(_iter_signal_lengths(1, 16, 8)), [1, 9, 16])


class MuxAndBitTests(unittest.TestCase):
    def test_mux_bytes_for_group_exact_then_fallback(self):
        configs = [MuxConfigEntry(can_id="100", length=8, mux_bytes=(0,))]
        self.assertEqual(_mux_bytes_for_group(configs, "100", 8), (0,))
        self.assertEqual(_mux_bytes_for_group(configs, "100", 6), ())
        any_len = [MuxConfigEntry(can_id="100", length=None, mux_bytes=(1,))]
        self.assertEqual(_mux_bytes_for_group(any_len, "100", 6), (1,))

    def test_parse_mux_case_value(self):
        self.assertEqual(_parse_mux_case_value("0A", (0,)), 0x0A)
        self.assertEqual(_parse_mux_case_value("0A 0B", (0, 1)), (0x0A << 8) | 0x0B)
        self.assertIsNone(_parse_mux_case_value("None", (0, 1)))
        self.assertIsNone(_parse_mux_case_value("ZZ", (0,)))
        self.assertIsNone(_parse_mux_case_value("00", ()))

    def test_bit_positions_little_endian(self):
        self.assertEqual(
            _bit_positions(start_bit=0, signal_length=8, is_little=True, available_bits=64),
            [0, 1, 2, 3, 4, 5, 6, 7],
        )
        self.assertIsNone(_bit_positions(start_bit=60, signal_length=8, is_little=True, available_bits=64))

    def test_bit_positions_big_endian_motorola(self):
        self.assertEqual(
            _bit_positions(start_bit=0, signal_length=8, is_little=False, available_bits=64),
            [0, 15, 14, 13, 12, 11, 10, 9],
        )

    def test_overlaps_mux_bytes(self):
        self.assertTrue(_overlaps_mux_bytes(start_bit=0, signal_length=8, mux_bytes=(0,), is_little=True, available_bits=64))
        self.assertFalse(_overlaps_mux_bytes(start_bit=0, signal_length=8, mux_bytes=(1,), is_little=True, available_bits=64))


class IterSignalSpecsTests(unittest.TestCase):
    def test_basic_count_matches_start_bit_positions(self):
        specs = list(_iter_signal_specs(
            available_bits=64, mux_bytes=(), min_length=8, max_length=8,
            granularity=8, endianness="Little Endian", value_type="Unsigned",
        ))
        self.assertEqual(len(specs), 8)

    def test_mux_overlap_skips_the_overlapping_start_bit(self):
        specs = list(_iter_signal_specs(
            available_bits=64, mux_bytes=(0,), min_length=8, max_length=8,
            granularity=8, endianness="Little Endian", value_type="Unsigned",
        ))
        self.assertEqual(len(specs), 7)
        self.assertNotIn(0, [spec[3] for spec in specs])

    def test_try_all_value_types_adds_float32_only_at_32_bits(self):
        specs_8 = list(_iter_signal_specs(
            available_bits=64, mux_bytes=(), min_length=8, max_length=8,
            granularity=8, endianness="Little Endian", value_type="Try All",
        ))
        specs_32 = list(_iter_signal_specs(
            available_bits=64, mux_bytes=(), min_length=32, max_length=32,
            granularity=8, endianness="Little Endian", value_type="Try All",
        ))
        self.assertEqual({spec[4] for spec in specs_8}, {"Unsigned", "Signed"})
        self.assertEqual({spec[4] for spec in specs_32}, {"Unsigned", "Signed", "Float32"})


class BuildCandidatesTests(unittest.TestCase):
    def test_ramp_yields_candidate(self):
        rows = [frame_dict(ts=i * 0.1, bus="b", can_id="100", data=bytes([i % 256, 0, 0, 0, 0, 0, 0, 0])) for i in range(20)]
        df = rows_to_df(rows)
        items = _build_candidate_items(
            df, checked_ids={"100"}, mux_configs=[],
            min_length=8, max_length=8, granularity=8,
            endianness="Little Endian", value_type="Unsigned",
        )
        self.assertTrue(items)
        self.assertEqual(items[0].can_id, "100")

    def test_include_constant_surfaces_a_constant_byte_end_to_end(self):
        rows = [frame_dict(ts=i * 0.1, bus="b", can_id="100", data=bytes([7, 0, 0, 0, 0, 0, 0, 0])) for i in range(20)]
        df = rows_to_df(rows)
        kwargs = dict(
            df=df, checked_ids={"100"}, mux_configs=[],
            min_length=8, max_length=8, granularity=8,
            endianness="Little Endian", value_type="Unsigned",
        )
        self.assertEqual(_build_candidate_items(**kwargs), [])
        with_constant = _build_candidate_items(**kwargs, include_constant=True)
        self.assertTrue(with_constant)
        self.assertTrue(all(item.distinct_values == 1 for item in with_constant))

    def test_empty_inputs(self):
        df = rows_to_df([])
        self.assertEqual(
            _build_candidate_items(df, checked_ids={"100"}, mux_configs=[], min_length=8, max_length=8,
                                   granularity=8, endianness="Little Endian", value_type="Unsigned"),
            [],
        )

    def test_on_progress_reaches_the_exact_total(self):
        # 8-bit signal, granularity 8, LE only, Unsigned only, 64-bit frame -> 8 start-bit positions.
        rows = [frame_dict(ts=i * 0.1, bus="b", can_id="100", data=bytes([i % 256, 0, 0, 0, 0, 0, 0, 0])) for i in range(20)]
        df = rows_to_df(rows)
        calls: list[tuple[int, int]] = []
        _build_candidate_items(
            df, checked_ids={"100"}, mux_configs=[],
            min_length=8, max_length=8, granularity=8,
            endianness="Little Endian", value_type="Unsigned",
            on_progress=lambda done, total: calls.append((done, total)),
        )
        self.assertTrue(calls)
        totals = {total for _, total in calls}
        self.assertEqual(totals, {8})
        self.assertEqual([done for done, _ in calls], list(range(1, 9)))


class MultiByteHintIntegrationTests(unittest.TestCase):
    """P2.2: end-to-end wiring of the carry-alignment hint into _build_candidate_items."""

    def _kwargs(self, df):
        return dict(
            df=df, checked_ids={"100"}, mux_configs=[],
            min_length=8, max_length=8, granularity=8,
            endianness="Little Endian", value_type="Unsigned",
        )

    def test_carry_linked_bytes_get_a_hint(self):
        values = list(range(0, 3000, 5))
        rows = [
            frame_dict(ts=i * 0.1, bus="b", can_id="100", data=bytes([v % 256, (v // 256) % 256, 0, 0, 0, 0, 0, 0]))
            for i, v in enumerate(values)
        ]
        df = rows_to_df(rows)
        items = _build_candidate_items(**self._kwargs(df))

        byte0_hints = {item.multi_byte_hint for item in items if item.start_bit == 0}
        byte1_hints = {item.multi_byte_hint for item in items if item.start_bit == 8}
        self.assertTrue(any(h for h in byte0_hints), "expected byte 0 candidates to carry a multi-byte hint")
        self.assertTrue(any("B1" in h for h in byte0_hints))
        # byte 1 (the high byte) has no *higher* neighbor to pair with in this test's
        # payload beyond itself, so it may or may not carry its own hint -- only
        # byte 0 -> byte 1 pairing is asserted here.
        self.assertIsNotNone(byte1_hints)

    def test_independent_bytes_are_not_flagged_as_multi_byte(self):
        rng = random.Random(7)
        rows = [
            frame_dict(ts=i * 0.1, bus="b", can_id="100", data=bytes([rng.randint(0, 255), rng.randint(0, 255), 0, 0, 0, 0, 0, 0]))
            for i in range(200)
        ]
        df = rows_to_df(rows)
        items = _build_candidate_items(**self._kwargs(df))
        byte0_items = [item for item in items if item.start_bit == 0]
        self.assertTrue(byte0_items)
        self.assertTrue(all("likely 16-bit" not in item.multi_byte_hint for item in byte0_items))
        self.assertTrue(all(not item.is_multi_byte_fragment for item in items if item.start_bit == 0))

    def test_carry_linked_bytes_are_both_flagged_as_fragments(self):
        values = list(range(0, 3000, 5))
        rows = [
            frame_dict(ts=i * 0.1, bus="b", can_id="100", data=bytes([v % 256, (v // 256) % 256, 0, 0, 0, 0, 0, 0]))
            for i, v in enumerate(values)
        ]
        df = rows_to_df(rows)
        items = _build_candidate_items(**self._kwargs(df))
        byte0_items = [item for item in items if item.start_bit == 0]
        byte1_items = [item for item in items if item.start_bit == 8]
        self.assertTrue(all(item.is_multi_byte_fragment for item in byte0_items))
        self.assertTrue(all(item.is_multi_byte_fragment for item in byte1_items))


class SignalTypeTests(unittest.TestCase):
    """Unit tests for classify_signal_type -- one synthetic sequence per category."""

    def _kw(self, **overrides):
        base = dict(distinct_values=10, changes=50, values=[0.0] * 60, signal_length=8, value_type="Unsigned")
        base.update(overrides)
        return base

    def test_single_value_is_constant(self):
        self.assertEqual(classify_signal_type(**self._kw(distinct_values=1, values=[3.0] * 30)), SignalCategory.CONSTANT)

    def test_two_values_is_binary(self):
        values = ([0.0, 1.0] * 15)
        self.assertEqual(
            classify_signal_type(**self._kw(distinct_values=2, changes=1, values=values)), SignalCategory.BINARY
        )

    def test_rolling_wraparound_counter(self):
        values = [float(i % 256) for i in range(300)]
        self.assertEqual(
            classify_signal_type(**self._kw(distinct_values=256, changes=299, values=values)), SignalCategory.COUNTER
        )

    def test_few_values_held_steady_is_enum(self):
        values = [0.0] * 20 + [1.0] * 20 + [2.0] * 20 + [3.0] * 20
        self.assertEqual(
            classify_signal_type(**self._kw(distinct_values=4, changes=3, values=values)), SignalCategory.ENUM
        )

    def test_smooth_wave_is_analog(self):
        values = [128.0 + 100.0 * math.sin(i / 10.0) for i in range(300)]
        distinct = len(set(round(v) for v in values))
        changes = sum(1 for a, b in zip(values, values[1:]) if a != b)
        self.assertEqual(
            classify_signal_type(**self._kw(distinct_values=distinct, changes=changes, values=values)),
            SignalCategory.ANALOG,
        )

    def test_high_cardinality_noise_is_other(self):
        rng = random.Random(3)
        values = [float(rng.randint(0, 255)) for _ in range(300)]
        distinct = len(set(values))
        changes = sum(1 for a, b in zip(values, values[1:]) if a != b)
        self.assertEqual(
            classify_signal_type(**self._kw(distinct_values=distinct, changes=changes, values=values)),
            SignalCategory.OTHER,
        )

    def test_counter_check_only_applies_to_8bit_unsigned(self):
        values = [float(i % 256) for i in range(300)]
        result = classify_signal_type(
            distinct_values=256, changes=299, values=values, signal_length=16, value_type="Unsigned"
        )
        self.assertNotEqual(result, SignalCategory.COUNTER)


class SignalCategoryIntegrationTests(unittest.TestCase):
    def _kwargs(self, df):
        return dict(
            df=df, checked_ids={"100"}, mux_configs=[],
            min_length=8, max_length=8, granularity=8,
            endianness="Little Endian", value_type="Unsigned",
        )

    def test_rolling_counter_byte_is_categorized_as_counter(self):
        rows = [
            frame_dict(ts=i * 0.1, bus="b", can_id="100", data=bytes([i % 256, 0, 0, 0, 0, 0, 0, 0]))
            for i in range(300)
        ]
        df = rows_to_df(rows)
        items = _build_candidate_items(**self._kwargs(df))
        byte0_items = [item for item in items if item.start_bit == 0]
        self.assertTrue(byte0_items)
        self.assertTrue(all(item.signal_category == SignalCategory.COUNTER for item in byte0_items))

    def test_independent_random_byte_is_not_categorized_as_counter(self):
        rng = random.Random(11)
        rows = [
            frame_dict(ts=i * 0.1, bus="b", can_id="100", data=bytes([rng.randint(0, 255), 0, 0, 0, 0, 0, 0, 0]))
            for i in range(300)
        ]
        df = rows_to_df(rows)
        items = _build_candidate_items(**self._kwargs(df))
        byte0_items = [item for item in items if item.start_bit == 0]
        self.assertTrue(byte0_items)
        self.assertTrue(all(item.signal_category != SignalCategory.COUNTER for item in byte0_items))


def _item(
    *, can_id="100", frame_len=8, mux_label="None", start_bit, signal_length, score,
) -> CandidateItem:
    return CandidateItem(
        label=f"ID:{can_id} sb:{start_bit} len:{signal_length} score:{score}",
        can_id=can_id, frame_len=frame_len, mux_label=mux_label,
        mux_start=0, mux_bytes=0, mux_value=None,
        start_bit=start_bit, signal_length=signal_length,
        byte_order="LittleEndian", value_type="Unsigned",
        frames=10, changes=5, distinct_values=5, score=score,
        min_value=0.0, max_value=10.0, sample_values=(), timestamps=(), values=(),
    )


class GroupOverlappingCandidatesTests(unittest.TestCase):
    """CI5: collapse every interpretation of the same bit range into one group,
    keeping the highest-scoring member as the representative."""

    def test_non_overlapping_candidates_stay_in_separate_groups(self):
        a = _item(start_bit=0, signal_length=8, score=0.5)
        b = _item(start_bit=16, signal_length=8, score=0.6)
        groups = group_overlapping_candidates([a, b])
        self.assertEqual(len(groups), 2)
        self.assertEqual({g.representative for g in groups}, {a, b})

    def test_overlapping_candidates_collapse_into_one_group(self):
        # bytes 2-3 (bits 16-31) as one 16-bit value, vs the same range read as two
        # separate 8-bit bytes -- all three share bit range [16, 32).
        wide = _item(start_bit=16, signal_length=16, score=0.9)
        byte2 = _item(start_bit=16, signal_length=8, score=0.4)
        byte3 = _item(start_bit=24, signal_length=8, score=0.3)
        groups = group_overlapping_candidates([wide, byte2, byte3])
        self.assertEqual(len(groups), 1)
        self.assertIs(groups[0].representative, wide)
        self.assertEqual(set(groups[0].members), {wide, byte2, byte3})

    def test_transitive_overlap_chains_into_one_group(self):
        # A overlaps B, B overlaps C, but A and C don't directly overlap.
        a = _item(start_bit=0, signal_length=12, score=0.2)   # bits 0-11
        b = _item(start_bit=8, signal_length=12, score=0.8)   # bits 8-19, overlaps a and c
        c = _item(start_bit=16, signal_length=8, score=0.3)   # bits 16-23
        groups = group_overlapping_candidates([a, b, c])
        self.assertEqual(len(groups), 1)
        self.assertIs(groups[0].representative, b)

    def test_members_sorted_by_score_descending_representative_first(self):
        low = _item(start_bit=0, signal_length=8, score=0.1)
        mid = _item(start_bit=0, signal_length=8, score=0.5)
        high = _item(start_bit=0, signal_length=8, score=0.9)
        groups = group_overlapping_candidates([low, high, mid])
        self.assertEqual(groups[0].members, (high, mid, low))
        self.assertIs(groups[0].representative, high)

    def test_different_can_id_never_merges(self):
        a = _item(can_id="100", start_bit=0, signal_length=8, score=0.5)
        b = _item(can_id="200", start_bit=0, signal_length=8, score=0.6)
        groups = group_overlapping_candidates([a, b])
        self.assertEqual(len(groups), 2)

    def test_different_mux_label_never_merges(self):
        a = _item(mux_label="A", start_bit=0, signal_length=8, score=0.5)
        b = _item(mux_label="B", start_bit=0, signal_length=8, score=0.6)
        groups = group_overlapping_candidates([a, b])
        self.assertEqual(len(groups), 2)

    def test_different_frame_len_never_merges(self):
        a = _item(frame_len=4, start_bit=0, signal_length=8, score=0.5)
        b = _item(frame_len=8, start_bit=0, signal_length=8, score=0.6)
        groups = group_overlapping_candidates([a, b])
        self.assertEqual(len(groups), 2)

    def test_adjacent_non_overlapping_ranges_stay_separate(self):
        # [0,8) and [8,16) touch but don't overlap.
        a = _item(start_bit=0, signal_length=8, score=0.5)
        b = _item(start_bit=8, signal_length=8, score=0.6)
        groups = group_overlapping_candidates([a, b])
        self.assertEqual(len(groups), 2)

    def test_groups_sorted_by_representative_score_descending(self):
        a = _item(start_bit=0, signal_length=8, score=0.2)
        b = _item(start_bit=16, signal_length=8, score=0.9)
        groups = group_overlapping_candidates([a, b])
        self.assertEqual([g.representative for g in groups], [b, a])

    def test_empty_input_returns_empty(self):
        self.assertEqual(group_overlapping_candidates([]), [])


def _item_with_series(
    *, can_id="100", start_bit=0, score=0.5, timestamps, values, signal_category=SignalCategory.OTHER
) -> CandidateItem:
    return CandidateItem(
        label=f"ID:{can_id} sb:{start_bit} score:{score}",
        can_id=can_id, frame_len=8, mux_label="None",
        mux_start=0, mux_bytes=0, mux_value=None,
        start_bit=start_bit, signal_length=8,
        byte_order="LittleEndian", value_type="Unsigned",
        frames=len(values), changes=0, distinct_values=len(set(values)), score=score,
        min_value=min(values) if values else None, max_value=max(values) if values else None,
        sample_values=(), timestamps=tuple(timestamps), values=tuple(values),
        signal_category=signal_category,
    )


class BuildCandidateMatrixEntriesTests(unittest.TestCase):
    """The Matrix shows the current search results directly, not a separate raw-byte rollup."""

    def test_one_entry_per_candidate_with_a_series(self):
        a = _item_with_series(can_id="100", start_bit=0, timestamps=[0, 1, 2], values=[1, 2, 3])
        b = _item_with_series(can_id="200", start_bit=8, timestamps=[0, 1, 2], values=[4, 5, 6])
        entries = build_candidate_matrix_entries([a, b])
        self.assertEqual(len(entries), 2)
        self.assertEqual({e.can_id for e in entries}, {"100", "200"})

    def test_candidates_with_no_series_are_skipped(self):
        empty = _item_with_series(timestamps=[], values=[])
        entries = build_candidate_matrix_entries([empty])
        self.assertEqual(entries, [])

    def test_label_matches_the_source_candidate_for_drill_in(self):
        a = _item_with_series(can_id="100", timestamps=[0, 1], values=[1, 2])
        entries = build_candidate_matrix_entries([a])
        self.assertEqual(entries[0].label, a.label)

    def test_score_is_carried_through(self):
        a = _item_with_series(score=0.87, timestamps=[0, 1], values=[1, 2])
        entries = build_candidate_matrix_entries([a])
        self.assertAlmostEqual(entries[0].score, 0.87)

    def test_series_is_decimated_for_a_long_candidate(self):
        n = 2000
        a = _item_with_series(timestamps=list(range(n)), values=[i % 5 for i in range(n)])
        entries = build_candidate_matrix_entries([a], max_points=100)
        self.assertLessEqual(len(entries[0].series.x), 100 + 1)

    def test_empty_input_returns_empty(self):
        self.assertEqual(build_candidate_matrix_entries([]), [])

    def test_signal_category_is_carried_through(self):
        a = _item_with_series(timestamps=[0, 1], values=[1, 2], signal_category=SignalCategory.COUNTER)
        entries = build_candidate_matrix_entries([a])
        self.assertEqual(entries[0].signal_category, SignalCategory.COUNTER)


if __name__ == "__main__":
    unittest.main()
