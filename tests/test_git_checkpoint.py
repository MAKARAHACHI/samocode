#!/usr/bin/env python3
"""No-network tests for reviewed Git push and rollback SHA contract."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from worker.operational_gate import OperationalGate, canonical_bytes, digest, plan_fingerprint
from worker.git_checkpoint import ReleaseBlocked, publish_once, verify_reviewed_head

PLAN="""# Authorized operational task
## Implementation Phases
### Phase 1: Implementation
**Profile:** `standard`
- [ ] A: implement verified gate
- [ ] B: validate and publish
"""
OVERVIEW="# owner\n## Plans\n- plan.md\n"
HEAD="a"*40


class FakeGit:
    def __init__(self, head=HEAD, remote="https://github.com/MAKARAHACHI/samocode.git",
                 dirty=False, failure=False):
        self.head=head;self.remote=remote;self.dirty=dirty;self.failure=failure
        self.calls=[]
    def __call__(self, args, **kw):
        self.calls.append(list(args))
        if args[:3]==["git","rev-parse","--verify"]:
            out=self.head
        elif args[:3]==["git","remote","get-url"]:
            out=self.remote
        elif args[:3]==["git","status","--porcelain"]:
            out=" M file.py" if self.dirty else ""
        elif args[:3]==["git","push","--porcelain"]:
            out="To github.com:MAKARAHACHI/samocode\n * [new branch] HEAD -> branch"
        else:
            raise AssertionError("unexpected Git command: "+repr(args))
        return SimpleNamespace(returncode=1 if self.failure else 0,
                               stdout=out,stderr="")


class GitCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="samocode-git-check-")
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        self.session=self.root/"session"; self.session.mkdir()
        (self.session/"plan.md").write_text(PLAN)
        (self.session/"_overview.md").write_text(OVERVIEW)
        (self.root/"src").mkdir()
        self.checkout=self.root/"checkout";self.checkout.mkdir()
        (self.checkout/"worker").mkdir()
        self.source=self.checkout/"worker"/"operational_gate.py"
        self.source.write_text("def approved(): return True\n")
        self.sha=hashlib.sha256(self.source.read_bytes()).hexdigest()
        p={
          "schema":"samocode.owner.approval.v1",
          "approval_id":"git-test-approval",
          "task_id":"76a33adbd957",
          "plan_fingerprint":plan_fingerprint(PLAN),
          "approved_tasks":["A","B"],
          "allowed_ops":["status","next_task","git_push","git_commit","write_source","run_tests"],
          "write_prefix":"src",
          "repo":"MAKARAHACHI/samocode",
          "branch":"samocode-operational-integration-20261106"
        }
        data=canonical_bytes(p)
        self.gate=OperationalGate(self.root,self.session,data,hashlib.sha256(data).hexdigest())
        testing={"role":"testing-agent","run_id":"r1",
                 "source_sha256":self.sha,"tests_passed":14,"exit_code":0}
        quality={"role":"quality-agent","run_id":"r2",
                 "source_sha256":self.sha,"tests_passed":14,"exit_code":0,
                 "testing_evidence_sha256":digest(testing)}
        self.qa={"testing":testing,"quality":quality}
        self.git=FakeGit()

    def inspect(self, **updates):
        data=dict(task="A", source_path="worker/operational_gate.py",
                  source_sha256=self.sha, qa=self.qa, expected_head=HEAD,
                  runner=self.git)
        data.update(updates)
        return verify_reviewed_head(self.gate,self.checkout,**data)

    def publish(self, **updates):
        data=dict(task="A",source_path="worker/operational_gate.py",
                  source_sha256=self.sha,qa=self.qa,expected_head=HEAD,
                  ledger_path=self.root/"once.json",runner=self.git)
        data.update(updates)
        return publish_once(self.gate,self.checkout,**data)

    def test_git_ready_and_branch_pinned(self):
        x=self.inspect()
        self.assertEqual(x["status"],"REVIEWED_HEAD_READY")
        self.assertEqual(x["branch"],"samocode-operational-integration-20261106")

    def test_git_argv_contains_no_force(self):
        argv=self.inspect()["git_push_argv"]
        self.assertEqual(argv,["git","push","--porcelain","origin",
                               "HEAD:refs/heads/samocode-operational-integration-20261106"])
        self.assertNotIn("--force",argv)

    def test_git_non_clean_refused(self):
        self.git.dirty=True
        with self.assertRaisesRegex(ReleaseBlocked,"UNCLEAN_WORKTREE"):
            self.inspect()

    def test_wrong_origin_refused(self):
        self.git.remote="https://github.com/Yuvasee/samocode.git"
        with self.assertRaisesRegex(ReleaseBlocked,"WRONG_GIT_REMOTE"):
            self.inspect()

    def test_remote_with_userinfo_refused(self):
        self.git.remote="https://token@github.com/MAKARAHACHI/samocode.git"
        with self.assertRaisesRegex(ReleaseBlocked,"WRONG_GIT_REMOTE"):
            self.inspect()

    def test_wrong_head_refused(self):
        self.git.head="b"*40
        with self.assertRaisesRegex(ReleaseBlocked,"HEAD_CHANGED_SINCE_REVIEW"):
            self.inspect()

    def test_changed_source_denied(self):
        self.source.write_text("def compromised(): return True\n")
        with self.assertRaisesRegex(ReleaseBlocked,"SOURCE_CHANGED_SINCE_QA"):
            self.inspect()

    def test_missing_source_denied(self):
        self.source.unlink()
        with self.assertRaisesRegex(ReleaseBlocked,"UNTRUSTED_REVIEWED_SOURCE"):
            self.inspect()

    def test_source_traversal_denied(self):
        with self.assertRaisesRegex(ReleaseBlocked,"UNTRUSTED_SOURCE_PATH"):
            self.inspect(source_path="../plan.md")

    def test_unapproved_task_denied(self):
        with self.assertRaises(ValueError):
            self.inspect(task="B")

    def test_missing_qa_denied(self):
        with self.assertRaises(ValueError):
            self.inspect(qa={})

    def test_checkout_not_absolute_denied(self):
        with self.assertRaisesRegex(ReleaseBlocked,"INVALID_CHECKOUT"):
            verify_reviewed_head(self.gate,Path("checkout"),"A",
                                 "worker/operational_gate.py",self.sha,self.qa,HEAD,
                                 runner=self.git)

    def test_ledger_success_and_remote_readback_required(self):
        receipt=self.publish()
        self.assertEqual(receipt["status"],"PUSH_COMMAND_EXIT0")
        self.assertTrue(receipt["receipt_requires_remote_readback"])
        self.assertTrue((self.root/"once.json").is_file())
        self.assertTrue((self.root/"once.json.success").is_file())
        self.assertEqual(len([x for x in self.git.calls if x[:2]==["git","push"]]),1)

    def test_push_is_one_shot(self):
        self.publish()
        with self.assertRaisesRegex(ReleaseBlocked,"PUSH_LEDGER_NOT_FRESH"):
            self.publish()
        self.assertEqual(len([x for x in self.git.calls if x[:2]==["git","push"]]),1)

    def test_git_operation_failed_not_retried(self):
        self.git.failure=True
        with self.assertRaisesRegex(ReleaseBlocked,"GIT_OPERATION_FAILED_NO_RETRY"):
            self.publish()
        self.assertFalse((self.root/"once.json").exists())
        self.assertEqual(len([x for x in self.git.calls if x[:2]==["git","push"]]),0)

    def test_ledger_directory_missing_denied(self):
        with self.assertRaisesRegex(ReleaseBlocked,"PUSH_LEDGER_NOT_FRESH"):
            self.publish(ledger_path=self.root/"missing"/"once.json")

    def test_no_runtime_mutation_during_preflight(self):
        self.inspect()
        self.assertFalse((self.root/"once.json").exists())

    def test_allow_ssh_origin_in_own_fork(self):
        self.git.remote="git@github.com:MAKARAHACHI/samocode.git"
        self.assertEqual(self.inspect()["status"],"REVIEWED_HEAD_READY")

    def test_reject_any_git_command_injection_from_branch(self):
        p=self.gate.policy
        self.assertEqual(p["branch"],"samocode-operational-integration-20261106")
        self.assertNotIn(";",self.inspect()["git_push_argv"][-1])

    def test_git_failure_on_push_leaves_attempt_intent(self):
        class PushFailure(FakeGit):
            def __call__(self,args,**kw):
                x=super().__call__(args,**kw)
                if args[:2]==["git","push"]:
                    x.returncode=1
                return x
        self.git=PushFailure()
        with self.assertRaisesRegex(ReleaseBlocked,"GIT_OPERATION_FAILED_NO_RETRY"):
            self.publish()
        self.assertTrue((self.root/"once.json").exists())
        self.assertFalse((self.root/"once.json.success").exists())
        self.assertEqual(len([x for x in self.git.calls if x[:2]==["git","push"]]),1)
        with self.assertRaises(ReleaseBlocked):
            self.publish()


if __name__=="__main__":
    unittest.main(verbosity=2)

