"""Co-implemented PRs: only the last implementer is ineligible as different reviewer."""
import unittest

from tools import review_readiness
from tests.test_review_readiness import HEAD, review_body

MIXED_MODEL = "ChatGPT GPT-6 + Claude Code unknown"


def mixed_pr(last_system="ChatGPT", last_model="GPT-6", *, include_last=True, extra=""):
    last = (
        f"- Last-Implementer-System: {last_system}\n- Last-Implementer-Model: {last_model}\n"
        if include_last else ""
    )
    body = f"""- Formal review required: yes
- Different reviewer required: yes
- Implementer-System: mixed
- Implementer-Model: {MIXED_MODEL}
{last}{extra}"""
    return {"body": body, "head": {"sha": HEAD}}


def mixed_review(reviewer_system, reviewer_model="unknown"):
    return {
        "id": 7,
        "state": "COMMENTED",
        "commit_id": HEAD,
        "body": review_body(
            reviewer_system=reviewer_system,
            reviewer_model=reviewer_model,
            implementer_system="mixed",
            implementer_model=MIXED_MODEL,
        ),
    }


class MixedImplementerReadinessTests(unittest.TestCase):
    def test_earlier_co_implementer_may_review_when_not_last(self):
        result = review_readiness.evaluate(mixed_pr("ChatGPT", "GPT-6"), [mixed_review("Claude Code")])
        self.assertTrue(result.ready, result.reason)

    def test_last_implementer_cannot_review(self):
        result = review_readiness.evaluate(
            mixed_pr("Claude Code", "unknown"), [mixed_review("Claude Code")]
        )
        self.assertFalse(result.ready)

    def test_same_system_other_model_qualifies_only_with_known_models(self):
        ok = review_readiness.evaluate(mixed_pr("ChatGPT", "GPT-6"), [mixed_review("ChatGPT", "GPT-5.6 Sol")])
        self.assertTrue(ok.ready, ok.reason)
        unknown = review_readiness.evaluate(mixed_pr("ChatGPT", "GPT-6"), [mixed_review("ChatGPT", "unknown")])
        self.assertFalse(unknown.ready)

    def test_mixed_without_last_implementer_fails_closed(self):
        result = review_readiness.evaluate(mixed_pr(include_last=False), [mixed_review("Codex")])
        self.assertFalse(result.ready)
        self.assertIn("Last-Implementer", result.reason)

    def test_unknown_or_mixed_last_implementer_fails_closed(self):
        for system in ("unknown", "mixed", ""):
            with self.subTest(system=system):
                result = review_readiness.evaluate(mixed_pr(system, "x"), [mixed_review("Codex")])
                self.assertFalse(result.ready)

    def test_duplicate_last_implementer_fields_fail_closed(self):
        dup = "- Last-Implementer-System: Codex\n"
        result = review_readiness.evaluate(mixed_pr(extra=dup), [mixed_review("Claude Code")])
        self.assertFalse(result.ready)

    def test_last_fields_rejected_for_single_implementer(self):
        body = """- Formal review required: yes
- Different reviewer required: yes
- Implementer-System: ChatGPT
- Implementer-Model: GPT-6
- Last-Implementer-System: Codex
- Last-Implementer-Model: x
"""
        review = {
            "id": 1, "state": "COMMENTED", "commit_id": HEAD,
            "body": review_body(reviewer_system="Codex", reviewer_model="x",
                                implementer_system="ChatGPT", implementer_model="GPT-6"),
        }
        result = review_readiness.evaluate({"body": body, "head": {"sha": HEAD}}, [review])
        self.assertFalse(result.ready)

    def test_review_must_still_declare_pr_mixed_provenance(self):
        review = mixed_review("Claude Code")
        review["body"] = review["body"].replace("Implementer-System: mixed", "Implementer-System: ChatGPT")
        result = review_readiness.evaluate(mixed_pr("ChatGPT", "GPT-6"), [review])
        self.assertFalse(result.ready)

    def test_no_formal_gate_does_not_bypass_mixed_validation(self):
        gate = "- Formal review required: no\n- Different reviewer required: no\n"
        missing = {"body": gate + f"- Implementer-System: mixed\n- Implementer-Model: {MIXED_MODEL}\n",
                   "head": {"sha": HEAD}}
        self.assertFalse(review_readiness.evaluate(missing, []).ready)
        stray = {"body": gate + "- Implementer-System: ChatGPT\n- Implementer-Model: GPT-6\n"
                 "- Last-Implementer-System: Codex\n- Last-Implementer-Model: x\n",
                 "head": {"sha": HEAD}}
        self.assertFalse(review_readiness.evaluate(stray, []).ready)
        plain = {"body": gate, "head": {"sha": HEAD}}
        self.assertTrue(review_readiness.evaluate(plain, []).ready)

    def test_composite_last_implementer_fails_closed(self):
        for system in ("ChatGPT + Claude Code", "ChatGPT, Claude Code", "ChatGPT and Codex", "ChatGPT/Codex"):
            with self.subTest(system=system):
                result = review_readiness.evaluate(mixed_pr(system, "unknown"), [mixed_review("Codex")])
                self.assertFalse(result.ready)

    def test_duplicate_last_fields_rejected_for_single_implementer(self):
        body = """- Formal review required: yes
- Different reviewer required: yes
- Implementer-System: ChatGPT
- Implementer-Model: GPT-6
- Last-Implementer-System: Codex
- Last-Implementer-System: Codex
"""
        review = {
            "id": 1, "state": "COMMENTED", "commit_id": HEAD,
            "body": review_body(reviewer_system="Codex", reviewer_model="x",
                                implementer_system="ChatGPT", implementer_model="GPT-6"),
        }
        result = review_readiness.evaluate({"body": body, "head": {"sha": HEAD}}, [review])
        self.assertFalse(result.ready)
        self.assertIn("Last-Implementer", result.reason)


if __name__ == "__main__":
    unittest.main()
