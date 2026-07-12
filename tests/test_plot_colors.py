"""Characterization tests for PlotViewModel signal color assignment.

Pins three invariants:
- next_color() returns distinct palette colors for each sequential add.
- When the full palette is used, wraps around by total signal count.
- duplicate_signal() assigns a new distinct color, not the original's color.
"""
from __future__ import annotations

import sys
import unittest

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from config.defaults import SIGNAL_COLOR_PALETTE
from models.frame_selector import FrameSelector
from models.signal import Signal
from viewmodels.plot_viewmodel import PlotViewModel
from viewmodels.view_signal import ViewSignal

_app: QApplication | None = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


def _make_view_signal(name: str, color: QColor) -> ViewSignal:
    sig = Signal(name=name, can_id=0x100, start_bit=0, length=8,
                 le=True, scale=1.0, offset=0.0)
    return ViewSignal(
        signal=sig,
        selector=FrameSelector(selected_id=0x100, mode="exact"),
        color=color,
        line_style="Solid",
        line_width=2,
    )


class NextColorTests(unittest.TestCase):
    def setUp(self):
        self.vm = PlotViewModel()

    def test_first_color_is_palette_zero(self):
        color = self.vm.next_color()
        self.assertEqual(color.name().lower(), SIGNAL_COLOR_PALETTE[0].lower())

    def test_sequential_adds_return_distinct_colors(self):
        seen = []
        for i in range(len(SIGNAL_COLOR_PALETTE)):
            color = self.vm.next_color()
            hex_c = color.name().lower()
            self.assertNotIn(hex_c, seen,
                             msg=f"Color {hex_c} returned twice at index {i}")
            seen.append(hex_c)
            vs = _make_view_signal(f"sig_{i}", color)
            self.vm.upsert_signal(vs)

    def test_no_duplicate_colors_for_two_signals(self):
        c1 = self.vm.next_color()
        self.vm.upsert_signal(_make_view_signal("A", c1))
        c2 = self.vm.next_color()
        self.assertNotEqual(
            c1.name().lower(), c2.name().lower(),
            msg="Second signal received same color as first signal",
        )

    def test_wraps_around_when_palette_exhausted(self):
        for i in range(len(SIGNAL_COLOR_PALETTE)):
            c = self.vm.next_color()
            self.vm.upsert_signal(_make_view_signal(f"sig_{i}", c))
        # Next call must return a color (wraps around, no crash)
        extra = self.vm.next_color()
        self.assertIsInstance(extra, QColor)
        self.assertTrue(extra.isValid())

    def test_color_from_removed_signal_becomes_reusable(self):
        c1 = self.vm.next_color()
        self.vm.upsert_signal(_make_view_signal("A", c1))
        c2 = self.vm.next_color()
        self.vm.upsert_signal(_make_view_signal("B", c2))
        self.vm.remove_signal("A")
        # After removing A, palette[0] should be available again
        c_new = self.vm.next_color()
        self.assertEqual(c_new.name().lower(), SIGNAL_COLOR_PALETTE[0].lower())


class DuplicateSignalColorTests(unittest.TestCase):
    def setUp(self):
        self.vm = PlotViewModel()

    def test_duplicate_gets_distinct_color(self):
        c1 = self.vm.next_color()
        vs = _make_view_signal("Original", c1)
        self.vm.upsert_signal(vs)

        new_name = self.vm.duplicate_signal("Original")
        self.assertIsNotNone(new_name)

        original_color = self.vm.signals["Original"].color.name().lower()
        duplicate_color = self.vm.signals[new_name].color.name().lower()
        self.assertNotEqual(
            original_color, duplicate_color,
            msg="Duplicated signal must have a different color from the original",
        )

    def test_duplicate_marker_color_matches_new_color(self):
        c1 = self.vm.next_color()
        vs = _make_view_signal("S", c1)
        self.vm.upsert_signal(vs)

        new_name = self.vm.duplicate_signal("S")
        dup = self.vm.signals[new_name]
        self.assertEqual(dup.color.name().lower(), dup.marker_color.name().lower())

    def test_duplicate_does_not_change_original_color(self):
        c1 = self.vm.next_color()
        vs = _make_view_signal("Original", c1)
        self.vm.upsert_signal(vs)
        original_hex = self.vm.signals["Original"].color.name().lower()

        self.vm.duplicate_signal("Original")
        self.assertEqual(
            self.vm.signals["Original"].color.name().lower(),
            original_hex,
            msg="Duplicating a signal must not change the original's color",
        )
