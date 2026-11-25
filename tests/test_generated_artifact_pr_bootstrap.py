"""No-network first-PR lifecycle, using the existing immutable writer core."""
import copy
import hashlib
import unittest

from tools.generated_artifact_packager import package_generated_bytes
from tools.generated_artifact_pr_bootstrap import (
    BootstrapRecipe, plan_new_pr, _execute_admitted_new_pr,
)
from tools.generated_artifact_writer import WritebackRejected
from tools.generated_artifact_contract import ArtifactRejected
from tests.test_generated_artifact_contract import fixture
from tests.test_generated_artifact_writer import FakeGitHub, HEAD, ROOT, DIST, NEW_TREE, NEW_HEAD


class BootstrapFake(FakeGitHub):
    def __init__(self, files):
        super().__init__(files)
        self.main = HEAD
        self.main_protected = True
        self.private = True
        self.ref = None
        self.prs = []
        self.lost_pr_response = False
        self.fail_pr = False
        self.move_after_commit = False

    def get(self, path):
        if path == "":
            return {"id": 7, "full_name": self.repository, "private": self.private,
                    "visibility": "private" if self.private else "public", "default_branch": "main"}
        if path == "/branches/main":
            return {"name":"main", "protected":self.main_protected, "commit":{"sha":self.main}}
        if path.startswith("/git/matching-refs/"):
            return [self.ref] if self.ref else []
        if path.startswith("/pulls?"):
            return self.prs
        if path.startswith("/branches/"):
            return {"name":self.ref["ref"].removeprefix("refs/heads/"),
                    "protected":False, "commit":{"sha":self.ref["object"]["sha"]}}
        if path == "/git/trees/" + ROOT:
            return {"truncated":False, "tree":[{"path":"dist","type":"tree","mode":"040000","sha":DIST}]}
        if path == "/git/trees/" + NEW_TREE:
            return {"truncated":False, "tree":[{"path":"dist","type":"tree","mode":"040000","sha":"1"*40}]}
        if path in ("/git/trees/"+DIST, "/git/trees/"+"1"*40):
            entries = self.first_blob_shas if path.endswith(DIST) else self.new_entries
            return {"truncated":False, "tree":[{"path":p.split("/")[1], "type":"blob","mode":"100644","sha":sha}
                                              for p,sha in sorted(entries.items())]}
        return super().get(path)

    def post(self, path, payload):
        if path == "/git/refs":
            self.calls.append(("POST",path))
            if self.ref:
                raise WritebackRejected("ref already exists")
            self.ref = {"ref":payload["ref"], "object":{"sha":payload["sha"]}}
            return copy.deepcopy(self.ref)
        if path == "/pulls":
            self.calls.append(("POST",path))
            if self.fail_pr:
                raise WritebackRejected("PR creation failed")
            if self.prs:
                raise WritebackRejected("duplicate PR")
            repo = {"id":7,"full_name":self.repository}
            self.prs = [{"number":1,"state":"open",
                         "head":{"ref":payload["head"],"sha":self.ref["object"]["sha"],"repo":repo},
                         "base":{"ref":payload["base"],"repo":repo}}]
            if self.lost_pr_response:
                raise WritebackRejected("response lost")
            return copy.deepcopy(self.prs[0])
        result = super().post(path,payload)
        if path == "/git/commits" and self.move_after_commit:
            self.main = "9"*40
        return result

    def patch(self, path, payload):
        raise AssertionError("bootstrap may not update any ref")


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        policy, _, _, blobs = fixture()
        self.recipe = BootstrapRecipe("kinoko34077/example",7,True,"fixture",
                                     tuple(sorted(blobs)),policy["limits"])
        self.api = BootstrapFake(blobs)
        self.files,self.archive = package_generated_bytes(list(self.recipe.paths),self.recipe.limits,blobs)

    def plan(self):
        return plan_new_pr(self.api,self.recipe,HEAD,self.files,self.archive)

    def execute(self):
        return _execute_admitted_new_pr(self.api,self.recipe,HEAD,self.files,self.archive)

    def test_dry_run_and_create_then_exact_replay(self):
        self.assertEqual(self.plan()["status"],"CREATE_BRANCH")
        self.assertFalse(self.plan()["writer_authorized"])
        self.assertEqual(self.api.mutation_count,0)
        self.assertEqual(self.execute()["status"],"PR_CREATED")
        n=self.api.mutation_count
        self.assertEqual(self.execute()["status"],"NO_OP_REPLAY")
        self.assertEqual(self.api.mutation_count,n)

    def test_resume_ref_created_but_pr_failed(self):
        self.api.fail_pr=True
        with self.assertRaises(WritebackRejected):
            self.execute()
        self.api.fail_pr=False
        self.assertEqual(self.plan()["status"],"CREATE_PR")
        n=self.api.mutation_count
        self.assertEqual(self.execute()["status"],"PR_CREATED")
        self.assertEqual(self.api.mutation_count,n+1)

    def test_lost_pr_response_resumes_without_duplicate(self):
        self.api.lost_pr_response=True
        with self.assertRaises(WritebackRejected):
            self.execute()
        n=self.api.mutation_count
        self.assertEqual(self.execute()["status"],"NO_OP_REPLAY")
        self.assertEqual(self.api.mutation_count,n)

    def test_unprotected_public_and_stale_main_fail_before_write(self):
        for attr,value in (("main_protected",False),("private",False),("main","9"*40)):
            with self.subTest(attr=attr):
                old=getattr(self.api,attr)
                setattr(self.api,attr,value)
                with self.assertRaises(WritebackRejected):
                    self.execute()
                self.assertEqual(self.api.mutation_count,0)
                setattr(self.api,attr,old)

    def test_main_moves_after_commit_no_ref_or_pr(self):
        self.api.move_after_commit=True
        with self.assertRaises(WritebackRejected):
            self.execute()
        self.assertIsNone(self.api.ref)
        self.assertEqual(self.api.prs,[])

    def test_mismatched_ref_and_closed_pr_fail_without_more_writes(self):
        self.execute()
        n=self.api.mutation_count
        self.api.prs[0]["state"]="closed"
        with self.assertRaises(WritebackRejected):
            self.execute()
        self.api.prs[0]["state"]="open"
        self.api.extra_diff=True
        with self.assertRaises(WritebackRejected):
            self.execute()
        self.assertEqual(self.api.mutation_count,n)

    def test_tampered_archive_rejected_before_writes(self):
        bad = copy.deepcopy(self.files)
        bad[0]["sha256"] = "0"*64
        with self.assertRaises(ArtifactRejected):
            _execute_admitted_new_pr(self.api,self.recipe,HEAD,bad,self.archive)
        self.assertEqual(self.api.mutation_count,0)

    def test_unchanged_source_requires_no_branch(self):
        self.api.first_blob_shas = {p: hashlib.sha1(v).hexdigest()
                                    for p,v in self.api.files.items()}
        self.api.objects.update({self.api.first_blob_shas[p]:v for p,v in self.api.files.items()})
        self.assertEqual(self.plan()["status"],"NO_OP")
        self.assertEqual(self.execute()["status"],"NO_OP")
        self.assertEqual(self.api.mutation_count,0)

    def test_branch_collision(self):
        self.api.ref={"ref":"refs/heads/unrelated","object":{"sha":NEW_HEAD}}
        with self.assertRaises(WritebackRejected):
            self.execute()
        self.assertEqual(self.api.mutation_count,0)

if __name__ == "__main__":
    unittest.main()
