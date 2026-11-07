"""Strict validation of independently recorded unittest run metadata."""
import re

_KEYS = frozenset(("role", "run_id", "exit_code", "tests_passed", "source_sha256"))
_SHA = re.compile(r"[0-9a-f]{64}")

def validate_run_receipt(receipt):
    """Return a fresh validated receipt; reject invalid types or values."""
    if type(receipt) is not dict:
        raise TypeError("receipt must be a built-in dict")
    if receipt.keys() != _KEYS:
        raise ValueError("receipt must contain exactly the required keys")
    role = receipt["role"]
    run_id = receipt["run_id"]
    exit_code = receipt["exit_code"]
    tests_passed = receipt["tests_passed"]
    source_sha256 = receipt["source_sha256"]
    if type(role) is not str or type(run_id) is not str or type(source_sha256) is not str:
        raise TypeError("text fields must be built-in strings")
    if type(exit_code) is not int or type(tests_passed) is not int:
        raise TypeError("numeric fields must be built-in integers")
    if role not in ("testing-agent", "quality-agent"):
        raise ValueError("invalid role")
    if not run_id or len(run_id) > 100 or run_id != run_id.strip():
        raise ValueError("invalid run_id")
    if exit_code != 0:
        raise ValueError("exit_code must be zero")
    if tests_passed < 12:
        raise ValueError("tests_passed must be at least 12")
    if _SHA.fullmatch(source_sha256) is None:
        raise ValueError("invalid sha256")
    return dict(receipt)


