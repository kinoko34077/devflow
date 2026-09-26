import unittest

from tools import review_readiness


HEAD = "a" * 40
OTHER = "b" * 40


def pr_body(
    formal_required="yes",
    different_required="no",
    implementer_system="ChatGPT",
    implementer_model="GPT-5.6 Sol",
):
    return f"""## Review target
- Formal review required: {formal_required}
- Different reviewer required: {different_required}
- Review focus: correctness
- Reviewed-SHA target: {HEAD}

## Implementer Provenance
- Implementer-System: {implementer_system}
- Implementer-Model: {implementer_model}
"""


def review_body(
    *,
    reviewed_commit=HEAD,
    reviewer_system="ChatGPT",
    reviewer_model="GPT-5.6 Sol",
    implementer_system="ChatGPT",
    implementer_model="GPT-5.6 Sol",
    blocking="none",
    decision="COMMENT",
    version="2",
):
    return f"""## Review Result
- Blocking findings: {blocking}
- Reviewed-Commit: {reviewed_commit}

### Review Provenance
- Reviewer-System: {reviewer_system}
- Reviewer-Model: {reviewer_model}
- Implementer-System: {implementer_system}
- Implementer-Model: {implementer_model}
- Reviewed-Commit: {reviewed_commit}
- Review-Scope: test
- Decision: {decision}
- Review-Provenance-Version: {version}
"""


def pr(
    formal_required="yes",
    different_required="no",
    implementer_system="ChatGPT",
    implementer_model="GPT-5.6 Sol",
    body=None,
):
    return {
        "body": (
            pr_body(
                formal_required,
                different_required,
                implementer_system,
                implementer_model,
            )
            if body is None
            else body
        ),
        "head": {"sha": HEAD},
    }


def review(**kwargs):
    commit_id = kwargs.pop("commit_id", HEAD)
    state = kwargs.pop("state", "COMMENTED")
    review_id = kwargs.pop("review_id", 101)
    return {
        "id": review_id,
        "state": state,
        "commit_id": commit_id,
        "body": review_body(**kwargs),
    }


class ReviewReadinessTests(unittest.TestCase):
    def test_default_same_signature_formal_review_passes(self):
        result = review_readiness.evaluate(pr(), [review()])
        self.assertTrue(result.ready)
        self.assertEqual(result.matched_review_id, 101)

    def test_default_different_signature_formal_review_passes(self):
        candidate = review(
            reviewer_system="Claude Code",
            reviewer_model="Sonnet",
        )
        result = review_readiness.evaluate(pr(), [candidate])
        self.assertTrue(result.ready)

    def test_different_reviewer_gate_rejects_same_signature(self):
        result = review_readiness.evaluate(
            pr(different_required="yes"),
            [review()],
        )
        self.assertFalse(result.ready)
        self.assertIn("different reviewer", result.reason.lower())

    def test_different_reviewer_gate_accepts_different_signature(self):
        candidate = review(
            reviewer_system="Claude Code",
            reviewer_model="Sonnet",
        )
        result = review_readiness.evaluate(
            pr(different_required="yes"),
            [candidate],
        )
        self.assertTrue(result.ready)
        self.assertEqual(result.matched_review_id, 101)

    def test_stale_reviewed_commit_fails(self):
        result = review_readiness.evaluate(
            pr(), [review(reviewed_commit=OTHER, commit_id=OTHER)]
        )
        self.assertFalse(result.ready)
        self.assertIn("current head", result.reason)

    def test_declared_blocking_findings_fail(self):
        result = review_readiness.evaluate(pr(), [review(blocking="R1")])
        self.assertFalse(result.ready)
        self.assertIn("blocking", result.reason.lower())

    def test_missing_or_malformed_review_gate_fails_closed(self):
        bodies = [
            "## Review target\n- Different reviewer required: no",
            "## Review target\n- Formal review required: maybe\n- Different reviewer required: no",
            "## Review target\n- Formal review required: yes",
            "## Review target\n- Formal review required: yes\n- Different reviewer required: maybe",
        ]
        for body in bodies:
            with self.subTest(body=body):
                result = review_readiness.evaluate(pr(body=body), [])
                self.assertFalse(result.ready)
                self.assertIn("review", result.reason.lower())

    def test_inconsistent_no_formal_but_different_required_fails_closed(self):
        result = review_readiness.evaluate(
            pr(formal_required="no", different_required="yes"),
            [],
        )
        self.assertFalse(result.ready)
        self.assertIn("inconsistent", result.reason.lower())

    def test_no_formal_review_required_passes_without_review(self):
        result = review_readiness.evaluate(
            pr(formal_required="no", different_required="no"),
            [],
        )
        self.assertTrue(result.ready)
        self.assertIsNone(result.matched_review_id)

    def test_api_commit_id_mismatch_fails(self):
        result = review_readiness.evaluate(pr(), [review(commit_id=OTHER)])
        self.assertFalse(result.ready)
        self.assertIn("current head", result.reason)

    def test_malformed_review_provenance_does_not_satisfy_readiness(self):
        malformed = {
            "id": 102,
            "state": "COMMENTED",
            "commit_id": HEAD,
            "body": "## Review Result\n- Blocking findings: none\n",
        }
        result = review_readiness.evaluate(pr(), [malformed])
        self.assertFalse(result.ready)
        self.assertIn("formal review", result.reason.lower())

    def test_legacy_v1_provenance_does_not_satisfy_v2_readiness(self):
        candidate = review(version="1")
        result = review_readiness.evaluate(pr(), [candidate])
        self.assertFalse(result.ready)
        self.assertIn("version", result.reason.lower())

    def test_later_blocking_review_supersedes_earlier_clean_review(self):
        clean = review(review_id=101)
        blocking = review(review_id=102, blocking="R1")
        result = review_readiness.evaluate(pr(), [clean, blocking])
        self.assertFalse(result.ready)
        self.assertIn("blocking", result.reason.lower())

    def test_later_request_changes_supersedes_earlier_clean_review(self):
        clean = review(review_id=101)
        request_changes = review(
            review_id=102,
            state="CHANGES_REQUESTED",
            decision="REQUEST_CHANGES",
            blocking="R1",
        )
        result = review_readiness.evaluate(pr(), [clean, request_changes])
        self.assertFalse(result.ready)
        self.assertIn("blocking", result.reason.lower())

    def test_fresh_clean_review_supersedes_earlier_blocker(self):
        blocking = review(review_id=101, blocking="R1")
        clean = review(review_id=102)
        result = review_readiness.evaluate(pr(), [blocking, clean])
        self.assertTrue(result.ready)
        self.assertEqual(result.matched_review_id, 102)

    def test_different_reviewer_gate_requires_latest_different_signature_review_clean(self):
        different_blocking = review(
            review_id=101,
            reviewer_system="Claude Code",
            reviewer_model="Sonnet",
            blocking="R1",
        )
        self_clean = review(review_id=102)
        result = review_readiness.evaluate(
            pr(different_required="yes"),
            [different_blocking, self_clean],
        )
        self.assertFalse(result.ready)
        self.assertIn("blocking", result.reason.lower())

    def test_api_state_and_declared_decision_must_match(self):
        candidate = review(state="COMMENTED", decision="APPROVE")
        result = review_readiness.evaluate(pr(), [candidate])
        self.assertFalse(result.ready)
        self.assertIn("decision", result.reason.lower())


if __name__ == "__main__":
    unittest.main()
