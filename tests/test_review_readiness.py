import unittest

from tools import review_readiness


HEAD = "a" * 40
OTHER = "b" * 40


def pr_body(role="independent-review", implementer="ChatGPT"):
    return f"""## Review target
- Required review role: {role}
- Review focus: correctness
- Reviewed-SHA target: {HEAD}

## Implementer Provenance
- Implementer-System: {implementer}
"""


def review_body(
    *,
    reviewed_commit=HEAD,
    reviewer="Claude Code",
    role="independent-review",
    independence="DIFFERENT_AGENT",
    blocking="none",
):
    return f"""## Review Result
- Blocking findings: {blocking}
- Reviewed-Commit: {reviewed_commit}

### Review Provenance
- Reviewer-System: {reviewer}
- Reviewer-Model: test-model
- Review-Role: {role}
- Implementer-System: ChatGPT
- Reviewed-Commit: {reviewed_commit}
- Review-Scope: test
- Independence: {independence}
- Decision: COMMENT
- Review-Provenance-Version: 1
"""


def pr(role="independent-review", implementer="ChatGPT", body=None):
    return {
        "body": pr_body(role, implementer) if body is None else body,
        "head": {"sha": HEAD},
    }


def review(**kwargs):
    commit_id = kwargs.pop("commit_id", HEAD)
    return {
        "id": 101,
        "state": "COMMENTED",
        "commit_id": commit_id,
        "body": review_body(**kwargs),
    }


class ReviewReadinessTests(unittest.TestCase):
    def test_independent_current_head_review_passes(self):
        result = review_readiness.evaluate(pr(), [review()])
        self.assertTrue(result.ready)
        self.assertEqual(result.matched_review_id, 101)

    def test_stale_reviewed_commit_fails(self):
        result = review_readiness.evaluate(
            pr(), [review(reviewed_commit=OTHER, commit_id=OTHER)]
        )
        self.assertFalse(result.ready)
        self.assertIn("current head", result.reason)

    def test_independent_review_rejects_same_agent_or_wrong_independence(self):
        cases = [
            review(reviewer="ChatGPT"),
            review(independence="SAME_AGENT_SELF_REVIEW"),
        ]
        for candidate in cases:
            with self.subTest(candidate=candidate["body"]):
                self.assertFalse(review_readiness.evaluate(pr(), [candidate]).ready)

    def test_declared_blocking_findings_fail(self):
        result = review_readiness.evaluate(pr(), [review(blocking="R1")])
        self.assertFalse(result.ready)
        self.assertIn("blocking", result.reason.lower())

    def test_missing_or_malformed_required_role_fails_closed(self):
        bodies = [
            "## Review target\n- Review focus: correctness",
            "## Review target\n- Required review role: maybe",
        ]
        for body in bodies:
            with self.subTest(body=body):
                result = review_readiness.evaluate(pr(body=body), [])
                self.assertFalse(result.ready)
                self.assertIn("Required review role", result.reason)

    def test_valid_self_review_passes(self):
        candidate = review(
            reviewer="ChatGPT",
            role="self-review",
            independence="SAME_AGENT_SELF_REVIEW",
        )
        result = review_readiness.evaluate(pr(role="self-review"), [candidate])
        self.assertTrue(result.ready)

    def test_none_role_passes_without_review(self):
        result = review_readiness.evaluate(pr(role="none"), [])
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


if __name__ == "__main__":
    unittest.main()
