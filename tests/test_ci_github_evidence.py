import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest
from urllib.parse import urlsplit

from tools.ci_github_evidence import (
    ExecutionInputs, FixedSourceRequirement, TrustedExecutionReceipt,
    read_execution_verification, read_fixed_source_verification,
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
        self.workflow_runs = None
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
        if suffix == "actions/workflows/13/runs":
            self.fixed_query = urlsplit(url).query
            return (self.workflow_runs if self.workflow_runs is not None
                    else {"total_count": 1, "workflow_runs": [self.run]})
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


class FixedSourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.f = ReaderFixture()
        self.f.run.update(
            head_sha=MERGE, event="push", head_branch="main",
            repository={"full_name": REPO, "id": 1234},
            head_repository={"full_name": REPO, "id": 1234},
        )
        self.f.jobs["jobs"][0]["head_sha"] = MERGE
        self.required = FixedSourceRequirement(
            REPO, 1234, "stable", "policy-1", MERGE, "main", 13,
            RUN["path"], ("verify",),
        )

    def read(self, required=None):
        return read_fixed_source_verification(
            self.f.reader, self.required if required is None else required,
        )

    def test_fixed_native_success_distinct_from_code_equivalence_and_authority(self):
        r = self.read()
        self.assertEqual(r["status"], "NATIVE_SOURCE_CANDIDATE")
        self.assertEqual(r["tree_sha"], TREE)
        self.assertEqual(r["commit"], MERGE)
        self.assertEqual(r["repository_id"], 1234)
        self.assertEqual(r["channel"], "stable")
        self.assertEqual(r["policy_revision"], "policy-1")
        self.assertEqual(r["run_id"], 42)
        self.assertEqual(len(r["job_source_refs"]), 1)
        self.assertFalse(r["can_authorize_execution"])
        self.assertIsNone(r["tested_tree"])
        self.assertTrue(r["requires_source_revalidation"])
        self.assertEqual(len(self.f.calls), 5)
        self.assertIn("head_sha=" + MERGE, self.f.fixed_query)
        self.assertIn("event=push", self.f.fixed_query)
        self.assertIn("branch=main", self.f.fixed_query)

    def test_invalid_requirements_stop_before_read(self):
        for changes in (
            {"repository_id": True}, {"commit": "main"}, {"workflow_id": 0},
            {"channel": ""}, {"policy_revision": ""}, {"branch": ""},
            {"required_jobs": ()}, {"required_jobs": ("verify", "verify")},
            {"required_jobs": "verify"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(self.read(replace(self.required, **changes))["status"], "UNKNOWN")
        self.assertEqual(self.f.calls, [])

    def test_native_lookup_must_be_complete_and_unique(self):
        for packet in (
            {"total_count": 0, "workflow_runs": []},
            {"total_count": 2, "workflow_runs": [self.f.run]},
            {"total_count": 2, "workflow_runs": [self.f.run, self.f.run]},
            {"total_count": True, "workflow_runs": [self.f.run]},
        ):
            self.f.workflow_runs = packet
            self.assertEqual(self.read()["reason"], "FIXED_SOURCE_RUN_NOT_UNIQUE")

    def test_wrong_repo_id_head_branch_workflow_event_or_commit_rejected(self):
        original = copy.deepcopy(self.f.run)
        for changes in (
            {"repository": {"full_name": REPO, "id": 1235}},
            {"head_repository": {"id": 1235}},
            {"repository": {"full_name": REPO, "id": 1234.0}},
            {"head_repository": {"id": 1234.0}},
            {"head_branch": "feature"}, {"head_sha": HEAD},
            {"workflow_id": 99}, {"event": "pull_request"}, {"path": "other.yml"},
        ):
            with self.subTest(changes=changes):
                self.f.run = original | changes
                self.assertEqual(self.read()["reason"], "FIXED_SOURCE_RUN_IDENTITY_UNPROVEN")

    def test_partial_latest_jobs_or_run_drift_is_not_success(self):
        self.f.workflow_runs = {"total_count": 1, "workflow_runs": [copy.deepcopy(self.f.run)]}
        self.f.run["run_attempt"] = 3
        self.assertEqual(self.read()["reason"], "FIXED_SOURCE_RUN_CHANGED_OR_INCOMPLETE")
        self.f.workflow_runs = None
        self.f.jobs["total_count"] = 2
        self.assertEqual(self.read()["reason"], "FIXED_SOURCE_RUN_CHANGED_OR_INCOMPLETE")

    def test_missing_duplicate_or_unsuccessful_required_job(self):
        self.assertEqual(self.read(replace(self.required, required_jobs=("missing",)))
                         ["reason"], "FIXED_SOURCE_REQUIRED_JOB_NOT_UNIQUE")
        self.f.jobs["jobs"][0]["conclusion"] = "skipped"
        self.assertEqual(self.read()["status"], "NOT_SUCCESSFUL")
        self.f.jobs["jobs"][0]["conclusion"] = "success"
        self.f.jobs["jobs"].append(dict(self.f.jobs["jobs"][0], id=11))
        self.f.jobs["total_count"] = 2
        self.assertEqual(self.read()["reason"], "FIXED_SOURCE_REQUIRED_JOB_NOT_UNIQUE")

    def test_nonsuccessful_run_and_missing_tree_do_not_qualify(self):
        self.f.run["conclusion"] = "failure"
        self.assertEqual(self.read()["status"], "NOT_SUCCESSFUL")
        self.f.run["conclusion"] = "success"
        self.f.commit["tree"]["sha"] = None
        self.assertEqual(self.read()["reason"], "FIXED_SOURCE_TREE_UNPROVEN")


class HostFixedPolicyTests(unittest.TestCase):
    def setUp(self):
        import hashlib
        from tools.reference_host_policy import resolve_fixed_reference
        self.resolve = resolve_fixed_reference
        self.hashlib = hashlib
        self.f = ReaderFixture()
        self.f.run.update(
            head_sha=MERGE, event="push", head_branch="main",
            repository={"full_name": REPO, "id": 1234},
            head_repository={"full_name": REPO, "id": 1234},
        )
        self.f.jobs["jobs"][0]["head_sha"] = MERGE
        self.policy = f"""schema_version = 1

[[sources]]
repository = "{REPO}"
repository_id = 1234
channel = "stable"
commit = "{MERGE}"
tree_sha = "{TREE}"
branch = "main"
workflow_id = 13
workflow_path = "{RUN['path']}"
required_jobs = ["verify"]
""".encode("utf-8")
        self.digest = self.hashlib.sha256(self.policy).hexdigest()

    def read(self, policy=None, digest=None, **changes):
        params = dict(repository=REPO, channel="stable", policy_revision=self.digest,
                      pinned_commit="")
        params.update(changes)
        return self.resolve(
            self.f.reader, self.policy if policy is None else policy,
            self.digest if digest is None else digest, **params,
        )

    def read_changed_policy(self, policy):
        digest = self.hashlib.sha256(policy).hexdigest()
        return self.read(policy, digest, policy_revision=digest)

    def test_approved_fixed_policy_selects_default_or_matching_pin(self):
        for pin in ("", MERGE):
            result = self.read(pinned_commit=pin)
            self.assertEqual(result["status"], "RESOLVED")
            self.assertEqual(result["mode"], "CURRENT")
            self.assertEqual(result["repository"], REPO)
            self.assertEqual(result["repository_id"], 1234)
            self.assertEqual(result["policy_revision"], self.digest)
            self.assertEqual(result["commit"], MERGE)
            self.assertEqual(result["tree_sha"], TREE)
            self.assertTrue(result["requires_source_revalidation"])
        self.assertEqual(len(self.f.calls), 10)

    def test_policy_identity_and_request_scope_rejected_before_read(self):
        cases = [
            self.read(self.policy + b"\n"),
            self.read(digest="0" * 64),
            self.read(policy_revision="0" * 64),
            self.read(repository="other/repo"),
            self.read(channel="preview"),
            self.read(pinned_commit=HEAD),
            self.read(pinned_commit="main"),
        ]
        for result in cases:
            self.assertEqual(result["status"], "BLOCKED")
            self.assertNotIn("mode", result)
        self.assertEqual(self.f.calls, [])

    def test_bad_policy_schema_and_duplicate_source_fail_before_read(self):
        for raw in (
            self.policy.replace(b"schema_version = 1", b"schema_version = true"),
            self.policy.replace(b"repository_id = 1234", b"repository_id = 1234.0"),
            self.policy.replace(b'channel = "stable"', b'channel = "stable"\nchannel = "other"'),
            self.policy + b'\nunknown = "bad"\n',
            self.policy.replace(b'required_jobs = ["verify"]', b'required_jobs = []'),
            self.policy.replace(b'required_jobs = ["verify"]', b'required_jobs = [["verify"]]'),
            self.policy + self.policy[self.policy.index(b"[[sources]]"):],
            b"\xff",
        ):
            with self.subTest(raw=raw[:70]):
                self.assertEqual(self.read_changed_policy(raw)["status"], "BLOCKED")
        self.assertEqual(self.f.calls, [])

    def test_matching_native_success_cannot_substitute_for_policy_tree(self):
        policy = self.policy.replace(TREE.encode(), b"f" * 40)
        result = self.read_changed_policy(policy)
        self.assertEqual(result, {"status": "BLOCKED", "reason": "REFERENCE_TREE_MISMATCH"})

    def test_native_failure_or_unavailable_never_falls_back_offline(self):
        self.f.run["conclusion"] = "failure"
        self.assertEqual(self.read(), {"status": "BLOCKED", "reason": "REFERENCE_NATIVE_EVIDENCE_UNAVAILABLE"})
        self.f.run["conclusion"] = "success"
        self.f.workflow_runs = {"total_count": 0, "workflow_runs": []}
        self.assertEqual(self.read(), {"status": "BLOCKED", "reason": "REFERENCE_NATIVE_EVIDENCE_UNAVAILABLE"})

    def test_direct_isolated_cli_rejects_unapproved_pin_and_bad_digest(self):
        import json
        from pathlib import Path
        import subprocess
        import sys
        import tempfile
        script = Path(__file__).resolve().parents[1] / "tools/reference_host_policy.py"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.toml"
            path.write_bytes(self.policy)
            args = [sys.executable, "-I", "-B", str(script),
                    "--host-policy", str(path), "--approved-digest", self.digest,
                    "--repository", REPO, "--channel", "stable",
                    "--policy-revision", self.digest]
            result = subprocess.run(args + ["--pin", HEAD], cwd=tmp, capture_output=True,
                                    text=True, check=False, timeout=20)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout), {"status": "BLOCKED", "reason": "REFERENCE_PIN_NOT_APPROVED"})
            path.write_bytes(self.policy + b"\n")
            result = subprocess.run(args, cwd=tmp, capture_output=True, text=True,
                                    check=False, timeout=20)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout), {"status": "BLOCKED", "reason": "HOST_POLICY_IDENTITY_MISMATCH"})


if __name__ == "__main__":
    unittest.main()
