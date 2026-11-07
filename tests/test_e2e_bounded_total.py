"""Tests for bounded_total, using only the standard library."""
import unittest

from e2e_bounded_total import bounded_total


class IntSubclass(int):
    pass


class OnceIterable:
    def __init__(self, items):
        self.items = items
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        if self.iterations != 1:
            raise AssertionError("iterated more than once")
        yield from self.items


class BoundedTotalTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(bounded_total([], 0), 0)

    def test_single(self):
        self.assertEqual(bounded_total([4], 4), 4)

    def test_multiple(self):
        self.assertEqual(bounded_total([1, 2, 3], 10), 6)

    def test_zero_values(self):
        self.assertEqual(bounded_total([0, 0], 0), 0)

    def test_limit_equal(self):
        self.assertEqual(bounded_total([2, 3], 5), 5)

    def test_over_limit(self):
        with self.assertRaises(OverflowError):
            bounded_total([2, 4], 5)

    def test_huge_integers(self):
        huge = 10 ** 100
        self.assertEqual(bounded_total([huge, huge], 2 * huge), 2 * huge)

    def test_negative_value(self):
        with self.assertRaises(ValueError):
            bounded_total([1, -1], 10)

    def test_bool_value(self):
        with self.assertRaises(TypeError):
            bounded_total([True], 10)

    def test_subclass_value(self):
        with self.assertRaises(TypeError):
            bounded_total([IntSubclass(1)], 10)

    def test_float_value(self):
        with self.assertRaises(TypeError):
            bounded_total([1.0], 10)

    def test_string_value(self):
        with self.assertRaises(TypeError):
            bounded_total(["1"], 10)

    def test_bool_limit(self):
        with self.assertRaises(TypeError):
            bounded_total([], True)

    def test_subclass_limit(self):
        with self.assertRaises(TypeError):
            bounded_total([], IntSubclass(5))

    def test_negative_limit(self):
        with self.assertRaises(ValueError):
            bounded_total([], -1)

    def test_float_limit(self):
        with self.assertRaises(TypeError):
            bounded_total([], 5.0)

    def test_generator(self):
        self.assertEqual(bounded_total((x for x in [2, 3]), 5), 5)

    def test_one_iteration(self):
        values = OnceIterable([2, 3])
        self.assertEqual(bounded_total(values, 5), 5)
        self.assertEqual(values.iterations, 1)

    def test_no_mutation(self):
        values = [2, 3, 0]
        self.assertEqual(bounded_total(values, 5), 5)
        self.assertEqual(values, [2, 3, 0])

    def test_invalid_limit_checked_before_iteration(self):
        values = OnceIterable([1])
        with self.assertRaises(TypeError):
            bounded_total(values, False)
        self.assertEqual(values.iterations, 0)


if __name__ == "__main__":
    unittest.main()
