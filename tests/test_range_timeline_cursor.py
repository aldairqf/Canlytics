from __future__ import annotations

import sys
import unittest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from models.analysis_context import AnalysisMarker
from views.widgets.range_timeline import RangeTimeline


class RangeTimelineCursorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_clicking_timeline_sets_global_cursor_time(self):
        timeline = RangeTimeline()
        timeline.resize(200, 90)
        timeline.show()
        self.app.processEvents()
        values = []
        timeline.cursor_time_changed.connect(values.append)

        QTest.mouseClick(timeline, Qt.LeftButton, pos=QPoint(100, 35))

        self.assertEqual(len(values), 1)
        self.assertAlmostEqual(values[0], 0.5)
        self.assertAlmostEqual(timeline._cursor_time, 0.5)
        timeline.close()

    def test_event_markers_are_retained_as_epoch_references(self):
        timeline = RangeTimeline()
        marker = AnalysisMarker(sequence=1, name="Load", timestamp=123.5, state="ON")

        timeline.set_event_markers((marker,))

        self.assertEqual(timeline._event_markers, ((123.5, "ON", "Load"),))
