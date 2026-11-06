#!/usr/bin/env python3
"""Fail-closed approval gate for SAMOCODE's existing owner/executor.

This module is not an alternative scheduler, Git client or CDP sender.
The EXISTING host TA-V/Hermes executor must pass the operator-controlled
approval bytes and independently pinned SHA256 on EVERY privileged operation.
Never allow the agent to choose the expected digest or bypass this checker.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from worker.plan_resolver import (
    resolve_plan_phase, validate_plan_contract, select_active_phase
)
from worker.phases import (
    get_phase_config, validate_transition, validate_signal_for_phase
)

SCHEMA = "samocode.owner.approval.v1"
OPS = frozenset({"status", "next_task", "write_source", "run_tests",
                 "git_commit", "git_push", "phase_transition"})
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_-]{0,120}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
TASK = re.compile(r"^[A-Za-z0-9_-]{1,90}$")
CHECKBOX = re.compile(r"(?m)^(\s*-\s)\[[ xX]\](\s)")


class Denied(ValueError):
    """An authorization check did not succeed; no action is permitted."""


def require(ok: bool, why: str) -> None:
    if not ok:
        raise Denied(why)


def canonical_bytes(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(obj: object) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def plan_fingerprint(text: str) -> str:
    """Bind the ENTIRE approved plan, tolerating only checkbox completion."""
    require(type(text) is str, "BAD_PLAN_TEXT")
    return hashlib.sha256(CHECKBOX.sub(r"\1[ ]\2", text).encode("utf-8")).hexdigest()


def _regular_file(path: Path, root: Path) -> bytes:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise Denied("UNTRUSTED_FILE") from exc
    require(resolved.is_relative_to(root) and path.is_file()
            and not path.is_symlink(), "UNTRUSTED_FILE")
    for part in (path, *path.parents):
        if part == root:
            break
        require(not part.is_symlink(), "SYMLINK_PATH")
    return path.read_bytes()


def _validated_location(root: Path, relative: str) -> Path:
    require(type(relative) is str and relative and not "\\" in relative,
            "BAD_RELATIVE_PATH")
    p = Path(relative)
    require(not p.is_absolute() and all(x not in ("", ".", "..") for x in p.parts),
            "PATH_TRAVERSAL")
    candidate = root / p
    for parent in (candidate, *candidate.parents):
        if parent == root:
            break
        require(not parent.is_symlink(), "SYMLINK_PATH")
    require(candidate.resolve(strict=False).is_relative_to(root), "PATH_ESCAPE")
    return candidate


def _qa_proved(qa: object, expected_sha: str) -> dict:
    require(type(qa) is dict and type(expected_sha) is str
            and SHA256.fullmatch(expected_sha) is not None, "MISSING_QA")
    testing = qa.get("testing")
    quality = qa.get("quality")
    require(type(testing) is dict and type(quality) is dict,
            "MISSING_INDEPENDENT_ROLES")
    for role, item in (("testing-agent", testing), ("quality-agent", quality)):
        require(item.get("role") == role
                and type(item.get("run_id")) is str and item["run_id"]
                and type(item.get("tests_passed")) is int and item["tests_passed"] >= 12
                and type(item.get("exit_code")) is int and item["exit_code"] == 0
                and item.get("source_sha256") == expected_sha, "BAD_QA_" + role)
    require(testing["run_id"] != quality["run_id"], "DUPLICATE_QA_RUN")
    require(quality.get("testing_evidence_sha256") == digest(testing),
            "QUALITY_NOT_LINKED_TO_TESTING")
    return {"testing": testing["run_id"], "quality": quality["run_id"],
            "source_sha256": expected_sha}


class OperationalGate:
    def __init__(self, workspace_root: Path, session_dir: Path,
                 approval_bytes: bytes, trusted_approval_sha256: str):
        require(isinstance(workspace_root, Path) and workspace_root.is_absolute()
                and workspace_root.is_dir() and not workspace_root.is_symlink(),
                "INVALID_PINNED_ROOT")
        self.root = workspace_root.resolve(strict=True)
        require(isinstance(session_dir, Path) and session_dir.is_absolute()
                and session_dir.is_dir() and not session_dir.is_symlink(),
                "INVALID_SESSION")
        self.session = session_dir.resolve(strict=True)
        require(self.session.is_relative_to(self.root), "SESSION_OUTSIDE_ROOT")
        require(type(approval_bytes) is bytes
                and type(trusted_approval_sha256) is str
                and SHA256.fullmatch(trusted_approval_sha256) is not None
                and hashlib.sha256(approval_bytes).hexdigest() == trusted_approval_sha256,
                "UNPINNED_APPROVAL")
        try:
            policy = json.loads(approval_bytes.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise Denied("MALFORMED_APPROVAL") from exc
        require(type(policy) is dict and policy.get("schema") == SCHEMA,
                "BAD_POLICY_SCHEMA")
        required = {"schema", "approval_id", "task_id", "plan_fingerprint",
                    "approved_tasks", "allowed_ops", "write_prefix", "repo", "branch"}
        require(set(policy) == required, "BAD_POLICY_FIELDS")
        require(type(policy["approval_id"]) is str and policy["approval_id"]
                and type(policy["task_id"]) is str and policy["task_id"]
                and type(policy["plan_fingerprint"]) is str
                and SHA256.fullmatch(policy["plan_fingerprint"]) is not None,
                "BAD_POLICY_IDENTITY")
        require(type(policy["approved_tasks"]) is list
                and 1 <= len(policy["approved_tasks"]) <= 100
                and all(type(t) is str and TASK.fullmatch(t)
                        for t in policy["approved_tasks"])
                and len(set(policy["approved_tasks"])) == len(policy["approved_tasks"]),
                "BAD_APPROVED_TASKS")
        require(type(policy["allowed_ops"]) is list
                and set(policy["allowed_ops"]).issubset(OPS)
                and len(policy["allowed_ops"]) == len(set(policy["allowed_ops"])),
                "BAD_ALLOWED_OPS")
        require(type(policy["repo"]) is str
                and REPO.fullmatch(policy["repo"]) is not None
                and type(policy["branch"]) is str
                and BRANCH.fullmatch(policy["branch"]) is not None
                and ".." not in policy["branch"]
                and not policy["branch"].endswith(("/", ".lock")),
                "BAD_GIT_SCOPE")
        _validated_location(self.root, policy["write_prefix"])
        self.policy = policy

    def snapshot(self) -> dict:
        overview = _regular_file(self.session / "_overview.md", self.root)
        resolution = resolve_plan_phase(self.session)  # ORIGINAL authoritative resolver
        plan = _regular_file(resolution.plan_path, self.root).decode("utf-8")
        require(plan_fingerprint(plan) == self.policy["plan_fingerprint"],
                "APPROVED_PLAN_CHANGED")
        phases = validate_plan_contract(plan)
        ids = []
        for phase in phases:
            for t in phase.tasks:
                identifier = t.text.split(":", 1)[0].strip()
                require(TASK.fullmatch(identifier) is not None, "TASK_ID_INVALID")
                ids.append(identifier)
        require(ids == self.policy["approved_tasks"], "TASK_LIST_CHANGED")
        phase = select_active_phase(phases)
        task = None
        if phase is not None:
            item = next((t for t in phase.tasks if not t.complete), None)
            require(item is not None, "ORIGINAL_RESOLVER_INCONSISTENT")
            task = item.text.split(":", 1)[0].strip()
            require(not resolution.all_complete, "ORIGINAL_RESOLVER_INCONSISTENT")
        else:
            require(resolution.all_complete, "ORIGINAL_RESOLVER_INCONSISTENT")
        return {"task": task, "all_complete": resolution.all_complete,
                "plan_sha256": hashlib.sha256(plan.encode("utf-8")).hexdigest(),
                "overview_sha256": hashlib.sha256(overview).hexdigest(),
                "approval_id": self.policy["approval_id"]}

    def authorize(self, operation: str, *, task: str | None = None,
                  relative_path: str | None = None, repo: str | None = None,
                  branch: str | None = None, sha256: str | None = None,
                  qa: object = None, reviewed_commit_sha: str | None = None,
                  actual_commit_sha: str | None = None,
                  source_phase: str | None = None,
                  target_phase: str | None = None,
                  signal: str = "continue") -> dict:
        require(type(operation) is str and operation in self.policy["allowed_ops"],
                "OP_NOT_APPROVED")
        current = self.snapshot()
        if operation == "status":
            return {"allowed": True, "operation": "status", **current}
        require(not current["all_complete"], "APPROVED_PLAN_COMPLETE_STOP")
        require(type(task) is str and task == current["task"],
                "UNAPPROVED_OR_UNSELECTED_TASK")
        if operation == "write_source":
            p = _validated_location(self.root, relative_path)
            prefix = _validated_location(self.root, self.policy["write_prefix"])
            require(p != prefix and p.is_relative_to(prefix), "WRITE_OUTSIDE_APPROVED_SCOPE")
        if operation in ("git_commit", "git_push"):
            require(type(repo) is str and repo == self.policy["repo"]
                    and type(branch) is str and branch == self.policy["branch"],
                    "GIT_TARGET_UNAPPROVED")
            _qa_proved(qa, sha256)
            if operation == "git_push":
                require(type(reviewed_commit_sha) is str
                        and GIT_SHA.fullmatch(reviewed_commit_sha) is not None
                        and actual_commit_sha == reviewed_commit_sha,
                        "UNREVIEWED_COMMIT")
        if operation == "phase_transition":
            require(get_phase_config(source_phase) is not None
                    and type(target_phase) is str, "UNKNOWN_PHASE")
            allowed, _ = validate_transition(source_phase, target_phase)
            valid_signal, _ = validate_signal_for_phase(source_phase, signal)
            require(allowed and valid_signal, "ORIGINAL_PHASE_VALIDATION_FAILED")
            if target_phase in ("pr-readiness", "done"):
                require(False, "EXTERNAL_RELEASE_APPROVAL_REQUIRED")
            _qa_proved(qa, sha256)
        return {"allowed": True, "operation": operation, "task": task,
                "approval_id": self.policy["approval_id"],
                "plan_sha256": current["plan_sha256"],
                "repo": repo if operation.startswith("git_") else None,
                "branch": branch if operation.startswith("git_") else None,
                "never_force_push": operation == "git_push"}

