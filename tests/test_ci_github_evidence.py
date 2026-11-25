import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest
from urllib.parse import urlsplit

from tools.ci_github_evidence import (
    ExecutionInputs, TrustedExecutionReceipt, read_execution_verification,
    read_pr_verification, read_run_verification,
)
from tools.devflow_mcp_core import GitHubReader, DevflowMCPError

REPO = "kinoko34077/testapp"
HEAD = "a" * 40
BASE = "b" * 40
MERGE = "c" * 40
TREE = "d" * 40
PR = {
    "number": 7, "html_url": f"https://github.com/{REPO}/pull/7",
    "state": "open", "merged": False, "merge_commit_sha": MERGE,
    "body": "- Owning-Issue: #1",
    "head": {"sha": HEAD}, "base": {
        "sha": BASE, "ref": "main", "repo": {"full_name": REPO, "default_branch": "main"},
    },
}
COMMIT = {"sha": MERGE, "tree": {"sha": TREE},
          "parents": [{"sha": BASE}, {"sha": HEAD}]}
RUN = {"id": 42, "workflow_id": 13, "run_attempt": 2, "head_sha": HEAD,
       "repository": {"full_name": REPO}, "path": ".github/workflows/ci.yml",
       "event": "pull_request", "status": "completed", "conclusion": "success",
       "pull_requests": [], "head_commit": {"id": HEAD, "tree_id": "e" * 40}}
JOB = {"id": 10, "run_id": 42, "run_attempt": 1, "head_sha": HEAD,
       "name": "verify", "status": "completed", "conclusion": "success"}


class ReaderFixture:
    def __init__(self):
        self.pr = copy.deepcopy(PR)
        self.commit = copy.deepcopy(COMMIT)
        self.run = copy.deepcopy(RUN)
        self.jobs = {"total_count": 1, "jobs": [copy.deepcopy(JOB)]}
        self.calls = []
        self.run_reads = 0
        self.changed_run = None
        self.failed = set()
        self.reader = GitHubReader(transport=self.get)

    def get(self, url, headers):
        path = urlsplit(url).path
        self.calls.append(path)
        if path in self.failed:
            raise DevflowMCPError("read failed")
        suffix = path.removeprefix("/repos/" + REPO + "/")
        if suffix == "pulls/7":
            return self.pr
        if suffix == "git/commits/" + MERGE:
            return self.commit
        if suffix == "actions/runs/42/jobs":
            self.query = urlsplit(url).query
            return self.jobs
        if suffix == "actions/runs/42":
            self.run_reads += 1
            return self.changed_run if self.run_reads > 1 and self.changed_run is not None else self.run
        raise AssertionError(path)

    def read_pr(self):
        return read_pr_verification(self.reader, REPO, 7)

    def read_run(self):
        return read_run_verification(self.reader, REPO, 42)


class NativeEvidenceTests(unittest.TestCase):
    def test_live_metadata_and_candidate_are_separate(self):
        f = ReaderFixture()
        result = f.read_pr()
        self.assertEqual(result["metadata"]["status"], "VALID")
        self.assertEqual(result["candidate"]["tree_sha"], TREE)
        self.assertEqual(result["candidate"]["kind"], "SYNTHETIC_MERGE")
        self.assertIsNone(result["tested_tree"])
        self.assertEqual(len(f.calls), 2)
        original_digest = result["metadata"]["input_digest"]
        f.pr["body"] = "unrelated text"
        edited = f.read_pr()
        self.assertEqual(edited["metadata"]["status"], "INVALID")
        self.assertNotEqual(edited["metadata"]["input_digest"], original_digest)
        self.assertEqual(edited["candidate"], result["candidate"])

    def test_wrong_candidate_parent_cannot_prove_tree(self):
        f = ReaderFixture()
        f.commit["parents"][0]["sha"] = "f" * 40
        r = f.read_pr()
        self.assertEqual(r["candidate"]["reason"], "CANDIDATE_PARENT_MISMATCH")
        self.assertEqual(r["metadata"]["status"], "VALID")

    def test_candidate_failure_preserves_metadata(self):
        f = ReaderFixture()
        f.failed.add(f"/repos/{REPO}/git/commits/{MERGE}")
        r = f.read_pr()
        self.assertEqual(r["candidate"]["status"], "UNKNOWN")
        self.assertEqual(r["metadata"]["status"], "VALID")

    def test_merged_commit_is_not_synthetic(self):
        f = ReaderFixture()
        f.pr.update(state="closed", merged=True)
        f.commit["parents"] = [{"sha": BASE}]
        r = f.read_pr()
        self.assertEqual(r["candidate"]["kind"], "MERGED_COMMIT")
        self.assertIsNone(r["tested_tree"])

    def test_wrong_pr_repository_rejected(self):
        f = ReaderFixture()
        f.pr["base"]["repo"]["full_name"] = "other/repo"
        self.assertEqual(f.read_pr()["reason"], "PR_IDENTITY_UNPROVEN")
        self.assertEqual(len(f.calls), 1)

    def test_native_run_success_does_not_bind_actual_checkout(self):
        f = ReaderFixture()
        r = f.read_run()
        self.assertEqual(r["native_run_decision"]["action"], "REUSE_CANDIDATE")
        self.assertEqual(r["jobs"][0]["native_decision"]["action"], "REUSE_CANDIDATE")
        self.assertEqual(r["jobs"][0]["attempt"], 1)
        self.assertEqual(r["event_head_tree"], "e" * 40)
        self.assertIsNone(r["tested_tree"])
        self.assertEqual(r["code_equivalence"]["status"], "UNKNOWN")
        self.assertIn("filter=latest", f.query)
        self.assertEqual(len(f.calls), 3)

    def test_current_attempt_drift(self):
        f = ReaderFixture()
        f.changed_run = dict(f.run, run_attempt=3)
        r = f.read_run()
        self.assertEqual(r["reason"], "RUN_CHANGED_DURING_READ")
        self.assertNotIn("native_run_decision", r)
        self.assertEqual(r["jobs"], [])

    def test_non_success_and_active_are_not_success(self):
        for status, conclusion, action in (
            ("completed", "failure", "RUN"), ("completed", "skipped", "RUN"),
            ("completed", "cancelled", "RUN"), ("in_progress", None, "WAIT"),
        ):
            with self.subTest(status=status, conclusion=conclusion):
                f = ReaderFixture()
                f.run.update(status=status, conclusion=conclusion)
                f.jobs["jobs"][0].update(status=status, conclusion=conclusion)
                r = f.read_run()
                self.assertEqual(r["native_run_decision"]["action"], action)
                self.assertEqual(r["jobs"][0]["native_decision"]["action"], action)

    def test_invalid_and_partial_job_inventory(self):
        for changes in ({"total_count": 2}, {"total_count": True}, {"jobs": None}):
            with self.subTest(changes=changes):
                f = ReaderFixture()
                f.jobs.update(changes)
                r = f.read_run()
                self.assertEqual(r["status"], "PARTIAL")
                self.assertEqual(r["job_coverage"], "UNKNOWN")
                self.assertEqual(r["jobs"], [])
        for changes in ({"head_sha": BASE}, {"run_id": 43}, {"run_attempt": 3}):
            f = ReaderFixture()
            f.jobs["jobs"][0].update(changes)
            r = f.read_run()
            self.assertEqual(r["reason"], "JOB_IDENTITY_UNPROVEN")
            self.assertEqual(r["jobs"], [])

    def test_duplicate_job_id_rejected_but_distinct_matrix_jobs_allowed(self):
        f = ReaderFixture()
        f.jobs["total_count"] = 2
        f.jobs["jobs"].append(copy.deepcopy(JOB))
        self.assertEqual(f.read_run()["reason"], "JOB_IDENTITY_UNPROVEN")
        f.jobs["jobs"][1]["id"] = 11
        self.assertEqual(len(f.read_run()["jobs"]), 2)

    def test_read_failure_is_local(self):
        f = ReaderFixture()
        f.failed.add(f"/repos/{REPO}/actions/runs/42/jobs")
        r = f.read_run()
        self.assertEqual(r["status"], "PARTIAL")
        self.assertEqual(r["run"]["id"], 42)
        self.assertNotIn("native_run_decision", r)

    def test_invalid_identifiers_no_read(self):
        f = ReaderFixture()
        for value in (0, True, "42", -1):
            with self.assertRaises(DevflowMCPError):
                f.reader.get_action_run(REPO, value)
            with self.assertRaises(DevflowMCPError):
                f.reader.get_pull_request(REPO, value)
            with self.assertRaises(DevflowMCPError):
                f.reader.get_latest_action_jobs(REPO, value)
        with self.assertRaises(DevflowMCPError):
            f.reader.get_git_commit(REPO, "../main")
        self.assertEqual(f.calls, [])


class ExecutionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.f = ReaderFixture()
        self.now = datetime(2026, 11, 25, tzinfo=timezone.utc)
        self.inputs = ExecutionInputs(TREE, "1" * 64, "2" * 64, "3" * 64, "4" * 64)
        # The fixture stands in for a protected collector. The REST event head
        # deliberately differs from the actual tested checkout.
        self.receipt = TrustedExecutionReceipt(
            REPO, "code-verification", 42, 13, RUN["path"], RUN["event"],
            HEAD, 10, "verify", 1, MERGE, self.inputs,
            "trusted-host:fixture", self.now + timedelta(hours=1),
        )

    def read(self, required=None, receipt="default"):
        return read_execution_verification(
            self.f.reader, REPO, "code-verification",
            self.inputs if required is None else required,
            self.receipt if receipt == "default" else receipt, now=self.now,
        )

    def test_exact_job_and_actual_checkout_bind_measured_identity(self):
        result = self.read()
        self.assertEqual(result["status"], "OBSERVED")
        self.assertEqual(result["tested_tree"], TREE)
        self.assertEqual(result["checkout_sha"], MERGE)
        self.assertEqual(result["decision"]["action"], "REUSE_CANDIDATE")
        self.assertTrue(result["requires_source_revalidation"])
        self.assertEqual(len(self.f.calls), 4)

    def test_absent_or_untyped_receipt_is_not_inferred_from_success(self):
        for receipt in (None, {"run_id": 42, "tested_tree": TREE}):
            result = self.read(receipt=receipt)
            self.assertEqual(result["status"], "UNKNOWN")
            self.assertIsNone(result["tested_tree"])
            self.assertEqual(result["decision"]["action"], "HOLD")
        self.assertEqual(self.f.calls, [])

    def test_all_code_input_dimensions_must_match(self):
        for field, value in (
            ("tree_sha", "f" * 40), ("recipe_sha256", "f" * 64),
            ("environment_sha256", "f" * 64), ("dependencies_sha256", "f" * 64),
            ("policy_sha256", "f" * 64),
        ):
            with self.subTest(field=field):
                result = self.read(required=replace(self.inputs, **{field: value}))
                self.assertEqual(result["decision"]["action"], "RUN")
                self.assertEqual(result["tested_tree"], TREE)
        self.assertEqual(self.read(required=replace(self.inputs, recipe_sha256="unknown"))
                         ["status"], "UNKNOWN")

    def test_invalid_or_mismatched_run_job_or_guarantee_cannot_bind(self):
        for changes in (
            {"repository": "other/repo"}, {"guarantee": "metadata"},
            {"job_id": True}, {"job_id": 99}, {"job_attempt": 2},
            {"job_name": "different"}, {"workflow_id": 14},
            {"event_head_sha": BASE}, {"workflow_path": "other.yml"},
            {"event": "push"}, {"source_ref": ""}, {"checkout_sha": "../main"},
        ):
            with self.subTest(changes=changes):
                r = self.read(receipt=replace(self.receipt, **changes))
                self.assertEqual(r["status"], "UNKNOWN")
                self.assertIsNone(r["tested_tree"])
                self.assertEqual(r["decision"]["action"], "HOLD")

    def test_native_commit_tree_must_match_receipt_not_event_head(self):
        self.f.commit["tree"]["sha"] = "f" * 40
        r = self.read()
        self.assertEqual(r["reason"], "EXECUTION_CHECKOUT_TREE_MISMATCH")
        self.assertIsNone(r["tested_tree"])

    def test_missing_commit_or_partial_latest_attempt_is_unknown(self):
        self.f.failed.add(f"/repos/{REPO}/git/commits/{MERGE}")
        self.assertEqual(self.read()["reason"], "EXECUTION_CHECKOUT_UNAVAILABLE")
        self.f.failed.clear()
        self.f.jobs["total_count"] = 2
        self.assertEqual(self.read()["reason"], "NATIVE_EXECUTION_EVIDENCE_UNKNOWN")

    def test_expiry_and_native_nonsuccess_do_not_reuse(self):
        self.assertEqual(self.read(receipt=replace(self.receipt, valid_until=self.now))
                         ["decision"]["action"], "RUN")
        for status, conclusion, action in (
            ("completed", "failure", "RUN"), ("completed", "skipped", "RUN"),
            ("completed", "cancelled", "RUN"), ("in_progress", None, "WAIT"),
        ):
            with self.subTest(status=status, conclusion=conclusion):
                self.f.jobs["jobs"][0].update(status=status, conclusion=conclusion)
                self.assertEqual(self.read()["decision"]["action"], action)
        self.f.jobs["jobs"][0].update(status="completed", conclusion="success")
        self.f.run.update(status="completed", conclusion="failure")
        self.assertEqual(self.read()["decision"]["action"], "RUN")


if __name__ == "__main__":
    unittest.main()
