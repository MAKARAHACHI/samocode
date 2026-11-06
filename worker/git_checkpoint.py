#!/usr/bin/env python3
"""One-shot, non-force Git push of an independently reviewed SHA.

Not a Git credential provider or a scheduler. The approved host gateway must
pass a pinned OperationalGate and an allowed checkout. No automatic retries.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from worker.operational_gate import OperationalGate, Denied

GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_ORIGIN = {
    "https://github.com/MAKARAHACHI/samocode",
    "https://github.com/MAKARAHACHI/samocode.git",
    "git@github.com:MAKARAHACHI/samocode.git",
}


class ReleaseBlocked(ValueError):
    pass


def _require(ok: bool, why: str) -> None:
    if not ok:
        raise ReleaseBlocked(why)


def _result(command: list[str], checkout: Path, runner) -> str:
    try:
        process = runner(command, cwd=checkout, capture_output=True,
                         text=True, timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseBlocked("GIT_OPERATION_UNCERTAIN_NO_RETRY") from exc
    _require(process.returncode == 0, "GIT_OPERATION_FAILED_NO_RETRY")
    return process.stdout.strip()


def verify_reviewed_head(gate: OperationalGate, checkout: Path,
                         task: str, source_path: str, source_sha256: str,
                         qa: dict, expected_head: str,
                         runner=subprocess.run) -> dict:
    _require(isinstance(gate, OperationalGate), "MISSING_APPROVAL_GATE")
    _require(isinstance(checkout, Path) and checkout.is_absolute()
             and checkout.is_dir() and not checkout.is_symlink(),
             "INVALID_CHECKOUT")
    checkout = checkout.resolve(strict=True)
    _require(checkout.is_relative_to(gate.root), "CHECKOUT_OUTSIDE_TASK")
    _require(type(source_path) is str and source_path and
             not Path(source_path).is_absolute() and
             ".." not in Path(source_path).parts and
             "\\" not in source_path, "UNTRUSTED_SOURCE_PATH")
    source = checkout / source_path
    _require(source.is_file() and not source.is_symlink() and
             source.resolve(strict=True).is_relative_to(checkout),
             "UNTRUSTED_REVIEWED_SOURCE")
    _require(hashlib.sha256(source.read_bytes()).hexdigest() == source_sha256,
             "SOURCE_CHANGED_SINCE_QA")
    _require(type(expected_head) is str and GIT_SHA.fullmatch(expected_head),
             "INVALID_REVIEWED_HEAD")
    _require(_result(["git","rev-parse","--verify","HEAD"],checkout,runner)
             == expected_head, "HEAD_CHANGED_SINCE_REVIEW")
    _require(_result(["git","remote","get-url","origin"],checkout,runner)
             in _ALLOWED_ORIGIN, "WRONG_GIT_REMOTE")
    _require(_result(["git","status","--porcelain"],checkout,runner) == "",
             "UNCLEAN_WORKTREE")
    auth = gate.authorize("git_push", task=task, repo=gate.policy["repo"],
                          branch=gate.policy["branch"], sha256=source_sha256,
                          qa=qa, reviewed_commit_sha=expected_head,
                          actual_commit_sha=expected_head)
    _require(auth.get("allowed") is True, "GATE_DENIED")
    return {"status": "REVIEWED_HEAD_READY", "head_sha": expected_head,
            "branch": gate.policy["branch"], "repo": gate.policy["repo"],
            "source_sha256": source_sha256, "task": task,
            "git_push_argv": ["git","push","--porcelain","origin",
                               "HEAD:refs/heads/" + gate.policy["branch"]],
            "force_push": False}


def publish_once(gate: OperationalGate, checkout: Path, task: str,
                 source_path: str, source_sha256: str, qa: dict,
                 expected_head: str, ledger_path: Path,
                 runner=subprocess.run) -> dict:
    preflight = verify_reviewed_head(gate, checkout, task, source_path,
                                     source_sha256, qa, expected_head, runner)
    _require(isinstance(ledger_path, Path) and ledger_path.is_absolute()
             and ledger_path.parent.is_dir()
             and ledger_path.parent.resolve(strict=True).is_relative_to(gate.root)
             and not ledger_path.exists() and not ledger_path.is_symlink(),
             "PUSH_LEDGER_NOT_FRESH")
    # Exclusive durable intent means a timeout, crash or ambiguous result
    # cannot repeat an unknown push in a second call.
    intent = {"status": "ATTEMPTING_NO_RETRY", **preflight}
    try:
        fd = os.open(ledger_path,
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise ReleaseBlocked("PUSH_ALREADY_ATTEMPTED") from exc
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        json.dump(intent,f,sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    output = _result(preflight["git_push_argv"],checkout.resolve(),runner)
    receipt = dict(preflight,status="PUSH_COMMAND_EXIT0",
                   git_stdout_sha256=hashlib.sha256(output.encode()).hexdigest(),
                   receipt_requires_remote_readback=True)
    # Write a SEPARATE create-only success receipt; never rewrite intent.
    receipt_path=ledger_path.with_name(ledger_path.name + ".success")
    flags=os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW
    with os.fdopen(os.open(receipt_path,flags,0o600),"w",encoding="utf-8") as f:
        json.dump(receipt,f,sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    return receipt
