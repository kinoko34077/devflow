import hashlib
import unittest

from tools.acceptance_evidence_preflight import acceptance_preflight
from tools.development_reconciler import evaluate_pr

TASK = "kinoko34077/devflow#798"
BODY = "Current owning Issue body: local MCP accepted; Inbox completeness excluded"
SHA = hashlib.sha256(BODY.encode()).hexdigest()


def proof(**overrides):
    value = {
        "task_ref": TASK, "issue_body_sha256": SHA,
        "issue_read_at": "2026-10-27T00:00:00Z",
        "acceptance_scope": "bounded Windows local MCP availability",
        "status": "SATISFIED", "source_verified": True,
        "source_complete": True, "decision_authorized": True,
        "evidence_refs": ["https://github.com/kinoko34077/devflow/issues/531#issuecomment-6366311495"],
        "excluded_scopes": ["global Inbox completeness", "original historical failure cause"],
    }
    value.update(overrides)
    return value


class AcceptanceEvidenceTests(unittest.TestCase):
    def check(self, value):
        return acceptance_preflight(value, task_ref=TASK, observed_issue_body_sha256=SHA)

    def test_bounded_current_issue_acceptance_passes_without_overclaim(self):
        result = self.check(proof())
        self.assertEqual(result["status"], "VERIFIED_SCOPE_DECISION")
        self.assertTrue(result["acceptance_satisfied"])
        self.assertEqual(result["excluded_scopes"], ("global Inbox completeness", "original historical failure cause"))

    def test_older_pr_claim_cannot_override_current_issue_revision(self):
        result = self.check(proof(issue_body_sha256="a"*64))
        self.assertEqual(result["reason"], "STALE_OWNING_ISSUE_REVISION")
        self.assertFalse(result["evidence_complete"])

    def test_merge_and_ci_alone_do_not_attest_success(self):
        for patch in ({"decision_authorized": False}, {"source_verified": False},
                      {"source_complete": False}, {"evidence_refs": []},
                      {"status": "UNKNOWN"}, {"task_ref": "kinoko34077/devflow#799"}):
            with self.subTest(patch=patch):
                result = self.check(proof(**patch))
                self.assertFalse(result["evidence_complete"])
                self.assertFalse(result["acceptance_satisfied"])

    def test_rejected_scope_is_not_positive_acceptance(self):
        result = self.check(proof(status="UNSATISFIED"))
        self.assertTrue(result["evidence_complete"])
        self.assertFalse(result["acceptance_satisfied"])

    def test_untrusted_or_incomplete_proof_cannot_trigger_existing_reconciler(self):
        result = self.check(proof(source_verified=False))
        pr = {
            "task_ref": TASK, "task_kind": "FINITE", "task_open": True,
            "acceptance_satisfied": result["acceptance_satisfied"],
            "pr_number": 799, "pr_state": "MERGED", "pr_head_sha": "a"*40,
            "expected_head_sha": "a"*40, "checks": "PASS", "formal_review": "PASS",
            "different_reviewer_required": False, "different_reviewer": "PASS",
            "request_changes": False, "blocking_finding": False, "owning_blocker": False,
            "human_gate": False, "external_wait": False, "mergeable": True,
            "revertible": True, "current_state_changed": True,
            "control_changed": True, "evidence_complete": result["evidence_complete"],
        }
        decision = evaluate_pr(pr)
        self.assertEqual(decision.disposition, "NEEDS_EVIDENCE")
        self.assertIsNone(decision.transition)


if __name__ == "__main__":
    unittest.main()
