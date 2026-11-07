"""Saved stdlib tests for strict release proof."""
import copy
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import strict_release_proof as module

PATHS = [
    "acceptance/strict_run_receipt.py", "tests/test_strict_run_receipt.py",
    "acceptance/strict_release_proof.py", "tests/test_strict_release_proof.py",
]
SHA = "a" * 64
COMMIT = "b" * 40
class SubStr(str): pass
class SubList(list): pass
def receipt(role, run):
    return dict(role=role, run_id=run, exit_code=0, tests_passed=12, source_sha256=SHA)
def proof():
    return [receipt("testing-agent", "test-1"), receipt("quality-agent", "quality-2"), COMMIT, COMMIT, list(PATHS)]
class ProofTests(unittest.TestCase):
    def call(self, args):
        return module.verify_release_proof(*args)
    def test_valid(self):
        self.assertEqual(self.call(proof())["status"], "RELEASE_PROOF_VALID")
    def test_actual_A_import_and_use(self):
        validator, phases = module._dependencies()
        self.assertEqual(validator(proof()[0])["run_id"], "test-1")
        self.assertTrue(phases.validate_transition("testing", "quality")[0])
    def test_wrong_testing_role(self):
        a=proof(); a[0]["role"]="quality-agent"
        with self.assertRaises(ValueError): self.call(a)
    def test_wrong_quality_role(self):
        a=proof(); a[1]["role"]="testing-agent"
        with self.assertRaises(ValueError): self.call(a)
    def test_same_run_ids(self):
        a=proof(); a[1]["run_id"]="test-1"
        with self.assertRaises(ValueError): self.call(a)
    def test_source_hash_mismatch(self):
        a=proof(); a[1]["source_sha256"]="c"*64
        with self.assertRaises(ValueError): self.call(a)
    def test_A_rejects_invalid_receipt(self):
        a=proof(); a[0]["tests_passed"]=11
        with self.assertRaises(ValueError): self.call(a)
    def test_receipt_strict_dict(self):
        a=proof(); a[0]=dict(a[0]); a[0]=type("SubDict",(dict,),{})(a[0])
        with self.assertRaises(TypeError): self.call(a)
    def test_commit_mismatch(self):
        a=proof(); a[3]="c"*40
        with self.assertRaises(ValueError): self.call(a)
    def test_commit_bad_format(self):
        for value in ("A"*40, "a"*39, "g"*40):
            a=proof(); a[2]=value
            with self.subTest(value=value), self.assertRaises(ValueError): self.call(a)
    def test_commit_type_strict(self):
        for value in (SubStr(COMMIT), None, 1):
            a=proof(); a[3]=value
            with self.subTest(value=value), self.assertRaises(TypeError): self.call(a)
    def test_duplicate_paths(self):
        a=proof(); a[4][3]=a[4][0]
        with self.assertRaises(ValueError): self.call(a)
    def test_extra_and_missing_paths(self):
        for paths in (PATHS+["extra"], PATHS[:3]):
            a=proof(); a[4]=paths
            with self.subTest(paths=paths), self.assertRaises(ValueError): self.call(a)
    def test_path_type_strict(self):
        for paths in (SubList(PATHS), set(PATHS)):
            a=proof(); a[4]=paths
            with self.assertRaises(TypeError): self.call(a)
        a=proof(); a[4][0]=SubStr(a[4][0])
        with self.assertRaises(TypeError): self.call(a)
    def test_tuple_paths(self):
        a=proof(); a[4]=tuple(reversed(PATHS))
        self.assertEqual(self.call(a)["committed_paths"],sorted(PATHS))
    def test_original_transition_rejection(self):
        a=proof(); _, phases=module._dependencies()
        with patch.object(phases,"validate_transition",return_value=(False,"invalid")):
            with self.assertRaises(ValueError): self.call(a)
    def test_original_signal_rejection(self):
        a=proof(); _, phases=module._dependencies()
        with patch.object(phases,"validate_signal_for_phase",return_value=(False,"invalid")):
            with self.assertRaises(ValueError): self.call(a)
    def test_immutable_inputs_and_fresh_result(self):
        a=proof(); before=copy.deepcopy(a)
        x=self.call(a); y=self.call(a)
        self.assertEqual(a,before); self.assertEqual(x,y); self.assertIsNot(x,y)
        x["committed_paths"].clear()
        self.assertEqual(a,before)
if __name__=="__main__":
    unittest.main()

