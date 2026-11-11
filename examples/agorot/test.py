"""Executable deterministic tests and a separate readback QA mode.

Run normally for implementation tests or with --qa EXPECTED_SOURCE_SHA EXPECTED_TEST_SHA
to reread and verify the exact saved artifacts and run additional edge-case QA.
"""
import hashlib
import json
from pathlib import Path
import runpy
import sys
import unittest

SOURCE_PATH = Path(__file__).with_name("source.py")
TEST_PATH = Path(__file__)
agorot_total = runpy.run_path(str(SOURCE_PATH))["agorot_total"]


class AgorotTotalTests(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(agorot_total([]), 0)

    def test_empty_tuple(self):
        self.assertEqual(agorot_total(()), 0)

    def test_single_zero(self):
        self.assertEqual(agorot_total([0]), 0)

    def test_single_positive(self):
        self.assertEqual(agorot_total([23]), 23)

    def test_multiple_values(self):
        self.assertEqual(agorot_total([100, 25, 75, 0]), 200)

    def test_large_arbitrary_precision_integers(self):
        self.assertEqual(agorot_total([10**100, 10**100, 1]), 2 * 10**100 + 1)

    def test_generator(self):
        self.assertEqual(agorot_total(n for n in (10, 20, 30)), 60)

    def test_iterator_consumed_exactly_once(self):
        class SinglePass:
            def __init__(self):
                self.items = iter([7, 8, 9])
                self.iter_calls = 0
            def __iter__(self):
                self.iter_calls += 1
                if self.iter_calls != 1:
                    raise AssertionError("second iteration attempted")
                return self.items
        values = SinglePass()
        self.assertEqual(agorot_total(values), 24)
        self.assertEqual(values.iter_calls, 1)

    def test_input_list_is_unchanged(self):
        values = [5, 3, 7, 0]
        before = list(values)
        self.assertEqual(agorot_total(values), 15)
        self.assertEqual(values, before)

    def test_input_tuple_is_unchanged(self):
        values = (9, 1, 0)
        self.assertEqual(agorot_total(values), 10)
        self.assertEqual(values, (9, 1, 0))

    def test_bool_true_rejected(self):
        with self.assertRaises(TypeError):
            agorot_total([True])

    def test_bool_false_rejected(self):
        with self.assertRaises(TypeError):
            agorot_total([False])

    def test_int_subclass_rejected(self):
        class ChildInt(int):
            pass
        with self.assertRaises(TypeError):
            agorot_total([ChildInt(4)])

    def test_negative_one_rejected(self):
        with self.assertRaises(ValueError):
            agorot_total([-1])

    def test_negative_after_valid_prefix_rejected(self):
        with self.assertRaises(ValueError):
            agorot_total((2, 3, -4))

    def test_float_rejected_even_if_integral(self):
        with self.assertRaises(TypeError):
            agorot_total([2.0])

    def test_string_rejected(self):
        with self.assertRaises(TypeError):
            agorot_total(["2"])

    def test_none_item_rejected(self):
        with self.assertRaises(TypeError):
            agorot_total([None])

    def test_non_iterable_rejected(self):
        with self.assertRaises(TypeError):
            agorot_total(123)

    def test_nested_list_rejected(self):
        with self.assertRaises(TypeError):
            agorot_total([[2]])

    def test_late_invalid_stops_iteration(self):
        seen = []
        def values():
            for n in (4, True, 7):
                seen.append(n)
                yield n
        with self.assertRaises(TypeError):
            agorot_total(values())
        self.assertEqual(seen, [4, True])

    def test_range_values(self):
        self.assertEqual(agorot_total(range(5)), 10)

    def test_dict_integer_keys(self):
        values = {2: "a", 4: "b"}
        self.assertEqual(agorot_total(values), 6)
        self.assertEqual(values, {2: "a", 4: "b"})


class ReadbackQATests(unittest.TestCase):
    expected_source = ""
    expected_test = ""

    def test_exact_saved_source_sha256(self):
        self.assertEqual(hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest(), self.expected_source)

    def test_exact_saved_test_sha256(self):
        self.assertEqual(hashlib.sha256(TEST_PATH.read_bytes()).hexdigest(), self.expected_test)

    def test_readback_source_contains_function(self):
        self.assertIn(b"def agorot_total(values):", SOURCE_PATH.read_bytes())

    def test_tight_one_shot_iterable(self):
        class ExactlyOneIteration:
            def __init__(self):
                self.used = False
            def __iter__(self):
                if self.used:
                    raise AssertionError("iterated twice")
                self.used = True
                yield 11
                yield 12
        obj = ExactlyOneIteration()
        self.assertEqual(agorot_total(obj), 23)
        self.assertTrue(obj.used)

    def test_non_integral_numeric_rejected(self):
        from decimal import Decimal
        from fractions import Fraction
        for value in (Decimal("4"), Fraction(4, 1), 4.0, 4j):
            with self.subTest(value=repr(value)), self.assertRaises(TypeError):
                agorot_total([value])

    def test_late_failure_does_not_modify_original_list(self):
        original = [8, 4, -1, 12]
        with self.assertRaises(ValueError):
            agorot_total(original)
        self.assertEqual(original, [8, 4, -1, 12])

    def test_huge_positive_then_bool_is_type_error(self):
        with self.assertRaises(TypeError):
            agorot_total((10**500, False))

    def test_generator_stop_after_bad_negative(self):
        steps = []
        def generator():
            for value in (1, -2, 300):
                steps.append(value)
                yield value
        with self.assertRaises(ValueError):
            agorot_total(generator())
        self.assertEqual(steps, [1, -2])


def main():
    qa_mode = len(sys.argv) > 1 and sys.argv[1] == "--qa"
    if qa_mode:
        if len(sys.argv) != 4:
            raise SystemExit("usage: test.py --qa SOURCE_SHA256 TEST_SHA256")
        ReadbackQATests.expected_source, ReadbackQATests.expected_test = sys.argv[2:]
    elif len(sys.argv) != 1:
        raise SystemExit("unexpected arguments")

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AgorotTotalTests)
    if qa_mode:
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ReadbackQATests))
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    count = result.testsRun
    print("QA_EVIDENCE_JSON=" + json.dumps({
        "mode": "readback_qa" if qa_mode else "implementation",
        "status": "PASS" if result.wasSuccessful() else "FAIL",
        "tests_run": count,
        "tests_passed": count - len(result.failures) - len(result.errors) - len(result.skipped),
        "failures": len(result.failures),
        "errors": len(result.errors),
        "source_sha256": hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest(),
        "test_sha256": hashlib.sha256(TEST_PATH.read_bytes()).hexdigest(),
    }, sort_keys=True))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
