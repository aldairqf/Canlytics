from __future__ import annotations

import unittest
from unittest.mock import Mock, call, patch
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from models.analysis_context import AnalysisContext, AnalysisMarker
from models.frame_selector import FrameSelector
from models.signal import Signal
from models.mux_config import MuxConfigEntry
from viewmodels.analysis_context_viewmodel import AnalysisContextViewModel
from config.app_config import get_text
from views.plot.add_to_plot_menu import (
    analysis_send_destinations,
    make_view_signal,
    plot_send_destinations,
    show_send_to_menu,
)


class AnalysisContextTests(unittest.TestCase):
    def test_carries_id_ranges_bytes_bits_mux_and_source(self) -> None:
        context = AnalysisContext(
            can_id="18FEF100",
            byte_indices=(1, 2),
            bit_indices=(8, 9),
            time_range=(1.0, 2.0),
            range_a=(1.0, 2.0),
            range_b=(3.0, 4.0),
            mux_case=2,
            source_window="Range Diff",
        )
        self.assertEqual(context.can_id, "18FEF100")
        self.assertEqual(context.range_b, (3.0, 4.0))
        self.assertEqual(context.mux_case, 2)

    def test_rejects_invalid_byte_and_time_ranges(self) -> None:
        with self.assertRaises(ValueError):
            AnalysisContext(byte_indices=(8,))
        with self.assertRaises(ValueError):
            AnalysisContext(time_range=(2.0, 1.0))

    def test_validates_suggested_scale_and_offset(self) -> None:
        context = AnalysisContext(suggested_scale=0.5, suggested_offset=-3)
        self.assertEqual(context.suggested_scale, 0.5)
        self.assertEqual(context.suggested_offset, -3.0)
        with self.assertRaisesRegex(ValueError, "suggested_scale"):
            AnalysisContext(suggested_scale=float("inf"))

    def test_copies_mutable_sequences_into_immutable_tuples(self) -> None:
        byte_indices = [1, 2]
        time_range = [1.0, 2.0]
        context = AnalysisContext(byte_indices=byte_indices, time_range=time_range)
        byte_indices.append(3)
        time_range[0] = 0.0
        self.assertEqual(context.byte_indices, (1, 2))
        self.assertEqual(context.time_range, (1.0, 2.0))

    def test_copies_marker_dicts_into_immutable_marker_values(self) -> None:
        marker = {"sequence": 1, "name": "engine on", "timestamp": 2.5}
        context = AnalysisContext(markers=(marker,))

        marker["name"] = "changed"

        self.assertEqual(context.markers[0].name, "engine on")
        with self.assertRaises(AttributeError):
            context.markers[0].name = "changed"

    def test_from_signal_respects_little_and_motorola_bit_order(self) -> None:
        little = AnalysisContext.from_signal(
            can_id="123", start_bit=6, length=4, little_endian=True, source_window="Plot"
        )
        motorola = AnalysisContext.from_signal(
            can_id="123", start_bit=6, length=4, little_endian=False, source_window="Candidate"
        )
        self.assertEqual(little.bit_indices, (6, 7, 8, 9))
        self.assertEqual(little.byte_indices, (0, 1))
        self.assertEqual(motorola.bit_indices, (6, 5, 4, 3))
        self.assertEqual(motorola.byte_indices, (0,))

    def test_from_signal_carries_scale_and_offset_suggestions(self) -> None:
        context = AnalysisContext.from_signal(
            can_id="123",
            start_bit=0,
            length=8,
            little_endian=True,
            source_window="Reference Correlation",
            suggested_scale=2.5,
            suggested_offset=4.0,
        )
        self.assertEqual((context.suggested_scale, context.suggested_offset), (2.5, 4.0))

    def test_suggested_signal_geometry_uses_bit_and_byte_evidence(self) -> None:
        little = AnalysisContext(bit_indices=(6, 7, 8, 9))
        motorola = AnalysisContext(bit_indices=(6, 5, 4, 3))
        byte_range = AnalysisContext(byte_indices=(2, 3))

        self.assertEqual(little.suggested_signal_geometry(), (6, 4, True))
        self.assertEqual(motorola.suggested_signal_geometry(), (6, 4, False))
        self.assertEqual(byte_range.suggested_signal_geometry(), (16, 16, True))


class AnalysisContextViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_send_to_uses_explicit_context_and_publishes_destination(self) -> None:
        vm = AnalysisContextViewModel()
        context = AnalysisContext(can_id="123", source_window="Table")
        changed = Mock()
        sent = Mock()
        vm.context_changed.connect(changed)
        vm.send_requested.connect(sent)

        vm.send_to("plot", context)

        self.assertIs(vm.context, context)
        changed.assert_called_once_with(context)
        sent.assert_called_once_with("plot", context)

    def test_send_to_without_any_context_is_noop(self) -> None:
        vm = AnalysisContextViewModel()
        sent = Mock()
        vm.send_requested.connect(sent)
        vm.send_to("plot")
        sent.assert_not_called()

    def test_shared_destinations_dispatch_context_and_enable_working_dbc_with_can_id(self) -> None:
        vm = AnalysisContextViewModel()
        context = AnalysisContext(can_id="123", source_window="Table")
        sent = Mock()
        vm.send_requested.connect(sent)
        destinations = analysis_send_destinations(vm, context)

        destinations[get_text("analysis_send_candidate")].callback()

        sent.assert_called_once_with("candidate", context)
        self.assertTrue(destinations[get_text("analysis_send_working_dbc")].enabled)
        self.assertFalse(destinations[get_text("analysis_send_realtime")].enabled)

        live_destinations = analysis_send_destinations(vm, context, realtime_enabled=True)
        self.assertTrue(live_destinations[get_text("analysis_send_realtime")].enabled)
        live_destinations[get_text("analysis_send_working_dbc")].callback()
        sent.assert_called_with("working_dbc", context)

        no_id = analysis_send_destinations(vm, AnalysisContext())
        self.assertFalse(no_id[get_text("analysis_send_working_dbc")].enabled)

    def test_plugin_actions_receive_immutable_session_markers(self) -> None:
        vm = AnalysisContextViewModel()
        vm.set_marker_provider(
            lambda: ({"sequence": 1, "name": "engine on", "timestamp": 2.5},)
        )
        action = Mock()
        vm.set_plugin_actions({"inspect": action}, {"annotate": action})
        context = AnalysisContext(can_id="123")

        vm.plugin_send_actions(context)["inspect"]()
        received = action.call_args.args[0]

        self.assertEqual(received.markers[0].name, "engine on")
        with self.assertRaises(AttributeError):
            received.markers[0].timestamp = 4.0

    def test_event_and_mcp_markers_are_combined_in_handoff_context(self) -> None:
        vm = AnalysisContextViewModel()
        vm.set_event_marker_provider(
            lambda: ({"sequence": 1, "name": "lift", "timestamp": 2.0, "state": "ON"},)
        )
        vm.set_marker_provider(
            lambda: ({"sequence": 1, "name": "mcp note", "timestamp": 3.0},)
        )
        action = Mock()
        vm.set_plugin_actions({"inspect": action}, {})

        vm.plugin_send_actions(AnalysisContext(can_id="123"))["inspect"]()

        markers = action.call_args.args[0].markers
        self.assertEqual([marker.name for marker in markers], ["lift", "mcp note"])
        self.assertEqual(markers[0].state, "ON")

    def test_session_markers_are_added_to_context_that_already_has_markers(self) -> None:
        vm = AnalysisContextViewModel()
        vm.set_event_marker_provider(lambda: ({
            "sequence": 1, "name": "event", "timestamp": 2.0, "state": "ON",
        },))
        context = AnalysisContext(markers=(AnalysisMarker(1, "existing", 1.0),))
        received = []
        vm.set_plugin_actions({"capture": lambda value: received.append(value)}, {})
        vm.plugin_send_actions(context)["capture"]()
        markers = received[0].markers
        self.assertEqual([marker.name for marker in markers], ["existing", "event"])
        self.assertEqual([marker.sequence for marker in markers], [1, 2])


class SendToMenuTests(unittest.TestCase):
    def test_only_selected_destination_runs(self) -> None:
        parent = Mock()
        first = Mock()
        second = Mock()
        selected = object()
        menu = Mock()
        menu.addAction.side_effect = [object(), selected]
        menu.exec.return_value = selected

        with patch("views.plot.add_to_plot_menu.QMenu", return_value=menu):
            show_send_to_menu(parent, (0, 0), {"Plot": first, "Candidate": second})

        first.assert_not_called()
        second.assert_called_once_with()

    def test_plot_destination_publishes_signal_context_before_sending(self) -> None:
        context_vm = AnalysisContextViewModel()
        plot_manager = Mock()
        view_signal = make_view_signal(
            Signal(name="Speed", can_id="123", start_bit=8, length=16),
            FrameSelector(selected_id="123"),
        )
        destinations = plot_send_destinations(
            plot_manager,
            lambda: view_signal,
            analysis_context_vm=context_vm,
            source_window="Table",
        )

        destinations["Add last graph"]()

        self.assertEqual(context_vm.context.can_id, "123")
        self.assertEqual(context_vm.context.byte_indices, (1, 2))
        self.assertEqual(context_vm.context.bit_indices, tuple(range(8, 24)))
        self.assertEqual(context_vm.context.source_window, "Table")
        plot_manager.add_view_signal.assert_called_once_with(view_signal, use_last=True)

    def test_plot_destinations_accept_analyze_labels_and_configuration_action(self) -> None:
        plot_manager = Mock()
        view_signal = make_view_signal(
            Signal(name="123.B2", can_id="123", start_bit=16, length=8),
            FrameSelector(selected_id="123", mode="exact"),
        )
        configure = Mock()
        destinations = plot_send_destinations(
            plot_manager,
            lambda: view_signal,
            configure_signal=configure,
            action_labels=(get_text("analysis_new_plot"), get_text("analysis_add_current_plot")),
        )

        destinations[get_text("analysis_new_plot")]()
        destinations[get_text("analysis_add_current_plot")]()
        destinations[get_text("analysis_configure_signal")]()

        self.assertEqual(plot_manager.add_view_signal.call_count, 2)
        self.assertEqual(plot_manager.add_view_signal.call_args.kwargs, {"use_last": True})
        configure.assert_called_once_with()

    def test_offscreen_analyze_menu_clicks_route_the_prefilled_byte_signal(self) -> None:
        from PySide6.QtWidgets import QWidget

        parent = QWidget()
        plot_manager = Mock()
        context_vm = AnalysisContextViewModel()
        context = AnalysisContext(
            can_id="18FEF100", byte_indices=(3,), bit_indices=tuple(range(24, 32)),
            source_window="Analyze Data",
        )
        view_signal = make_view_signal(
            Signal(name="18FEF100.B3", can_id="18FEF100", start_bit=24, length=8),
            FrameSelector(selected_id="18FEF100", mode="exact"),
        )
        destinations = plot_send_destinations(
            plot_manager,
            lambda: view_signal,
            analysis_context_vm=context_vm,
            context=context,
            configure_signal=Mock(),
            action_labels=(get_text("analysis_new_plot"), get_text("analysis_add_current_plot")),
        )
        sent = Mock()
        context_vm.send_requested.connect(sent)

        def click_action(label: str) -> None:
            menu = QApplication.activePopupWidget()
            if menu is None:
                QTimer.singleShot(10, lambda: click_action(label))
                return
            self.assertEqual(
                {action.text() for action in menu.actions()},
                {
                    get_text("analysis_new_plot"), get_text("analysis_add_current_plot"),
                    get_text("analysis_configure_signal"),
                },
            )
            action = next(a for a in menu.actions() if a.text() == label)
            QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())

        for label, use_last in (
            (get_text("analysis_new_plot"), False),
            (get_text("analysis_add_current_plot"), True),
        ):
            QTimer.singleShot(0, lambda target=label: click_action(target))
            show_send_to_menu(parent, parent.mapToGlobal(parent.rect().center()), destinations)
            self.assertEqual(plot_manager.add_view_signal.call_args.kwargs, {"use_last": use_last})

        self.assertEqual(view_signal.signal.can_id, "18FEF100")
        self.assertEqual((view_signal.signal.start_bit, view_signal.signal.length), (24, 8))
        self.assertEqual(view_signal.selector.selected_id, "18FEF100")
        self.assertEqual(context_vm.context, context)
        sent.assert_has_calls([call("plot", context)] * 2)
        self.assertEqual(plot_manager.add_view_signal.call_count, 2)
        parent.close()

    def test_signal_configuration_dialog_prefills_can_id_and_byte_geometry(self) -> None:
        import polars as pl

        from viewmodels.plot_viewmodel import PlotViewModel
        from views.signal.signal_settings_dialog import SignalSettingsDialog

        signal = make_view_signal(
            Signal(name="18FEF100.B3", can_id="18FEF100", start_bit=24, length=8),
            FrameSelector(selected_id="18FEF100", mode="exact"),
        )
        dataframe = pl.DataFrame({"ID": ["18FEF100"], "DATA": ["00000000"], "LEN": [8]})
        dialog = SignalSettingsDialog(PlotViewModel(dataframe), initial_signal=signal)

        self.assertEqual(dialog.decode_tab.id_box.currentText(), "18FEF100")
        self.assertEqual(dialog.decode_tab.start_bit.value(), 24)
        self.assertEqual(dialog.decode_tab.length.value(), 8)
        self.assertTrue(dialog.decode_tab.le.isChecked())
        from PySide6.QtWidgets import QPushButton

        button_texts = {button.text() for button in dialog.findChildren(QPushButton)}
        self.assertNotIn(get_text("delete"), button_texts)
        self.assertNotIn(get_text("duplicate"), button_texts)
        dialog.close()

    def test_single_and_multiple_bytes_keep_mux_filter(self) -> None:
        from types import SimpleNamespace

        from views.analyze_data_window import AnalyzeDataWindow

        context_vm = AnalysisContextViewModel()
        plot_manager = Mock()
        window = SimpleNamespace(
            _analysis_context_vm=context_vm,
            _real_time_analysis_manager=None,
            _plot_manager=plot_manager,
            _vm=SimpleNamespace(mux_configs=[MuxConfigEntry("123", None, (0,))]),
            mux_case=SimpleNamespace(currentText=lambda: "03"),
            _time_range_vm=None,
            _configure_signal=Mock(),
        )
        window._build_byte_view_signals = lambda can_id, byte_indices: AnalyzeDataWindow._build_byte_view_signals(
            window, can_id, byte_indices, "03"
        )
        window._mux_filter_for_selection = lambda can_id, case: AnalyzeDataWindow._mux_filter_for_selection(
            window, can_id, case
        )
        window._send_selected_bytes_to_plot = lambda context, signals, use_last: (
            AnalyzeDataWindow._send_selected_bytes_to_plot(window, context, signals, use_last=use_last)
        )
        context = AnalysisContext(can_id="123", byte_indices=(2, 3), mux_case="03")

        for byte_indices in ((2,), (2, 3)):
            plot_manager.reset_mock()
            destinations = AnalyzeDataWindow._send_destinations(
                window, context, window._build_byte_view_signals("123", byte_indices)
            )
            destinations[get_text("analysis_new_plot")]()
            signals = [call.args[0] for call in plot_manager.add_view_signal.call_args_list]
            self.assertEqual([signal.signal.start_bit for signal in signals], [index * 8 for index in byte_indices])
            self.assertEqual(
                [
                    (signal.signal.mux_start, signal.signal.mux_bytes, signal.signal.mux_value)
                    for signal in signals
                ],
                [(0, 1, 3)] * len(byte_indices),
            )

    def test_analyze_plot_destinations_are_absent_without_plot_manager(self) -> None:
        from types import SimpleNamespace

        from views.analyze_data_window import AnalyzeDataWindow

        context = AnalysisContext(can_id="123", byte_indices=(2, 3))
        window = SimpleNamespace(
            _analysis_context_vm=AnalysisContextViewModel(),
            _real_time_analysis_manager=None,
            _plot_manager=None,
            _configure_signal=Mock(),
        )
        destinations = AnalyzeDataWindow._send_destinations(
            window,
            context,
            [make_view_signal(
                Signal(name="123.B2", can_id="123", start_bit=16, length=8),
                FrameSelector(selected_id="123", mode="exact"),
            ), make_view_signal(
                Signal(name="123.B3", can_id="123", start_bit=24, length=8),
                FrameSelector(selected_id="123", mode="exact"),
            )],
        )

        self.assertNotIn(get_text("analysis_new_plot"), destinations)
        self.assertNotIn(get_text("analysis_add_current_plot"), destinations)
        self.assertNotIn(get_text("analysis_configure_signal"), destinations)

    def test_series_hit_test_ignores_empty_space_between_curve_samples(self) -> None:
        from types import SimpleNamespace

        from PySide6.QtCore import QPointF
        from services.analyze_data import ByteSeries
        from views.analyze_data_window import AnalyzeDataWindow

        series_b0 = ByteSeries("B0", [0.0, 100.0], [0, 255], "red")
        series_b1 = ByteSeries("B1", [0.0, 100.0], [20, 20], "blue")
        viewbox = SimpleNamespace(mapViewToScene=lambda point: QPointF(point.x(), point.y()))
        window = SimpleNamespace(
            _plot_series={object(): series_b0, object(): series_b1},
            plot=SimpleNamespace(getViewBox=lambda: viewbox),
        )

        hit = AnalyzeDataWindow._find_hit_series(window, QPointF(50.0, 200.0))

        self.assertIsNone(hit)

    def test_series_hit_test_uses_distance_to_curve_segment(self) -> None:
        from types import SimpleNamespace

        from PySide6.QtCore import QPointF
        from services.analyze_data import ByteSeries
        from views.analyze_data_window import AnalyzeDataWindow

        series = ByteSeries("B0", [0.0, 100.0], [0, 100], "red")
        viewbox = SimpleNamespace(mapViewToScene=lambda point: QPointF(point.x(), point.y()))
        window = SimpleNamespace(
            _plot_series={object(): series},
            plot=SimpleNamespace(getViewBox=lambda: viewbox),
        )

        self.assertIs(AnalyzeDataWindow._find_hit_series(window, QPointF(50.0, 50.0)), series)
        self.assertIsNone(AnalyzeDataWindow._find_hit_series(window, QPointF(50.0, 65.0)))

    def test_configure_signal_cancel_does_not_open_plot_or_publish_context(self) -> None:
        from types import SimpleNamespace

        from views.analyze_data_window import AnalyzeDataWindow

        context_vm = AnalysisContextViewModel()
        plot_manager = Mock()
        dialog = Mock()
        dialog.exec.return_value = 0
        plot_manager.create_signal_settings_dialog.return_value = dialog
        window = SimpleNamespace(_analysis_context_vm=context_vm, _plot_manager=plot_manager)
        signal = make_view_signal(
            Signal(name="123.B2", can_id="123", start_bit=16, length=8),
            FrameSelector(selected_id="123", mode="exact"),
        )
        context = AnalysisContext(can_id="123", byte_indices=(2,), source_window="Analyze Data")

        AnalyzeDataWindow._configure_signal(window, signal, context)

        plot_manager.create_signal_settings_dialog.assert_called_once_with(signal, window)
        dialog.exec.assert_called_once_with()
        plot_manager.open_plot_window.assert_not_called()
        plot_manager.add_view_signal.assert_not_called()
        self.assertIsNone(context_vm.context)

    def test_configure_signal_accept_publishes_then_resolves_plot(self) -> None:
        from types import SimpleNamespace

        from views.analyze_data_window import AnalyzeDataWindow

        context_vm = AnalysisContextViewModel()
        plot_manager = Mock()
        dialog = Mock()
        dialog.exec.return_value = 1
        configured = make_view_signal(
            Signal(name="123.B2", can_id="123", start_bit=16, length=8),
            FrameSelector(selected_id="123", mode="exact"),
        )
        dialog.get_signal.return_value = configured
        plot_manager.create_signal_settings_dialog.return_value = dialog
        window = SimpleNamespace(_analysis_context_vm=context_vm, _plot_manager=plot_manager)
        context = AnalysisContext(can_id="123", byte_indices=(2,), source_window="Analyze Data")

        AnalyzeDataWindow._configure_signal(window, configured, context)

        self.assertEqual(context_vm.context, context)
        plot_manager.add_view_signal.assert_called_once_with(configured, use_last=True)
        plot_manager.open_plot_window.assert_not_called()

    def test_context_selection_uses_current_group_or_only_unselected_clicked_byte(self) -> None:
        from views.analyze_data_window import AnalyzeDataWindow

        self.assertEqual(AnalyzeDataWindow._context_byte_indices(3, {2, 3, 4}), (2, 3, 4))
        self.assertEqual(AnalyzeDataWindow._context_byte_indices(5, {2, 3, 4}), (5,))

    def test_empty_space_plot_context_uses_selected_bytes(self) -> None:
        from types import SimpleNamespace

        from PySide6.QtCore import QPointF
        from views.analyze_data_window import AnalyzeDataWindow

        window = SimpleNamespace(_vm=SimpleNamespace(selected_id="123", selected_bytes={0, 2}))
        window._find_hit_series = lambda _pos: None

        self.assertEqual(
            AnalyzeDataWindow._plot_selection_for_position(window, QPointF(30, 200)),
            ("123", (0, 2)),
        )

    def test_context_signal_geometry_covers_all_selected_contiguous_bytes(self) -> None:
        context = AnalysisContext(can_id="123", byte_indices=(3, 4), mux_case="03")

        self.assertEqual(context.suggested_signal_geometry(), (24, 16, True))

    def test_configuration_signal_uses_whole_selection_geometry_and_mux_filter(self) -> None:
        from types import SimpleNamespace

        from views.analyze_data_window import AnalyzeDataWindow

        window = SimpleNamespace(_vm=SimpleNamespace(mux_configs=[MuxConfigEntry("123", None, (0,))]))
        window._mux_filter_for_selection = lambda can_id, case: AnalyzeDataWindow._mux_filter_for_selection(
            window, can_id, case
        )
        context = AnalysisContext(can_id="123", byte_indices=(3, 4), mux_case="03")

        view_signal = AnalyzeDataWindow._build_configuration_view_signal(window, context)

        self.assertEqual((view_signal.signal.start_bit, view_signal.signal.length, view_signal.signal.le), (24, 16, True))
        self.assertEqual(
            (view_signal.signal.mux_start, view_signal.signal.mux_bytes, view_signal.signal.mux_value),
            (0, 1, 3),
        )

    def test_plot_context_menu_extends_native_menu(self) -> None:
        import pyqtgraph as pg

        from views.analyze_data_window import AnalyzeDataWindow

        plot = pg.PlotWidget()
        native_menu = plot.getPlotItem().getViewBox().menu
        before = len(native_menu.actions())

        analyze_menu = AnalyzeDataWindow._extend_plot_context_menu(plot)

        self.assertGreaterEqual(len(native_menu.actions()), before + 1)
        self.assertIs(analyze_menu.parent(), native_menu)
        self.assertIsNotNone(plot.getPlotItem().getViewBox().menu)
        plot.close()

    def test_byte_widgets_route_context_requests_to_shared_menu_handlers(self) -> None:
        from types import SimpleNamespace

        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QCheckBox, QFrame
        from views.analyze_data_window import AnalyzeDataWindow

        byte_handler = Mock()
        matrix_handler = Mock()
        window = SimpleNamespace(
            _open_byte_context_menu=byte_handler,
            _show_bytes_context_menu=matrix_handler,
        )
        checkbox = QCheckBox("B2")
        cell = QFrame()

        AnalyzeDataWindow._wire_byte_context_menu(window, checkbox, 2)
        AnalyzeDataWindow._wire_matrix_cell_context_menu(window, cell, "123", 4)
        checkbox.customContextMenuRequested.emit(QPoint(1, 1))
        cell.customContextMenuRequested.emit(QPoint(1, 1))

        byte_handler.assert_called_once()
        self.assertEqual(byte_handler.call_args.args[0], 2)
        matrix_handler.assert_called_once()
        self.assertEqual(matrix_handler.call_args.args[:2], ("123", (4,)))


if __name__ == "__main__":
    unittest.main()
