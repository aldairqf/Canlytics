from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from config.app_config import get_text
from views.candidate_constraint_search import _time_label
from views.signal.pipeline_builder import _SourceRow, _TransformRow


class FlowTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def test_constraint_search_time_labels_use_configured_text(self) -> None:
        self.assertEqual(_time_label("none"), get_text("constraint_search_time_elapsed"))
        self.assertEqual(
            _time_label("UTC"),
            get_text("constraint_search_time_clock").format(timezone="UTC"),
        )

    def test_pipeline_source_labels_preserve_internal_values(self) -> None:
        row = _SourceRow(["Speed"], ["123"], [], removable=True)
        self.assertEqual(row._kind_combo.itemText(0), get_text("pipeline_source_signal"))
        self.assertEqual(row._kind_combo.itemData(0), "signal")
        self.assertEqual(row._kind_combo.itemData(1), "raw_field")
        self.assertEqual(row._raw_byte_order.itemText(0), get_text("pipeline_little_endian"))
        self.assertEqual(row._raw_byte_order.itemData(0), "LE")
        self.assertEqual(row._raw_type.itemData(0), "uint")
        self.assertEqual(row._raw_type.itemData(1), "int")
        self.assertEqual(row._raw_type.itemData(2), "float32")
        row.close()

    def test_pipeline_transform_labels_preserve_operation_values(self) -> None:
        row = _TransformRow("scale")
        self.assertEqual(row._op_combo.itemText(0), get_text("pipeline_transform_scale"))
        self.assertEqual(row._op_combo.itemData(0), "scale")
        self.assertEqual(row._op_combo.itemData(1), "offset")
        self.assertEqual(row._math_fn.itemData(0), "sqrt")
        row.close()


if __name__ == "__main__":
    unittest.main()
