from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication

from models.analysis_context import AnalysisContext
from models.frame_selector import FrameSelector
from models.signal import Signal
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
        cls.app = QCoreApplication.instance() or QCoreApplication([])

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


if __name__ == "__main__":
    unittest.main()
