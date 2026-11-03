from __future__ import annotations

import unittest

import polars as pl

from models.analysis_context import AnalysisContext
from services.mcp_session import McpSessionSnapshot


def _frames(rows: list[tuple[float, str, str, int, str]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema=["TS", "Bus", "ID", "LEN", "DATA"],
        orient="row",
    )


class McpSessionSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = McpSessionSnapshot(frame_capacity=3, max_query_frames=3)

    def test_replace_captures_session_metadata_and_recent_frames(self) -> None:
        source = _frames([
            (1.0, "can0", "100", 1, "00"),
            (2.0, "can0", "101", 1, "01"),
            (3.0, "can0", "100", 1, "02"),
            (4.0, "can0", "100", 1, "03"),
        ])
        self.state.replace_dataframe(
            source,
            can_ids=["100", "101"],
            source_paths=["/logs/field.log"],
            unsaved=True,
            connection_running=False,
        )

        status = self.state.get_open_session()
        self.assertEqual(status["frame_count"], 4)
        self.assertEqual(status["can_ids"], ["100", "101"])
        self.assertEqual(McpSessionSnapshot._sort_can_ids(["10", "2", "100"]), ("2", "10", "100"))
        self.assertEqual(status["source_paths"], ["/logs/field.log"])
        self.assertTrue(status["unsaved_capture"])
        self.assertEqual(status["last_timestamp"], 4.0)
        result = self.state.get_recent_frames(limit=2)
        self.assertEqual([frame["DATA"] for frame in result["frames"]], ["02", "03"])
        self.assertTrue(result["buffer_truncated"])

    def test_append_updates_recent_buffer_without_replacing_session(self) -> None:
        self.state.replace_dataframe(
            _frames([(1.0, "can0", "100", 1, "00")]),
            can_ids=["100"],
            source_paths=[],
            unsaved=False,
            connection_running=False,
        )
        self.state.set_connection_mode("live")
        self.state.append_rows(
            _frames([(2.0, "can0", "101", 1, "01")]),
            can_ids=["100", "101"],
            source_paths=["/recording/current.log"],
            total_frames=2,
            unsaved=True,
            connection_running=True,
        )

        status = self.state.get_open_session()
        self.assertEqual(status["frame_count"], 2)
        self.assertTrue(status["connection_running"])
        self.assertEqual(status["connection_mode"], "live")
        self.assertTrue(status["unsaved_capture"])
        self.assertEqual(len(self.state.get_recent_frames(limit=3)["frames"]), 2)

    def test_connection_mode_distinguishes_replay(self) -> None:
        self.state.set_connection_mode("replay")
        self.state.replace_dataframe(
            _frames([(1.0, "can0", "100", 1, "00")]),
            can_ids=["100"], source_paths=[], unsaved=False, connection_running=True,
        )
        self.assertTrue(self.state.get_open_session()["connection_running"])
        self.assertEqual(self.state.get_open_session()["connection_mode"], "replay")

    def test_recent_frames_filter_id_and_absolute_timestamp(self) -> None:
        self.state.replace_dataframe(
            _frames([
                (1.0, "can0", "100", 1, "00"),
                (2.0, "can0", "101", 1, "01"),
                (3.0, "can0", "100", 1, "02"),
            ]),
            can_ids=["100", "101"], source_paths=[], unsaved=False, connection_running=False,
        )
        result = self.state.get_recent_frames(limit=3, can_id="0x100", ts_min=2.0, ts_max=3.0)
        self.assertEqual([frame["TS"] for frame in result["frames"]], [3.0])

    def test_context_is_serialized_and_marker_defaults_to_latest_frame(self) -> None:
        self.state.replace_dataframe(
            _frames([(12.5, "can0", "100", 1, "AA")]),
            can_ids=["100"], source_paths=[], unsaved=False, connection_running=False,
        )
        context = AnalysisContext(can_id="100", byte_indices=(0,), source_window="Analyze")
        self.state.set_analysis_context(context)

        self.assertEqual(self.state.get_analysis_context()["can_id"], "100")
        marker = self.state.add_session_marker("pedal pressed")
        self.assertEqual(marker["timestamp"], 12.5)
        self.assertEqual(self.state.list_session_markers(), [marker])

    def test_marker_accepts_explicit_timestamp_and_rejects_invalid_values(self) -> None:
        self.state.replace_dataframe(
            _frames([(12.5, "can0", "100", 1, "AA")]),
            can_ids=["100"], source_paths=[], unsaved=False, connection_running=False,
        )
        marker = self.state.add_session_marker("start", timestamp=9.0)
        self.assertEqual(marker["timestamp"], 9.0)
        with self.assertRaises(ValueError):
            self.state.add_session_marker("  ")
        with self.assertRaises(ValueError):
            self.state.add_session_marker("bad", timestamp=float("nan"))

    def test_recent_frame_request_validates_limit_and_range(self) -> None:
        with self.assertRaises(ValueError):
            self.state.get_recent_frames(limit=0)
        with self.assertRaises(ValueError):
            self.state.get_recent_frames(limit=501)
        with self.assertRaises(ValueError):
            self.state.get_recent_frames(limit=1, ts_min=3.0, ts_max=2.0)


if __name__ == "__main__":
    unittest.main()
