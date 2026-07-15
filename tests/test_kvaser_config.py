"""Characterization tests for services/kvaser_config pure helpers."""

from __future__ import annotations

import unittest

from services.kvaser_config import (
    _build_kvaser_bus_kwargs,
    _coerce_scalar,
    _is_kvaser_backend,
    _is_virtual_kvaser_config,
    _validate_kvaser_channel_available,
    bitrate_probe_order,
    parse_kvaser_kwargs,
)


class _FakeCan:
    def __init__(self, configs=None, raises=False):
        self._configs = configs
        self._raises = raises

    def detect_available_configs(self, interfaces=None):
        if self._raises:
            raise RuntimeError("detection unavailable")
        return self._configs


class CoerceScalarTests(unittest.TestCase):
    def test_keywords_and_numbers(self):
        self.assertIs(_coerce_scalar("true"), True)
        self.assertIs(_coerce_scalar("false"), False)
        self.assertIsNone(_coerce_scalar("none"))
        self.assertEqual(_coerce_scalar("5"), 5)
        self.assertEqual(_coerce_scalar("1.5"), 1.5)
        self.assertEqual(_coerce_scalar("[1, 2]"), [1, 2])

    def test_plain_text_and_passthrough(self):
        self.assertEqual(_coerce_scalar("hello"), "hello")
        self.assertEqual(_coerce_scalar(""), "")
        self.assertEqual(_coerce_scalar(7), 7)


class ParseKvaserKwargsTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(parse_kvaser_kwargs(""), {})

    def test_mixed_values(self):
        self.assertEqual(
            parse_kvaser_kwargs("a=1, b=true, c=hello"),
            {"a": 1, "b": True, "c": "hello"},
        )

    def test_missing_equals_raises(self):
        with self.assertRaises(ValueError):
            parse_kvaser_kwargs("oops")

    def test_empty_key_raises(self):
        with self.assertRaises(ValueError):
            parse_kvaser_kwargs("=1")


class BuildBusKwargsTests(unittest.TestCase):
    def test_minimal(self):
        self.assertEqual(
            _build_kvaser_bus_kwargs(interface="kvaser", channel="", bitrate=None, extra_kwargs={}),
            {"interface": "kvaser"},
        )

    def test_full(self):
        self.assertEqual(
            _build_kvaser_bus_kwargs(interface="kvaser", channel="0", bitrate=250000, extra_kwargs={"fd": True}),
            {"interface": "kvaser", "channel": "0", "bitrate": 250000, "fd": True},
        )


class BitrateProbeOrderTests(unittest.TestCase):
    def test_priority_bitrates_come_first(self):
        result = bitrate_probe_order([10000, 20000, 250000, 500000, 1000000])
        self.assertEqual(result[:2], [250000, 500000])

    def test_preserves_relative_order_of_the_rest(self):
        result = bitrate_probe_order([10000, 20000, 250000, 500000, 1000000])
        self.assertEqual(result, [250000, 500000, 10000, 20000, 1000000])

    def test_missing_priority_values_are_skipped(self):
        result = bitrate_probe_order([10000, 20000])
        self.assertEqual(result, [10000, 20000])

    def test_no_duplicates(self):
        result = bitrate_probe_order([250000, 250000, 500000])
        self.assertEqual(result, [250000, 500000])

    def test_empty_input_returns_empty(self):
        self.assertEqual(bitrate_probe_order([]), [])


class BackendHelperTests(unittest.TestCase):
    def test_is_kvaser_backend(self):
        self.assertTrue(_is_kvaser_backend("kvaser"))
        self.assertTrue(_is_kvaser_backend("  KVASER  "))
        self.assertFalse(_is_kvaser_backend("j2534"))

    def test_is_virtual_kvaser_config(self):
        self.assertTrue(_is_virtual_kvaser_config({"device_name": "Kvaser Virtual CAN", "serial": 123}))
        self.assertTrue(_is_virtual_kvaser_config({"device_name": "Leaf", "serial": 0}))
        self.assertFalse(_is_virtual_kvaser_config({"device_name": "Leaf", "serial": 123}))


class ValidateChannelTests(unittest.TestCase):
    def test_no_devices_raises(self):
        with self.assertRaises(RuntimeError):
            _validate_kvaser_channel_available(_FakeCan(configs=[]), "0")

    def test_only_virtual_raises(self):
        configs = [{"device_name": "Kvaser Virtual", "serial": 0, "channel": 0}]
        with self.assertRaises(RuntimeError):
            _validate_kvaser_channel_available(_FakeCan(configs=configs), "0")

    def test_physical_channel_ok(self):
        configs = [{"device_name": "Leaf", "serial": 123, "channel": 0}]
        # channel "0" present -> no raise
        _validate_kvaser_channel_available(_FakeCan(configs=configs), "0")

    def test_physical_channel_missing_raises(self):
        configs = [{"device_name": "Leaf", "serial": 123, "channel": 0}]
        with self.assertRaises(RuntimeError):
            _validate_kvaser_channel_available(_FakeCan(configs=configs), "5")

    def test_detection_failure_is_silent(self):
        # detection raising -> keep default behavior (no raise)
        _validate_kvaser_channel_available(_FakeCan(raises=True), "0")


if __name__ == "__main__":
    unittest.main()
