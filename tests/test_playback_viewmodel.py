from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import polars as pl
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from config.defaults import PLAYBACK_TICK_MS
from viewmodels.main_window_viewmodel import MainWindowViewModel
from viewmodels.playback_viewmodel import PlaybackViewModel
from viewmodels.time_cursor_viewmodel import TimeCursorViewModel
from views.main_window import MainWindow
from views.widgets.playback_controls import PlaybackControls


class PlaybackViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cursor_and_playback_position_stay_synchronized(self):
        cursor = TimeCursorViewModel()
        playback = PlaybackViewModel(cursor)
        playback.seek(12.5)
        self.assertEqual(cursor.timestamp, 12.5)
        cursor.set_timestamp(18.0, "external")
        self.assertEqual(playback.position, 18.0)

    def test_two_controls_share_playback_state(self):
        cursor = TimeCursorViewModel()
        playback = PlaybackViewModel(cursor)
        playback.set_range(0, 10)
        first = PlaybackControls(playback)
        second = PlaybackControls(playback, compact=True)
        first.play_button.click()
        self.assertTrue(second.play_button.isChecked())
        playback.set_playing(False)
        self.assertFalse(second.play_button.isChecked())
        first.close()
        second.close()

    def test_speed_step_and_seek_update_cursor(self):
        cursor = TimeCursorViewModel()
        playback = PlaybackViewModel(cursor)
        playback.set_range(0, 10)
        playback.seek(2.0)
        playback.set_step_handler(lambda direction: playback.seek(playback.position + direction * 0.5))
        playback.step(1)
        self.assertEqual(cursor.timestamp, 2.5)
        playback.step(-1)
        self.assertEqual(cursor.timestamp, 2.0)
        playback.set_speed(2.0)
        self.assertEqual(playback.speed, 2.0)

    def test_timed_steps_advance_real_time_scaled_by_speed(self):
        tick = PLAYBACK_TICK_MS / 1000.0
        for speed in (1.0, 4.0):
            cursor = TimeCursorViewModel()
            playback = PlaybackViewModel(cursor)
            playback.set_range(0, 1000)
            playback.seek(10.0)
            playback.set_speed(speed)
            for _ in range(20):
                playback.step(1, timed=True)
            self.assertAlmostEqual(cursor.timestamp, 10.0 + 20 * tick * speed)

    def test_closing_controls_stops_timer_and_double_close_is_safe(self):
        playback = PlaybackViewModel(TimeCursorViewModel())
        controls = PlaybackControls(playback)
        playback.set_range(0, 10)
        playback.set_playing(True)
        self.assertTrue(playback._timer.isActive())
        controls.close()
        controls.close()
        self.assertFalse(playback.playing)
        self.assertFalse(playback._timer.isActive())

    def test_shutdown_stops_playback(self):
        playback = PlaybackViewModel(TimeCursorViewModel())
        playback.set_range(0, 10)
        playback.set_playing(True)
        playback.shutdown()
        self.assertFalse(playback._timer.isActive())
        playback.shutdown()

    def test_slider_follows_vm_range_and_position(self):
        playback = PlaybackViewModel(TimeCursorViewModel())
        controls = PlaybackControls(playback)
        playback.set_range(100, 200)
        playback.seek(150)
        self.assertEqual(controls.slider.value(), 5000)
        playback.set_range(100, 300)
        self.assertEqual(controls.slider.value(), 2500)
        controls.close()

    def test_values_html_shows_in_controls(self):
        controls = PlaybackControls(PlaybackViewModel(TimeCursorViewModel()))
        controls.set_values_html("<b>5</b>")
        self.assertIn("5", controls.values_label.text())
        controls.clear_values()
        self.assertEqual(controls.values_label.text(), "")
        controls.close()


class PlaybackWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _vm_with_data(self):
        vm = MainWindowViewModel()
        df = pl.DataFrame({"TS": [100.0, 150.0, 200.0]})
        vm._on_playback_data_replaced(df)
        return vm

    def test_composition_root_owns_range_and_extends_on_append(self):
        vm = self._vm_with_data()
        try:
            self.assertEqual((vm.playback_vm.minimum, vm.playback_vm.maximum), (100.0, 200.0))
            vm._on_playback_data_changed(pl.DataFrame({"TS": [100.0, 250.0]}))
            self.assertEqual(vm.playback_vm.maximum, 250.0)
            vm._on_playback_data_replaced(pl.DataFrame({"TS": []}, schema={"TS": pl.Float64}))
            self.assertIsNone(vm.playback_vm.minimum)
        finally:
            vm.shutdown()

    def test_plot_and_realtime_share_position_range_and_values(self):
        vm = self._vm_with_data()
        window = MainWindow(vm)
        try:
            plot, _plot_vm = window.plot_manager.open_plot_window()
            plot.show()
            plot._action_playback.setChecked(True)
            realtime = window.real_time_analysis_manager.open_window()
            self.assertEqual((vm.playback_vm.minimum, vm.playback_vm.maximum), (100.0, 200.0))
            self.assertIs(plot._playback_vm, vm.playback_vm)
            self.assertIs(realtime._playback_vm, vm.playback_vm)
            plot.vm.get_plot_data = lambda **_kw: [
                {"x": [0.0, 100.0], "y": [0.0, 10.0], "style": {"color": QColor("#ff0000")}, "name": "s", "label": "s", "visible": True}
            ]
            plot.cursor_controller._visible_only = lambda data: data
            plot.cursor_controller._format_value = lambda value, _style: f"{value:.1f}"
            plot.normalize_time = False
            vm.playback_vm.seek(150.0)
            self.assertEqual(vm.time_cursor_vm.timestamp, 150.0)
            self.assertEqual(plot.playback_bar.slider.value(), realtime.offline_position.value())
            self.assertEqual(plot.playback_bar.slider.value(), 5000)
            self.assertIn("10.0", plot.playback_bar.values_label.text())
            vm.playback_vm.set_playing(True)
            self.assertTrue(realtime.offline_play.isChecked())
            realtime.close()
            realtime.close()
            plot.close()
            plot.close()
            self.assertFalse(vm.playback_vm._timer.isActive())
        finally:
            window._close_all_secondary_windows()
            vm.shutdown()
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
