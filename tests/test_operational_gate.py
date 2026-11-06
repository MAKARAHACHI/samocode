#!/usr/bin/env python3
"""Offline regression checks of the existing SAMOCODE resolver + single guard."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from worker.operational_gate import (
    OperationalGate, Denied, canonical_bytes, digest, plan_fingerprint
)

PLAN = """# Authorized work
## Implementation Phases
### Phase 1: Implementation
**Profile:** `standard`
- [ ] A: build safe review
- [ ] B: integrate release gate
"""
OVERVIEW = """# Operational session
## Status
Phase: implementation
Iteration: 1
Blocked: no

## Plans
- plan.md
"""


class OperationalGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="samocode-gate-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.session = self.root / "session"
        self.session.mkdir()
        (self.session / "plan.md").write_text(PLAN)
        (self.session / "_overview.md").write_text(OVERVIEW)
        (self.root / "src").mkdir()
        self.policy = {
            "schema": "samocode.owner.approval.v1",
            "approval_id": "operator-approved-001",
            "task_id": "76a33adbd957",
            "plan_fingerprint": plan_fingerprint(PLAN),
            "approved_tasks": ["A", "B"],
            "allowed_ops": ["status", "next_task", "write_source",
                            "run_tests", "git_commit", "git_push",
                            "phase_transition"],
            "write_prefix": "src",
            "repo": "MAKARAHACHI/samocode",
            "branch": "samocode-operational-integration-20261106",
        }

    def gate(self):
        payload = canonical_bytes(self.policy)
        return OperationalGate(self.root, self.session, payload,
                               hashlib.sha256(payload).hexdigest())

    def qa(self, **changes):
        source = "f" * 64
        testing = {"role": "testing-agent", "run_id": "testing-5",
                   "tests_passed": 20, "exit_code": 0,
                   "source_sha256": source}
        quality = {"role": "quality-agent", "run_id": "quality-6",
                   "tests_passed": 20, "exit_code": 0,
                   "source_sha256": source,
                   "testing_evidence_sha256": digest(testing)}
        result = {"testing": testing, "quality": quality}
        for k, v in changes.items():
            if k.startswith("t_"):
                result["testing"][k[2:]] = v
            elif k.startswith("q_"):
                result["quality"][k[2:]] = v
            else:
                raise AssertionError(k)
        return result

    def git(self, **kw):
        data = {"task": "A", "repo": self.policy["repo"],
                "branch": self.policy["branch"], "sha256": "f" * 64,
                "qa": self.qa()}
        data.update(kw)
        return data

    def test_original_resolver_selects_a(self):
        self.assertEqual(self.gate().snapshot()["task"], "A")

    def test_authorized_next_task(self):
        self.assertTrue(self.gate().authorize("next_task", task="A")["allowed"])

    def test_next_task_b_cannot_start_early(self):
        with self.assertRaises(Denied):
            self.gate().authorize("next_task", task="B")

    def test_no_unlimited_work_after_complete(self):
        (self.session / "plan.md").write_text(PLAN.replace("[ ]", "[x]"))
        self.assertTrue(self.gate().snapshot()["all_complete"])
        with self.assertRaisesRegex(Denied, "COMPLETE_STOP"):
            self.gate().authorize("next_task", task="B")

    def test_selected_next_b_after_a_complete(self):
        (self.session / "plan.md").write_text(PLAN.replace("- [ ] A:", "- [x] A:"))
        self.assertEqual(self.gate().snapshot()["task"], "B")
        self.assertTrue(self.gate().authorize("next_task", task="B")["allowed"])

    def test_plan_description_edit_denied(self):
        (self.session / "plan.md").write_text(PLAN.replace("safe review", "unapproved exploit"))
        with self.assertRaisesRegex(Denied, "APPROVED_PLAN_CHANGED"):
            self.gate().snapshot()

    def test_plan_extra_task_denied(self):
        (self.session / "plan.md").write_text(PLAN + "- [ ] C: extra task\n")
        with self.assertRaisesRegex(Denied, "APPROVED_PLAN_CHANGED"):
            self.gate().snapshot()

    def test_plan_task_reordering_denied(self):
        (self.session / "plan.md").write_text(PLAN.replace(
            "- [ ] A: build safe review\n- [ ] B: integrate release gate",
            "- [ ] B: integrate release gate\n- [ ] A: build safe review"))
        with self.assertRaises(Denied):
            self.gate().snapshot()

    def test_overview_missing_denied(self):
        (self.session / "_overview.md").unlink()
        with self.assertRaises((Denied, ValueError)):
            self.gate().snapshot()

    def test_unknown_operation_denied(self):
        with self.assertRaises(Denied):
            self.gate().authorize("unbounded_execute", task="A")

    def test_force_push_not_exposed(self):
        with self.assertRaises(Denied):
            self.gate().authorize("force_push", task="A")

    def test_status_is_read_only(self):
        before=(self.session / "plan.md").read_bytes()
        state=self.gate().authorize("status")
        self.assertEqual(state["task"], "A")
        self.assertEqual(before, (self.session / "plan.md").read_bytes())

    def test_approval_sha_is_externally_pinned(self):
        payload=canonical_bytes(self.policy)
        with self.assertRaisesRegex(Denied, "UNPINNED_APPROVAL"):
            OperationalGate(self.root, self.session, payload, "0"*64)

    def test_malformed_policy(self):
        with self.assertRaisesRegex(Denied, "MALFORMED_APPROVAL"):
            OperationalGate(self.root,self.session,b"{oops",
                            hashlib.sha256(b"{oops").hexdigest())

    def test_extra_policy_field_is_denied(self):
        self.policy["extra_permission"]="yes"
        with self.assertRaisesRegex(Denied, "BAD_POLICY_FIELDS"):
            self.gate()

    def test_duplicate_tasks_in_approval_denied(self):
        self.policy["approved_tasks"]=["A","A"]
        with self.assertRaisesRegex(Denied, "BAD_APPROVED_TASKS"):
            self.gate()

    def test_duplicate_operations_denied(self):
        self.policy["allowed_ops"].append("git_push")
        with self.assertRaisesRegex(Denied, "BAD_ALLOWED_OPS"):
            self.gate()

    def test_relative_session_outside_root_denied(self):
        with self.assertRaisesRegex(Denied, "INVALID_SESSION"):
            payload=canonical_bytes(self.policy)
            OperationalGate(self.root, Path("session"), payload,
                            hashlib.sha256(payload).hexdigest())

    def test_source_write_inside_approved_directory(self):
        self.assertTrue(self.gate().authorize("write_source",task="A",
                          relative_path="src/a/new_module.py")["allowed"])

    def test_source_write_outside_approved_directory_denied(self):
        with self.assertRaisesRegex(Denied, "WRITE_OUTSIDE_APPROVED_SCOPE"):
            self.gate().authorize("write_source",task="A",
                                  relative_path="secret.env")

    def test_source_write_plan_denied(self):
        with self.assertRaises(Denied):
            self.gate().authorize("write_source",task="A",
                                  relative_path="session/plan.md")

    def test_source_path_traversal_denied(self):
        with self.assertRaisesRegex(Denied, "PATH_TRAVERSAL"):
            self.gate().authorize("write_source",task="A",
                                  relative_path="src/../../escape.py")

    def test_source_absolute_path_denied(self):
        with self.assertRaisesRegex(Denied,"PATH_TRAVERSAL"):
            self.gate().authorize("write_source",task="A",
                                  relative_path="/etc/passwd")

    def test_source_symlink_denied(self):
        (self.root / "src" / "unsafe").symlink_to(self.root / "session",
                                                   target_is_directory=True)
        with self.assertRaisesRegex(Denied,"SYMLINK_PATH"):
            self.gate().authorize("write_source",task="A",
                                  relative_path="src/unsafe/mutate.py")

    def test_git_wrong_repository_denied(self):
        with self.assertRaisesRegex(Denied, "GIT_TARGET_UNAPPROVED"):
            self.gate().authorize("git_commit", **self.git(repo="Yuvasee/samocode"))

    def test_git_wrong_branch_denied(self):
        with self.assertRaisesRegex(Denied, "GIT_TARGET_UNAPPROVED"):
            self.gate().authorize("git_commit", **self.git(branch="master"))

    def test_git_commit_with_qa_is_authorized(self):
        self.assertTrue(self.gate().authorize("git_commit",
                                              **self.git())["allowed"])

    def test_push_without_reviewed_commit_denied(self):
        with self.assertRaisesRegex(Denied, "UNREVIEWED_COMMIT"):
            self.gate().authorize("git_push", **self.git())

    def test_push_only_matching_reviewed_commit(self):
        commit="a" * 40
        self.assertTrue(self.gate().authorize("git_push",
            **self.git(reviewed_commit_sha=commit,
                       actual_commit_sha=commit))["allowed"])

    def test_push_commit_divergence_denied(self):
        with self.assertRaisesRegex(Denied, "UNREVIEWED_COMMIT"):
            self.gate().authorize("git_push",
                **self.git(reviewed_commit_sha="a"*40,
                           actual_commit_sha="b"*40))

    def test_git_qa_bool_exit_denied(self):
        with self.assertRaises(Denied):
            self.gate().authorize("git_commit",**self.git(
                qa=self.qa(t_exit_code=False)))

    def test_git_qa_bool_count_denied(self):
        with self.assertRaises(Denied):
            self.gate().authorize("git_commit",**self.git(
                qa=self.qa(q_tests_passed=True)))

    def test_git_qa_distinct_role_required(self):
        with self.assertRaises(Denied):
            self.gate().authorize("git_commit",**self.git(
                qa=self.qa(q_run_id="testing-5")))

    def test_git_qa_hash_drift_denied(self):
        with self.assertRaises(Denied):
            self.gate().authorize("git_commit",**self.git(
                qa=self.qa(q_source_sha256="0"*64)))

    def test_git_qa_binding_denied(self):
        with self.assertRaises(Denied):
            self.gate().authorize("git_commit",**self.git(
                qa=self.qa(q_testing_evidence_sha256="0"*64)))

    def test_git_qa_missing_denied(self):
        with self.assertRaises(Denied):
            self.gate().authorize("git_commit",**self.git(qa=None))

    def test_original_phase_rules_valid(self):
        r=self.gate().authorize("phase_transition",task="A",
            source_phase="implementation", target_phase="testing",
            sha256="f"*64, qa=self.qa())
        self.assertTrue(r["allowed"])

    def test_original_phase_rules_invalid(self):
        with self.assertRaisesRegex(Denied,"ORIGINAL_PHASE_VALIDATION_FAILED"):
            self.gate().authorize("phase_transition",task="A",
                source_phase="implementation", target_phase="done",
                sha256="f"*64, qa=self.qa())

    def test_release_never_done_without_external_review(self):
        with self.assertRaisesRegex(Denied,"EXTERNAL_RELEASE_APPROVAL_REQUIRED"):
            self.gate().authorize("phase_transition",task="A",
                source_phase="testing", target_phase="pr-readiness",
                sha256="f"*64, qa=self.qa())

    def test_missing_qa_on_phase_denied(self):
        with self.assertRaises(Denied):
            self.gate().authorize("phase_transition",task="A",
                source_phase="implementation",target_phase="testing",
                sha256="f"*64,qa=None)

    def test_unknown_phase_denied(self):
        with self.assertRaisesRegex(Denied,"UNKNOWN_PHASE"):
            self.gate().authorize("phase_transition",task="A",
                source_phase="fake",target_phase="testing",qa=self.qa(),
                sha256="f"*64)


if __name__ == "__main__":
    unittest.main(verbosity=2)

