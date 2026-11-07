"""Unit tests for strict_run_receipt."""
import copy
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from strict_run_receipt import validate_run_receipt

SHA = "a" * 64

def valid(**changes):
    data = dict(role="testing-agent", run_id="run-1", exit_code=0,
                tests_passed=12, source_sha256=SHA)
    data.update(changes)
    return data

class SubInt(int):
    pass

class SubStr(str):
    pass

class SubDict(dict):
    pass

class ReceiptTests(unittest.TestCase):
    def test_testing_role(self):
        self.assertEqual(validate_run_receipt(valid()), valid())

    def test_quality_role(self):
        self.assertEqual(validate_run_receipt(valid(role="quality-agent"))["role"], "quality-agent")

    def test_missing_each_key(self):
        for key in valid():
            with self.subTest(key=key):
                data = valid()
                del data[key]
                with self.assertRaises(ValueError):
                    validate_run_receipt(data)

    def test_extra_key(self):
        with self.assertRaises(ValueError):
            validate_run_receipt(valid(unexpected=1))

    def test_receipt_subclass_and_non_dict(self):
        for data in (SubDict(valid()), [], None):
            with self.subTest(data=type(data)):
                with self.assertRaises(TypeError):
                    validate_run_receipt(data)

    def test_role_invalid_values(self):
        for role in ("developer", "", "Testing-Agent"):
            with self.subTest(role=role), self.assertRaises(ValueError):
                validate_run_receipt(valid(role=role))

    def test_text_subclasses_and_non_strings(self):
        for key in ("role", "run_id", "source_sha256"):
            for value in (SubStr(valid()[key]), None, 123):
                with self.subTest(key=key, value=value), self.assertRaises(TypeError):
                    validate_run_receipt(valid(**{key: value}))

    def test_run_id_empty_whitespace_and_long(self):
        for value in ("", " ", " run", "run ", "x" * 101, "\trun"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_run_receipt(valid(run_id=value))

    def test_run_id_max_length(self):
        self.assertEqual(len(validate_run_receipt(valid(run_id="x" * 100))["run_id"]), 100)

    def test_invalid_hashes(self):
        for value in ("a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 63 + "\\n"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_run_receipt(valid(source_sha256=value))

    def test_valid_hash_alphabet(self):
        self.assertEqual(validate_run_receipt(valid(source_sha256="0123456789abcdef" * 4))["source_sha256"], "0123456789abcdef" * 4)

    def test_invalid_exit_code(self):
        for value in (-1, 1, 999):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_run_receipt(valid(exit_code=value))

    def test_exit_code_bool_and_subclass(self):
        for value in (False, True, SubInt(0), "0"):
            with self.subTest(value=value), self.assertRaises(TypeError):
                validate_run_receipt(valid(exit_code=value))

    def test_invalid_test_count(self):
        for value in (-1, 0, 11):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_run_receipt(valid(tests_passed=value))

    def test_test_count_bool_and_subclass(self):
        for value in (False, True, SubInt(12), 12.0):
            with self.subTest(value=value), self.assertRaises(TypeError):
                validate_run_receipt(valid(tests_passed=value))

    def test_huge_count(self):
        self.assertEqual(validate_run_receipt(valid(tests_passed=10**100))["tests_passed"], 10**100)

    def test_immutability_and_new_identity(self):
        data = valid()
        before = copy.deepcopy(data)
        output = validate_run_receipt(data)
        self.assertEqual(data, before)
        self.assertEqual(output, data)
        self.assertIsNot(output, data)
        output["role"] = "quality-agent"
        self.assertEqual(data, before)

    def test_repeatability(self):
        data = valid()
        self.assertEqual(validate_run_receipt(data), validate_run_receipt(data))

if __name__ == "__main__":
    unittest.main()

