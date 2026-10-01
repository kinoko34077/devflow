import copy
import json
import unittest
from pathlib import Path

from tools import chat_worker_bootstrap as cwb


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "docs/spec/examples/chat-worker-bootstrap/01-broad-instruction-fresh-claim.json"
SCHEMAS = ROOT / "docs/spec/schemas"


def base_case():
    data = copy.deepcopy(json.loads(EXAMPLE.read_text(encoding="utf-8")))
    candidate = data["evidence"]["frontier"]["candidates"][0]
    candidate.update(
        role="reviewer",
        action="REVIEW",
        work_class="formal-review",
        reviewer_independence_conflict=False,
    )
    return data


class ReviewerProvenancePickupTests(unittest.TestCase):
    def test_ordinary_review_remains_valid_without_review_provenance(self):
        data = base_case()
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual(("REVIEW_WORK", "ELIGIBLE_REVIEW_DEMAND"), (result["disposition"], result["reason_code"]))

    def test_explicit_different_reviewer_same_signature_is_ineligible(self):
        data = base_case()
        data["request"]["review_provenance"] = {"system": "Claude Code", "model": "Claude Sonnet 5"}
        data["evidence"]["frontier"]["candidates"][0]["different_reviewer_requirement"] = {
            "implementer_system": "Claude Code",
            "implementer_model": "Claude Sonnet 5",
        }
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual(("NO_ELIGIBLE_WORK", "ALL_CANDIDATES_OMITTED"), (result["disposition"], result["reason_code"]))
        self.assertEqual("REVIEWER_INDEPENDENCE_CONFLICT", result["omissions"][0]["reason"])

    def test_provider_transport_identity_does_not_override_review_signature(self):
        data = base_case()
        data["request"]["worker_system"] = "chatgpt"
        data["request"]["review_provenance"] = {"system": "Claude Code", "model": "Claude Sonnet 5"}
        data["evidence"]["frontier"]["candidates"][0]["different_reviewer_requirement"] = {
            "implementer_system": "Claude Code",
            "implementer_model": "Claude Sonnet 5",
        }
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual("NO_ELIGIBLE_WORK", result["disposition"])
        self.assertEqual("REVIEWER_INDEPENDENCE_CONFLICT", result["omissions"][0]["reason"])

    def test_explicit_different_reviewer_different_model_is_eligible(self):
        data = base_case()
        data["request"]["review_provenance"] = {"system": "Claude Code", "model": "Claude Opus 5.5"}
        data["evidence"]["frontier"]["candidates"][0]["different_reviewer_requirement"] = {
            "implementer_system": "Claude Code",
            "implementer_model": "Claude Sonnet 5",
        }
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual(("REVIEW_WORK", "ELIGIBLE_REVIEW_DEMAND"), (result["disposition"], result["reason_code"]))

    def test_explicit_different_reviewer_different_system_qualifies_even_if_implementer_model_unknown(self):
        data = base_case()
        data["request"]["worker_system"] = "chatgpt"
        data["request"]["review_provenance"] = {"system": "ChatGPT", "model": "GPT-5.6 Sol"}
        data["evidence"]["frontier"]["candidates"][0]["different_reviewer_requirement"] = {
            "implementer_system": "Claude Code",
            "implementer_model": "unknown",
        }
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual(("REVIEW_WORK", "ELIGIBLE_REVIEW_DEMAND"), (result["disposition"], result["reason_code"]))

    def test_unrelated_work_class_does_not_require_reviewer_provenance(self):
        data = base_case()
        data["request"]["accepted_work_classes"] = ["quickfix"]
        data["evidence"]["frontier"]["candidates"][0]["different_reviewer_requirement"] = {
            "implementer_system": "Claude Code",
            "implementer_model": "Claude Sonnet 5",
        }
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual(("NO_ELIGIBLE_WORK", "ALL_CANDIDATES_OMITTED"), (result["disposition"], result["reason_code"]))
        self.assertEqual("WORK_CLASS_MISMATCH", result["omissions"][0]["reason"])

    def test_explicit_different_reviewer_missing_reviewer_provenance_fails_closed(self):
        data = base_case()
        data["evidence"]["frontier"]["candidates"][0]["different_reviewer_requirement"] = {
            "implementer_system": "Claude Code",
            "implementer_model": "Claude Sonnet 5",
        }
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual(("NEEDS_EVIDENCE", "EVIDENCE_INVALID"), (result["disposition"], result["reason_code"]))

    def test_explicit_different_reviewer_missing_implementer_signature_fails_closed(self):
        data = base_case()
        data["request"]["review_provenance"] = {"system": "Claude Code", "model": "Claude Opus 5.5"}
        data["evidence"]["frontier"]["candidates"][0]["different_reviewer_requirement"] = {
            "implementer_system": "Claude Code",
        }
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual(("NEEDS_EVIDENCE", "EVIDENCE_INVALID"), (result["disposition"], result["reason_code"]))

    def test_different_reviewer_requirement_is_reviewer_only(self):
        data = base_case()
        candidate = data["evidence"]["frontier"]["candidates"][0]
        candidate.update(role="implementer", action="IMPLEMENT", work_class="implementation")
        candidate["different_reviewer_requirement"] = {
            "implementer_system": "Claude Code",
            "implementer_model": "Claude Sonnet 5",
        }
        data["request"]["review_provenance"] = {"system": "Claude Code", "model": "Claude Opus 5.5"}
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual(("NEEDS_EVIDENCE", "EVIDENCE_INVALID"), (result["disposition"], result["reason_code"]))

    def test_signature_matching_normalizes_case_and_whitespace(self):
        data = base_case()
        data["request"]["review_provenance"] = {"system": "  Claude   Code ", "model": "  Claude   Sonnet 5 "}
        data["evidence"]["frontier"]["candidates"][0]["different_reviewer_requirement"] = {
            "implementer_system": "CLAUDE CODE",
            "implementer_model": "claude sonnet 5",
        }
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual("NO_ELIGIBLE_WORK", result["disposition"])
        self.assertEqual("REVIEWER_INDEPENDENCE_CONFLICT", result["omissions"][0]["reason"])

    def test_schema_additions_are_optional_and_bound_to_existing_fresh_evidence(self):
        request_schema = json.loads((SCHEMAS / "chat-worker-bootstrap-request.v1.schema.json").read_text(encoding="utf-8"))
        self.assertIn("review_provenance", request_schema["properties"])
        self.assertNotIn("review_provenance", request_schema["required"])

        evidence_schema = json.loads((SCHEMAS / "chat-worker-bootstrap-evidence.v1.schema.json").read_text(encoding="utf-8"))
        candidate = evidence_schema["properties"]["frontier"]["properties"]["candidates"]["items"]
        self.assertIn("different_reviewer_requirement", candidate["properties"])
        self.assertNotIn("different_reviewer_requirement", candidate["required"])

        portfolio_schema = json.loads((SCHEMAS / "execution-portfolio-metadata.v1.schema.json").read_text(encoding="utf-8"))
        entry = portfolio_schema["properties"]["entries"]["items"]
        self.assertIn("different_reviewer_requirement", entry["properties"])
        self.assertNotIn("different_reviewer_requirement", entry["required"])


if __name__ == "__main__":
    unittest.main()
