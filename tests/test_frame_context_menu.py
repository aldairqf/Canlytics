from __future__ import annotations

import unittest

from views.table.frame_context_menu import build_byte_view_signal, format_copied_frame


class FrameContextMenuDataTests(unittest.TestCase):
    def test_copied_frame_contains_bus_id_and_normalized_payload(self) -> None:
        self.assertEqual(
            format_copied_frame({"Bus": "can0", "ID": "123", "DATA": "00 a1"}),
            "can0 123#00A1",
        )

    def test_copied_zero_length_frame_keeps_empty_payload(self) -> None:
        self.assertEqual(
            format_copied_frame({"Bus": "can0", "ID": "123", "DATA": ""}),
            "can0 123#",
        )

    def test_byte_signal_uses_exact_id_and_eight_bit_offset(self) -> None:
        view_signal = build_byte_view_signal("18FEF100", 3)

        self.assertEqual(view_signal.signal.name, "18FEF100.B3")
        self.assertEqual(view_signal.signal.can_id, "18FEF100")
        self.assertEqual(view_signal.signal.start_bit, 24)
        self.assertEqual(view_signal.signal.length, 8)
        self.assertEqual(view_signal.selector.selected_id, "18FEF100")
        self.assertEqual(view_signal.selector.mode, "exact")


if __name__ == "__main__":
    unittest.main()
