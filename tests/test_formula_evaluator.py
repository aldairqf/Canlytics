"""Characterization tests for services/formula_evaluator.py and
services/formula_context.py.

These tests cover: safe exec, result extraction, dtype decoding, sandbox
escape attempts, and the helpers exposed to formula scripts.
"""

from __future__ import annotations

import unittest

import numpy as np

from services.formula_context import build_formula_context, decode_bytes
from services.formula_evaluator import FormulaError, evaluate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(decoded: dict | None = None):
    """Minimal context backed by an empty DataFrame."""
    import polars as pl
    return build_formula_context(pl.DataFrame(), decoded or {})


# ---------------------------------------------------------------------------
# formula_evaluator — basic result shapes
# ---------------------------------------------------------------------------

class EvaluateBasicTests(unittest.TestCase):
    def test_tuple_result(self):
        formula = "result = (np.array([1.0, 2.0]), np.array([10.0, 20.0]))"
        ts, y = evaluate(formula, _ctx())
        np.testing.assert_array_equal(ts, [1.0, 2.0])
        np.testing.assert_array_equal(y, [10.0, 20.0])

    def test_single_array_result(self):
        formula = "result = np.array([5.0, 6.0, 7.0])"
        ts, y = evaluate(formula, _ctx())
        self.assertEqual(len(ts), 0)
        np.testing.assert_array_equal(y, [5.0, 6.0, 7.0])

    def test_multiline_formula(self):
        formula = (
            "a = np.array([1.0, 2.0, 3.0])\n"
            "b = a * 2\n"
            "result = (np.array([0.0, 1.0, 2.0]), b)\n"
        )
        ts, y = evaluate(formula, _ctx())
        np.testing.assert_array_equal(y, [2.0, 4.0, 6.0])

    def test_numpy_where_conditional(self):
        formula = (
            "y = np.array([100.0, 200.0, 300.0])\n"
            "out = np.where(y > 180, y * 2 - 50, y)\n"
            "result = (np.array([0.0, 1.0, 2.0]), out)\n"
        )
        ts, y = evaluate(formula, _ctx())
        np.testing.assert_array_equal(y, [100.0, 350.0, 550.0])


# ---------------------------------------------------------------------------
# formula_evaluator — error cases
# ---------------------------------------------------------------------------

class EvaluateErrorTests(unittest.TestCase):
    def test_missing_result_raises(self):
        with self.assertRaises(FormulaError) as ctx:
            evaluate("x = 1", _ctx())
        self.assertIn("result", str(ctx.exception))

    def test_empty_formula_raises(self):
        with self.assertRaises(FormulaError):
            evaluate("", _ctx())

    def test_syntax_error_raises(self):
        with self.assertRaises(FormulaError):
            evaluate("result = (np.array([", _ctx())

    def test_runtime_error_raises(self):
        with self.assertRaises(FormulaError):
            evaluate("result = 1 / 0", _ctx())

    def test_mismatched_ts_y_raises(self):
        formula = "result = (np.array([1.0, 2.0]), np.array([1.0]))"
        with self.assertRaises(FormulaError):
            evaluate(formula, _ctx())


# ---------------------------------------------------------------------------
# formula_evaluator — sandbox escape attempts
# ---------------------------------------------------------------------------

class SandboxTests(unittest.TestCase):
    def test_import_blocked(self):
        with self.assertRaises(FormulaError):
            evaluate("import os; result = os.getcwd()", _ctx())

    def test_open_blocked(self):
        with self.assertRaises(FormulaError):
            evaluate("result = open('x')", _ctx())

    def test_dunder_import_blocked(self):
        with self.assertRaises(FormulaError):
            evaluate("result = __import__('os')", _ctx())

    def test_builtins_not_available(self):
        # print is not in namespace; it shouldn't crash but result must be set
        with self.assertRaises(FormulaError):
            evaluate("print('hello'); result = np.array([1])", _ctx())


# ---------------------------------------------------------------------------
# formula_context — signal() helper
# ---------------------------------------------------------------------------

class SignalHelperTests(unittest.TestCase):
    def test_signal_returns_decoded(self):
        ts = np.array([0.0, 1.0])
        y = np.array([5.0, 10.0])
        ctx = _ctx({"rpm": (ts, y)})
        formula = "ts, vals = signal('rpm'); result = (ts, vals * 3.6)"
        out_ts, out_y = evaluate(formula, ctx)
        np.testing.assert_array_equal(out_ts, ts)
        np.testing.assert_array_equal(out_y, y * 3.6)

    def test_signal_missing_raises_key_error(self):
        ctx = _ctx({})
        formula = "result = signal('nonexistent')"
        with self.assertRaises(FormulaError) as cm:
            evaluate(formula, ctx)
        self.assertIn("nonexistent", str(cm.exception))


# ---------------------------------------------------------------------------
# decode_bytes — dtype coverage
# ---------------------------------------------------------------------------

class DecodeBytesTests(unittest.TestCase):
    def test_uint8(self):
        self.assertEqual(decode_bytes(b'\xFF', 0, 1, 'uint8'), 255)

    def test_int8_negative(self):
        self.assertEqual(decode_bytes(b'\x80', 0, 1, 'int8'), -128)

    def test_int16le(self):
        # 0xFFFE little-endian → -2 as int16
        data = b'\xFE\xFF'
        self.assertEqual(decode_bytes(data, 0, 2, 'int16le'), -2)

    def test_int16be(self):
        data = b'\xFF\xFE'
        self.assertEqual(decode_bytes(data, 0, 2, 'int16be'), -2)

    def test_uint32le(self):
        data = b'\x01\x00\x00\x00'
        self.assertEqual(decode_bytes(data, 0, 4, 'uint32le'), 1)

    def test_float32le(self):
        import struct
        data = struct.pack('<f', 3.14)
        val = decode_bytes(data, 0, 4, 'float32le')
        self.assertAlmostEqual(val, 3.14, places=5)

    def test_offset(self):
        data = b'\x00\x00\xFE\xFF'
        self.assertEqual(decode_bytes(data, 2, 2, 'int16le'), -2)

    def test_invalid_dtype_raises(self):
        with self.assertRaises(ValueError):
            decode_bytes(b'\x00', 0, 1, 'nope')

    def test_wrong_n_for_dtype_raises(self):
        with self.assertRaises(ValueError):
            decode_bytes(b'\x00\x00', 0, 1, 'int16le')


if __name__ == "__main__":
    unittest.main()
