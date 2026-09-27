import unittest

from tools import review_readiness
from tests.test_review_readiness import pr, review


class ReviewProvenanceAmbiguityTests(unittest.TestCase):
    def test_duplicate_review_provenance_sections_fail_closed(self):
        candidate = review()
        candidate["body"] += """

### Review Provenance
- Reviewer-System: Claude Code
- Reviewer-Model: Sonnet
- Implementer-System: ChatGPT
- Implementer-Model: GPT-5.6 Sol
- Reviewed-Commit: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
- Review-Scope: contradictory duplicate
- Decision: REQUEST_CHANGES
- Review-Provenance-Version: 2
"""

        result = review_readiness.evaluate(pr(), [candidate])

        self.assertFalse(result.ready)
        self.assertIn("provenance", result.reason.casefold())

    def test_newer_ambiguous_review_blocks_older_clean_review(self):
        clean = review()
        ambiguous = review()
        ambiguous["id"] = 2
        ambiguous["body"] = ambiguous["body"].replace(
            "- Blocking findings: none", "- Blocking findings: R1 P1 open"
        ) + "\n\n" + ambiguous["body"][ambiguous["body"].index("### Review Provenance"):]

        result = review_readiness.evaluate(pr(), [clean, ambiguous])

        self.assertFalse(result.ready)
        self.assertIn("ambiguous", result.reason.casefold())

    def test_older_ambiguous_review_superseded_by_newer_clean_review(self):
        ambiguous = review()
        ambiguous["body"] += "\n\n" + ambiguous["body"][ambiguous["body"].index("### Review Provenance"):]
        clean = review()
        clean["id"] = 3

        result = review_readiness.evaluate(pr(), [ambiguous, clean])

        self.assertTrue(result.ready, result.reason)


if __name__ == "__main__":
    unittest.main()
