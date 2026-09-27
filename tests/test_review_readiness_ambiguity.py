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


if __name__ == "__main__":
    unittest.main()
