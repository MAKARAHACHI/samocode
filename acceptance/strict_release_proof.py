"""Strict, pure release proof validation using saved upstream validators."""
import importlib
import pathlib
import re
import sys

_PATHS = frozenset((
    "acceptance/strict_run_receipt.py",
    "tests/test_strict_run_receipt.py",
    "acceptance/strict_release_proof.py",
    "tests/test_strict_release_proof.py",
))
_SHA40 = re.compile(r"[0-9a-f]{40}")

def _dependencies():
    here = pathlib.Path(__file__).resolve()
    # TA-V: mission/b -> mission/a; checkout: acceptance -> acceptance.
    a_dir = here.parent.parent / "a" if (here.parent.parent / "a" / "strict_run_receipt.py").is_file() else here.parent
    if not (a_dir / "strict_run_receipt.py").is_file():
        raise ValueError("saved A validator unavailable")
    # Import the original worker package, not an implementation copied here.
    vendor = here.parents[2] / "samocode_native_workflow_integration_20261104" / "vendor"
    roots = (vendor, here.parent.parent)
    for root in roots:
        if (root / "samocode_upstream" / "worker" / "phases.py").is_file():
            worker_root = root
            break
        if (root / "worker" / "phases.py").is_file():
            worker_root = root
            break
    else:
        raise ValueError("original worker phases unavailable")
    for root in (str(a_dir), str(worker_root)):
        if root not in sys.path:
            sys.path.insert(0, root)
    validator = importlib.import_module("strict_run_receipt").validate_run_receipt
    phases = importlib.import_module(
        "samocode_upstream.worker.phases" if (worker_root / "samocode_upstream").is_dir()
        else "worker.phases"
    )
    return validator, phases

def verify_release_proof(testing, quality, local_sha, remote_sha, committed_paths):
    if type(testing) is not dict or type(quality) is not dict:
        raise TypeError("receipts must be built-in dicts")
    validator, phases = _dependencies()
    t = validator(testing)
    q = validator(quality)
    if t["role"] != "testing-agent" or q["role"] != "quality-agent":
        raise ValueError("incorrect QA roles")
    if t["run_id"] == q["run_id"] or t["source_sha256"] != q["source_sha256"]:
        raise ValueError("QA independence or source mismatch")
    if type(local_sha) is not str or type(remote_sha) is not str:
        raise TypeError("commit hashes must be built-in strings")
    if not _SHA40.fullmatch(local_sha) or not _SHA40.fullmatch(remote_sha) or local_sha != remote_sha:
        raise ValueError("invalid or mismatched commit hashes")
    if type(committed_paths) not in (list, tuple):
        raise TypeError("committed_paths must be a built-in list or tuple")
    if any(type(p) is not str for p in committed_paths):
        raise TypeError("paths must be built-in strings")
    if len(committed_paths) != 4 or set(committed_paths) != _PATHS:
        raise ValueError("exactly four unique approved paths required")
    transition, _ = phases.validate_transition("testing", "quality")
    signal, _ = phases.validate_signal_for_phase("quality", "continue")
    if type(transition) is not bool or not transition or type(signal) is not bool or not signal:
        raise ValueError("original worker phase validation rejected proof")
    return {
        "status": "RELEASE_PROOF_VALID",
        "testing_run_id": t["run_id"],
        "quality_run_id": q["run_id"],
        "source_sha256": t["source_sha256"],
        "commit_sha": local_sha,
        "committed_paths": sorted(_PATHS),
    }
