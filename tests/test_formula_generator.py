"""Characterization tests for services/formula_generator.py."""

from __future__ import annotations

import unittest

from services.formula_generator import generate_formula


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _branch_cfg(branches, output_transforms=None, combine=None):
    if isinstance(combine, list):
        combine_obj = {"ops": [{"op": op} for op in combine]}
    elif combine:
        combine_obj = {"ops": [{"op": combine}]}
    else:
        combine_obj = None
    return {
        "type": "pipeline",
        "version": 3,
        "branches": branches,
        "combine": combine_obj,
        "output_transforms": output_transforms or [],
    }


def _branch(source, transforms=None, label="A"):
    return {"label": label, "source": source, "transforms": transforms or []}


def _sig(name):
    return {"kind": "signal", "signal_name": name}


def _bam(pgn, start_bit, length, byte_order="LE"):
    return {"kind": "bam_extract", "pgn": pgn, "start_bit": start_bit,
            "length": length, "byte_order": byte_order}


def _bam_chunk(pgn, chunk_size, start, length, dtype):
    return {
        "kind": "bam_chunk_extract",
        "pgn": pgn, "chunk_size": chunk_size,
        "start": start, "len": length, "dtype": dtype,
    }


def _raw(can_id, start_bit, length, byte_order="LE", mode="exact"):
    return {"kind": "raw_extract", "can_id": can_id,
            "start_bit": start_bit, "length": length,
            "byte_order": byte_order, "mode": mode}


def _raw_field(can_id_or_pgn, start_bit, length, byte_order="LE", type_data="uint",
               bam=False, mode="exact", mux_start=None, mux_bytes=None, mux_value=None):
    cfg = {
        "kind": "raw_field", "bam": bam,
        "start_bit": start_bit, "length": length,
        "byte_order": byte_order, "type_data": type_data,
    }
    if bam:
        cfg["pgn"] = can_id_or_pgn
    else:
        cfg["can_id"] = can_id_or_pgn
        cfg["mode"] = mode
    if mux_start is not None:
        cfg["mux_start"] = mux_start
        cfg["mux_bytes"] = mux_bytes
        cfg["mux_value"] = mux_value
    return cfg


# ---------------------------------------------------------------------------
# Single-source, no transforms
# ---------------------------------------------------------------------------

class RawFieldTests(unittest.TestCase):
    def test_raw_field_frame_le(self):
        code = generate_formula(_branch_cfg([_branch(_raw_field(0x123, 0, 8, "LE"))]))
        self.assertIn("raw_bits(0x123, 0, 8, byte_order='LE', mode='exact')", code)
        self.assertIn("result = ts, y", code)

    def test_raw_field_frame_be(self):
        code = generate_formula(_branch_cfg([_branch(_raw_field(0x123, 7, 16, "BE"))]))
        self.assertIn("raw_bits(0x123, 7, 16, byte_order='BE', mode='exact')", code)

    def test_raw_field_bam_le(self):
        code = generate_formula(_branch_cfg([_branch(_raw_field(0xFF17, 16, 16, bam=True))]))
        self.assertIn("bam_bits(0xff17, 16, 16, byte_order='LE')", code)

    def test_raw_field_bam_be(self):
        code = generate_formula(_branch_cfg([_branch(_raw_field(0xFF17, 23, 16, "BE", bam=True))]))
        self.assertIn("bam_bits(0xff17, 23, 16, byte_order='BE')", code)

    def test_raw_field_j1939_mode(self):
        code = generate_formula(_branch_cfg([_branch(_raw_field(0x18FF0001, 0, 8, mode="j1939"))]))
        self.assertIn("mode='j1939'", code)

    def test_raw_field_signed_adds_sign_extension(self):
        code = generate_formula(_branch_cfg([_branch(_raw_field(0x123, 0, 16, type_data="int"))]))
        self.assertIn("np.where", code)
        self.assertIn("2**15", code)
        self.assertIn("2**16", code)

    def test_raw_field_uint_no_type_conversion(self):
        code = generate_formula(_branch_cfg([_branch(_raw_field(0x123, 0, 8))]))
        self.assertNotIn("np.where", code)
        self.assertNotIn("view(np.float32)", code)

    def test_raw_field_float32_adds_view_cast(self):
        code = generate_formula(_branch_cfg([_branch(_raw_field(0x123, 0, 32, type_data="float32"))]))
        self.assertIn("view(np.float32)", code)
        self.assertIn("astype(np.uint32)", code)

    def test_raw_field_with_mux(self):
        code = generate_formula(_branch_cfg([
            _branch(_raw_field(0x123, 8, 8, mux_start=0, mux_bytes=1, mux_value=5))
        ]))
        self.assertIn("mux_start=0", code)
        self.assertIn("mux_bytes=1", code)
        self.assertIn("mux_value=5", code)

    def test_raw_field_bam_with_mux(self):
        code = generate_formula(_branch_cfg([
            _branch(_raw_field(0xFF17, 16, 16, bam=True, mux_start=0, mux_bytes=1, mux_value=3))
        ]))
        self.assertIn("bam_bits(", code)
        self.assertIn("mux_start=0", code)
        self.assertIn("mux_value=3", code)

    def test_raw_field_no_mux_no_mux_args(self):
        code = generate_formula(_branch_cfg([_branch(_raw_field(0x123, 0, 8))]))
        self.assertNotIn("mux_start", code)


class SingleSourceNoTransformTests(unittest.TestCase):
    def test_signal_generates_signal_call(self):
        code = generate_formula(_branch_cfg([_branch(_sig("rpm"))]))
        self.assertIn("signal('rpm')", code)
        self.assertIn("result = ts, y", code)

    def test_signal_only_two_lines(self):
        code = generate_formula(_branch_cfg([_branch(_sig("rpm"))]))
        lines = [l for l in code.strip().splitlines() if l.strip()]
        self.assertEqual(len(lines), 2)

    def test_bam_extract_generates_call(self):
        code = generate_formula(_branch_cfg([_branch(_bam(0xFF17, 144, 16, "LE"))]))
        self.assertIn("bam_bits(0xff17, 144, 16, byte_order='LE')", code)
        self.assertIn("result = ts, y", code)

    def test_bam_extract_be_generates_call(self):
        code = generate_formula(_branch_cfg([_branch(_bam(0xFF17, 151, 16, "BE"))]))
        self.assertIn("bam_bits(0xff17, 151, 16, byte_order='BE')", code)

    def test_bam_chunk_generates_loop(self):
        code = generate_formula(_branch_cfg([_branch(_bam_chunk(0xFF17, 20, 18, 2, "int16le"))]))
        self.assertIn("bam_messages(pgn=0xff17)", code)
        self.assertIn("range(0, len(_msg.data), 20)", code)
        self.assertIn("len(_chunk) == 20", code)
        self.assertIn("decode_bytes(_chunk, 18, 2, 'int16le')", code)
        self.assertIn("result = ts, y", code)

    def test_raw_extract_generates_call(self):
        code = generate_formula(_branch_cfg([_branch(_raw(0x18FF0001, 16, 16, "LE"))]))
        self.assertIn("raw_bits(0x18ff0001, 16, 16, byte_order='LE', mode='exact')", code)

    def test_raw_extract_be_generates_call(self):
        code = generate_formula(_branch_cfg([_branch(_raw(0x18FF0001, 23, 16, "BE"))]))
        self.assertIn("raw_bits(0x18ff0001, 23, 16, byte_order='BE', mode='exact')", code)

    def test_raw_extract_j1939_mode(self):
        code = generate_formula(_branch_cfg([_branch(_raw(0x18FF0001, 0, 8, "LE", mode="j1939"))]))
        self.assertIn("mode='j1939'", code)

    def test_small_pgn_uses_decimal(self):
        code = generate_formula(_branch_cfg([_branch(_bam(5, 0, 8, "LE"))]))
        self.assertIn("bam_bits(5,", code)

    def test_large_pgn_uses_hex(self):
        code = generate_formula(_branch_cfg([_branch(_bam(256, 0, 8, "LE"))]))
        self.assertIn("bam_bits(0x100,", code)


# ---------------------------------------------------------------------------
# Single-source with transforms
# ---------------------------------------------------------------------------

class TransformTests(unittest.TestCase):
    def _code(self, *transforms):
        return generate_formula(
            _branch_cfg([_branch(_sig("x"))], output_transforms=list(transforms))
        )

    def test_scale(self):
        code = self._code({"op": "scale", "value": 2.0})
        self.assertIn("y = y * 2.0", code)

    def test_offset(self):
        code = self._code({"op": "offset", "value": -5.0})
        self.assertIn("y = y + -5.0", code)

    def test_abs(self):
        code = self._code({"op": "abs"})
        self.assertIn("y = np.abs(y)", code)

    def test_clamp(self):
        code = self._code({"op": "clamp", "min": 0.0, "max": 100.0})
        self.assertIn("y = np.clip(y, 0.0, 100.0)", code)

    def test_round(self):
        code = self._code({"op": "round", "decimals": 3})
        self.assertIn("y = np.round(y, 3)", code)

    def test_math_sqrt(self):
        code = self._code({"op": "math", "fn": "sqrt"})
        self.assertIn("y = np.sqrt(y)", code)

    def test_math_ln_maps_to_log(self):
        code = self._code({"op": "math", "fn": "ln"})
        self.assertIn("y = np.log(y)", code)

    def test_math_log10(self):
        code = self._code({"op": "math", "fn": "log10"})
        self.assertIn("y = np.log10(y)", code)

    def test_math_abs(self):
        code = self._code({"op": "math", "fn": "abs"})
        self.assertIn("y = np.abs(y)", code)

    def test_conditional_full(self):
        code = self._code({
            "op": "conditional", "cmp": ">", "threshold": 180.0,
            "true_scale": 2.0, "true_offset": -50.0,
            "false_scale": 1.0, "false_offset": 0.0,
        })
        self.assertIn("np.where(y > 180.0, y * 2.0 + -50.0, y)", code)

    def test_conditional_identity_arms(self):
        code = self._code({
            "op": "conditional", "cmp": "<", "threshold": 0.0,
            "true_scale": 1.0, "true_offset": 0.0,
            "false_scale": 1.0, "false_offset": 0.0,
        })
        self.assertIn("np.where(y < 0.0, y, y)", code)

    def test_conditional_scale_only_true(self):
        code = self._code({
            "op": "conditional", "cmp": ">", "threshold": 10.0,
            "true_scale": 3.0, "true_offset": 0.0,
            "false_scale": 1.0, "false_offset": 0.0,
        })
        self.assertIn("y * 3.0", code)
        self.assertNotIn("y * 3.0 +", code)

    def test_conditional_offset_only_true(self):
        code = self._code({
            "op": "conditional", "cmp": ">", "threshold": 10.0,
            "true_scale": 1.0, "true_offset": 7.0,
            "false_scale": 1.0, "false_offset": 0.0,
        })
        self.assertIn("y + 7.0", code)

    def test_chained_transforms_in_order(self):
        code = self._code(
            {"op": "scale", "value": 2.0},
            {"op": "offset", "value": -1.0},
            {"op": "abs"},
        )
        lines = code.strip().splitlines()
        scale_idx  = next(i for i, l in enumerate(lines) if "y * 2.0" in l)
        offset_idx = next(i for i, l in enumerate(lines) if "y + -1.0" in l)
        abs_idx    = next(i for i, l in enumerate(lines) if "np.abs" in l)
        self.assertLess(scale_idx, offset_idx)
        self.assertLess(offset_idx, abs_idx)


# ---------------------------------------------------------------------------
# Multi-source / combine
# ---------------------------------------------------------------------------

class MultiSourceTests(unittest.TestCase):
    def test_two_signals_subtract(self):
        code = generate_formula(_branch_cfg(
            [_branch(_sig("pressure_hi"), label="A"), _branch(_sig("pressure_lo"), label="B")],
            combine="sub",
        ))
        self.assertIn("signal('pressure_hi')", code)
        self.assertIn("signal('pressure_lo')", code)
        self.assertIn("align(", code)
        self.assertIn("y = y - y_b", code)

    def test_two_signals_add(self):
        code = generate_formula(_branch_cfg([_branch(_sig("a")), _branch(_sig("b"), label="B")], combine="add"))
        self.assertIn("y = y + y_b", code)

    def test_two_signals_mul(self):
        code = generate_formula(_branch_cfg([_branch(_sig("a")), _branch(_sig("b"), label="B")], combine="mul"))
        self.assertIn("y = y * y_b", code)

    def test_combine_max(self):
        code = generate_formula(_branch_cfg([_branch(_sig("a")), _branch(_sig("b"), label="B")], combine="max"))
        self.assertIn("np.maximum(y, y_b)", code)

    def test_combine_min(self):
        code = generate_formula(_branch_cfg([_branch(_sig("a")), _branch(_sig("b"), label="B")], combine="min"))
        self.assertIn("np.minimum(y, y_b)", code)

    def test_bam_and_signal_combined(self):
        code = generate_formula(_branch_cfg(
            [_branch(_bam(0xFF17, 0, 16, "LE")), _branch(_sig("speed"), label="B")],
            combine="add",
        ))
        self.assertIn("bam_bits(0xff17", code)
        self.assertIn("signal('speed')", code)
        self.assertIn("y = y + y_b", code)

    def test_two_chunk_sources_no_variable_collision(self):
        code = generate_formula(_branch_cfg(
            [_branch(_bam_chunk(0xFF17, 20, 18, 2, "int16le")),
             _branch(_bam_chunk(0xFF18, 10, 8, 2, "uint16le"), label="B")],
            combine="sub",
        ))
        # Each source must use distinct internal temp variable names
        self.assertIn("_msgs_a", code)
        self.assertIn("_msgs_b", code)
        self.assertIn("ts_a, y_a = np.array", code)
        self.assertIn("ts_b, y_b = np.array", code)

    def test_default_combine_is_add(self):
        code = generate_formula(_branch_cfg([_branch(_sig("a")), _branch(_sig("b"), label="B")], combine=None))
        self.assertIn("y = y + y_b", code)

    def test_branch_transforms_are_applied_before_combine(self):
        code = generate_formula(_branch_cfg(
            [
                _branch(_sig("a"), [{"op": "scale", "value": 0.1}], "A"),
                _branch(_sig("b"), [{"op": "offset", "value": -5.0}], "B"),
            ],
            combine="sub",
            output_transforms=[{"op": "round", "decimals": 2}],
        ))
        lines = code.strip().splitlines()
        scale_idx = next(i for i, line in enumerate(lines) if "y_a = y_a * 0.1" in line)
        offset_idx = next(i for i, line in enumerate(lines) if "y_b = y_b + -5.0" in line)
        align_idx = next(i for i, line in enumerate(lines) if "align(" in line)
        combine_idx = next(i for i, line in enumerate(lines) if "y = y - y_b" in line)
        round_idx = next(i for i, line in enumerate(lines) if "np.round(y, 2)" in line)
        self.assertLess(scale_idx, align_idx)
        self.assertLess(offset_idx, align_idx)
        self.assertLess(align_idx, combine_idx)
        self.assertLess(combine_idx, round_idx)

    def test_three_signals_chain_operations(self):
        code = generate_formula(_branch_cfg(
            [
                _branch(_sig("a"), label="A"),
                _branch(_sig("b"), label="B"),
                _branch(_sig("c"), label="C"),
            ],
            combine=["sub", "add"],
        ))
        self.assertIn("ts, (y_a, y_b, y_c) = align((ts_a, y_a), (ts_b, y_b), (ts_c, y_c))", code)
        self.assertIn("y = y_a", code)
        self.assertIn("y = y - y_b", code)
        self.assertIn("y = y + y_c", code)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class ErrorTests(unittest.TestCase):
    def test_no_sources_raises(self):
        with self.assertRaises(ValueError):
            generate_formula({"type": "pipeline", "version": 3, "branches": []})

    def test_missing_branches_key_raises(self):
        with self.assertRaises(ValueError):
            generate_formula({"type": "pipeline", "version": 3})

    def test_wrong_number_of_combine_operations_raises(self):
        with self.assertRaises(ValueError):
            generate_formula(_branch_cfg([
                _branch(_sig("a")),
                _branch(_sig("b"), label="B"),
                _branch(_sig("c"), label="C"),
            ], combine=["add"]))

    def test_unknown_source_kind_raises(self):
        with self.assertRaises(ValueError):
            generate_formula(_branch_cfg([_branch({"kind": "mystery", "signal_name": "x"})]))

    def test_unknown_transform_op_raises(self):
        with self.assertRaises(ValueError):
            generate_formula(_branch_cfg([_branch(_sig("x"))], output_transforms=[{"op": "nope"}]))

    def test_unknown_math_fn_raises(self):
        with self.assertRaises(ValueError):
            generate_formula(_branch_cfg([_branch(_sig("x"))], output_transforms=[{"op": "math", "fn": "badFn"}]))

    def test_unknown_combine_raises(self):
        with self.assertRaises(ValueError):
            generate_formula(_branch_cfg([_branch(_sig("a")), _branch(_sig("b"), label="B")], combine="xor"))


if __name__ == "__main__":
    unittest.main()
