from __future__ import annotations

import unittest

import polars as pl
from PySide6.QtCore import QCoreApplication

from models.bit_track import BitTrack
from services.state_tracker import BitStateAccumulator
from viewmodels.state_tracker_viewmodel import StateTrackerViewModel


def frames(rows: list[tuple[float, str, int, int]]) -> pl.DataFrame:
    return pl.DataFrame(
        [{"TS": ts, "ID": can_id, "LEN": length, "D0": byte_value} for ts, can_id, length, byte_value in rows],
        schema={"TS": pl.Float64, "ID": pl.Utf8, "LEN": pl.UInt8, "D0": pl.UInt8},
    )


class BitStateAccumulatorTests(unittest.TestCase):
    def test_ignores_other_ids_missing_bytes_and_repeated_values(self) -> None:
        data = frames([
            (1.0, "123", 1, 0),
            (2.0, "456", 1, 1),
            (3.0, "123", 0, 1),
            (4.0, "123", 1, 0),
            (5.0, "123", 1, 1),
        ])
        accumulator = BitStateAccumulator(BitTrack("123", 0, 0))

        accumulator.reset(data)

        self.assertEqual(accumulator.snapshot(), ([1.0, 5.0], [0, 1]))

    def test_incremental_chunks_match_batch_with_equal_timestamps(self) -> None:
        data = frames([
            (1.0, "123", 1, 0),
            (2.0, "123", 1, 1),
            (2.0, "123", 1, 0),
            (3.0, "123", 1, 1),
        ])
        batch = BitStateAccumulator(BitTrack("123", 0, 0))
        batch.reset(data)
        incremental = BitStateAccumulator(BitTrack("123", 0, 0))
        incremental.append(data.slice(0, 2))
        incremental.append(data.slice(2, 2))

        self.assertEqual(incremental.snapshot(), batch.snapshot())
        self.assertEqual(incremental.snapshot(), ([1.0, 2.0, 2.0, 3.0], [0, 1, 0, 1]))


class StateTrackerViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_rows_append_incrementally_and_replacement_rebuilds_tracks(self) -> None:
        initial = frames([(1.0, "123", 1, 0)])
        vm = StateTrackerViewModel(initial)
        self.assertTrue(vm.add_track("123", 0, 0))
        track = vm.tracks[0]
        vm.append_rows(frames([(2.0, "123", 1, 1)]))
        self.assertEqual(vm.track_data(track), ([1.0, 2.0], [0, 1]))

        replacement = frames([(10.0, "123", 1, 1)])
        vm.reset_dataframe(replacement)

        self.assertEqual(vm.track_data(track), ([10.0], [1]))
        self.assertEqual(vm.latest_timestamp, 10.0)

    def test_dataframe_change_is_reference_only_and_chunk_updates_ids_and_latest(self) -> None:
        initial = frames([(1.0, "123", 1, 0)])
        vm = StateTrackerViewModel(initial)
        replacement_reference = frames([(2.0, "123", 1, 0), (5.0, "456", 1, 0)])
        vm.set_dataframe(replacement_reference)

        self.assertEqual(vm.latest_timestamp, 1.0)
        vm.append_rows(replacement_reference.slice(1), ["456"])

        self.assertEqual(vm.latest_timestamp, 5.0)
        self.assertEqual(vm.available_can_ids, ("123", "456"))

    def test_chunk_emits_only_changed_tracks_in_one_update(self) -> None:
        vm = StateTrackerViewModel(frames([(1.0, "123", 1, 0)]))
        vm.add_track("123", 0, 0)
        vm.add_track("123", 0, 1)
        appended = []
        vm.transitions_appended.connect(appended.append)

        vm.append_rows(frames([(2.0, "123", 1, 1)]))

        self.assertEqual(len(appended), 1)
        self.assertEqual(tuple(appended[0]), (vm.tracks[0],))

    def test_duplicate_track_is_not_added(self) -> None:
        vm = StateTrackerViewModel(frames([(1.0, "123", 1, 0)]))
        self.assertTrue(vm.add_track("123", 0, 0))
        self.assertFalse(vm.add_track("123", 0, 0))
        self.assertFalse(vm.add_track("123", 8, 0))
        self.assertEqual(len(vm.tracks), 1)


if __name__ == "__main__":
    unittest.main()
