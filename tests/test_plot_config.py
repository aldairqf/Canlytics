"""Characterization tests for services/plot_config.py.

Was viewmodels/plot_viewmodel.py's .conf version-migration (v1/v2+ signal and
selector construction) and MUX value parsing/validation -- pure, Qt-free
domain logic moved out of the ViewModel.
"""

from __future__ import annotations

import unittest

from models.derived_signal import DerivedSignal
from models.frame_selector import FrameSelector
from models.signal import Signal
from services.plot_config import (
    build_derived_signal_from_dict,
    build_selector_from_v1_dict,
    build_selector_from_v2_dict,
    build_signal_from_dict,
    maybe_int,
    parse_signal_data,
)


class MaybeIntTests(unittest.TestCase):
    def test_parses_valid_int(self):
        self.assertEqual(maybe_int("5"), 5)
        self.assertEqual(maybe_int(5), 5)

    def test_none_returns_none(self):
        self.assertIsNone(maybe_int(None))

    def test_invalid_returns_none_instead_of_raising(self):
        self.assertIsNone(maybe_int("abc"))


class BuildSignalFromDictTests(unittest.TestCase):
    def test_maps_all_fields(self):
        s = build_signal_from_dict(
            {
                "can_id": "100", "start_bit": 8, "length": 16, "le": False,
                "scale": 2.0, "offset": -40.0, "mux_start": 1, "mux_bytes": 1,
                "mux_value": "2", "type_data": "int",
            },
            name="Foo",
        )
        self.assertIsInstance(s, Signal)
        self.assertEqual(s.name, "Foo")
        self.assertEqual(s.can_id, "100")
        self.assertEqual(s.start_bit, 8)
        self.assertEqual(s.length, 16)
        self.assertFalse(s.le)
        self.assertEqual(s.scale, 2.0)
        self.assertEqual(s.offset, -40.0)
        self.assertEqual(s.mux_start, 1)
        self.assertEqual(s.mux_bytes, 1)
        self.assertEqual(s.mux_value, 2)
        self.assertEqual(s.type_data, "int")

    def test_defaults_when_fields_missing(self):
        s = build_signal_from_dict({}, name="Bare")
        self.assertIsNone(s.can_id)
        self.assertEqual(s.start_bit, 0)
        self.assertEqual(s.length, 8)
        self.assertTrue(s.le)
        self.assertEqual(s.scale, 1.0)
        self.assertEqual(s.offset, 0.0)
        self.assertEqual(s.type_data, "uint")
        self.assertIsNone(s.mux_value)

    def test_same_field_names_work_for_v1_flat_and_v2_nested_data(self):
        # build_signal_from_dict doesn't care whether the caller passed a
        # whole v1 item or a v2 item["signal"] sub-dict -- same field names.
        flat = build_signal_from_dict({"can_id": "1", "length": 16}, name="A")
        nested = build_signal_from_dict({"can_id": "1", "length": 16}, name="A")
        self.assertEqual(flat, nested)


class BuildSelectorFromV2DictTests(unittest.TestCase):
    def test_uses_selected_id_when_present(self):
        sel = build_selector_from_v2_dict({"selected_id": "200", "mode": "j1939"}, fallback_can_id="100")
        self.assertEqual(sel.selected_id, "200")
        self.assertEqual(sel.mode, "j1939")

    def test_falls_back_to_can_id_when_selected_id_missing(self):
        sel = build_selector_from_v2_dict({}, fallback_can_id="100")
        self.assertEqual(sel.selected_id, "100")
        self.assertEqual(sel.mode, "exact")

    def test_pgn_and_target_id_pass_through(self):
        sel = build_selector_from_v2_dict({"pgn": "0xFF00", "target_id": "300"}, fallback_can_id=None)
        self.assertEqual(sel.pgn, "0xFF00")
        self.assertEqual(sel.target_id, "300")


class BuildSelectorFromV1DictTests(unittest.TestCase):
    def test_valid_mode_is_kept(self):
        sel = build_selector_from_v1_dict({"id_match": "j1939"}, can_id="100")
        self.assertEqual(sel.mode, "j1939")

    def test_invalid_mode_falls_back_to_exact(self):
        sel = build_selector_from_v1_dict({"id_match": "bogus"}, can_id="100")
        self.assertEqual(sel.mode, "exact")

    def test_target_id_always_none(self):
        # v1 configs never had a separate target_id concept.
        sel = build_selector_from_v1_dict({"id_match": "exact"}, can_id="100")
        self.assertIsNone(sel.target_id)

    def test_selected_id_comes_from_can_id_argument(self):
        sel = build_selector_from_v1_dict({}, can_id="100")
        self.assertEqual(sel.selected_id, "100")


class BuildDerivedSignalFromDictTests(unittest.TestCase):
    def test_maps_all_fields(self):
        ds = build_derived_signal_from_dict(
            {"formula": "result = y", "inputs": ["A", "B"], "simple_config": {"x": 1}},
            name="Derived1",
        )
        self.assertIsInstance(ds, DerivedSignal)
        self.assertEqual(ds.name, "Derived1")
        self.assertEqual(ds.formula, "result = y")
        self.assertEqual(ds.inputs, ["A", "B"])
        self.assertEqual(ds.simple_config, {"x": 1})

    def test_defaults_when_fields_missing(self):
        ds = build_derived_signal_from_dict({}, name="Bare")
        self.assertEqual(ds.formula, "")
        self.assertEqual(ds.inputs, [])
        self.assertIsNone(ds.simple_config)


class ParseSignalDataTests(unittest.TestCase):
    def test_v2_nested_shape_is_passed_through(self):
        data = {"signal": {"name": "X", "can_id": "100"}, "selector": {"selected_id": "100", "mode": "j1939"}}
        parsed = parse_signal_data(data)
        self.assertEqual(parsed["signal"]["name"], "X")
        self.assertEqual(parsed["selector"]["mode"], "j1939")

    def test_flat_legacy_shape_is_normalized(self):
        data = {"name": "X", "can_id": "100", "id_match": "j1939", "pgn": "0xFF00"}
        parsed = parse_signal_data(data)
        self.assertEqual(parsed["signal"]["name"], "X")
        self.assertEqual(parsed["signal"]["can_id"], "100")
        self.assertEqual(parsed["selector"]["selected_id"], "100")
        self.assertEqual(parsed["selector"]["mode"], "j1939")
        self.assertEqual(parsed["selector"]["pgn"], "0xFF00")

    def test_hex_mux_value_is_parsed(self):
        parsed = parse_signal_data({"mux_value": "0x10", "mux_bytes": 1})
        self.assertEqual(parsed["signal"]["mux_value"], 16)

    def test_decimal_mux_value_is_parsed(self):
        parsed = parse_signal_data({"mux_value": "10", "mux_bytes": 1})
        self.assertEqual(parsed["signal"]["mux_value"], 10)

    def test_empty_mux_value_is_none(self):
        parsed = parse_signal_data({"mux_value": "", "mux_bytes": 1})
        self.assertIsNone(parsed["signal"]["mux_value"])

    def test_mux_value_overflowing_mux_bytes_raises(self):
        with self.assertRaises(ValueError):
            parse_signal_data({"mux_value": "999", "mux_bytes": 1})

    def test_mux_value_within_range_does_not_raise(self):
        parsed = parse_signal_data({"mux_value": "255", "mux_bytes": 1})
        self.assertEqual(parsed["signal"]["mux_value"], 255)

    def test_defaults_are_applied(self):
        parsed = parse_signal_data({})
        self.assertEqual(parsed["signal"]["type_data"], "uint")
        self.assertIsNone(parsed["signal"]["can_id"])
        self.assertEqual(parsed["selector"]["mode"], "exact")
        self.assertIsNone(parsed["selector"]["pgn"])


if __name__ == "__main__":
    unittest.main()
