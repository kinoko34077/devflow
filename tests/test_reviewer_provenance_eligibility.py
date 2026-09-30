import copy
import json
import unittest
from pathlib import Path

from tools import chat_worker_bootstrap as cwb


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "docs/spec/examples/chat-worker-bootstrap/02-two-fresh-candidates-rank-order.json"


def base_case():
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data = copy.deepcopy(data)
    candidate = data["evidence"]["frontier"]["candidates"][0]
    candidate.update(
        task_ref="kinoko34077/execution-coordinator#81",
        role="reviewer",
        action="REVIEW",
        work_class="formal-review",
        fingerprint="sha256:" + "a" * 64,
        rank_key=[1, 0, 0, 1],
    )
    data["evidence"]["frontier"]["candidates"] = [candidate]
    return data


def require_different(candidate, system="ChatGPT", model="GPT-5.6 Sol"):
    candidate.update(
        different_reviewer_required=True,
        implementer_system=system,
        implementer_model=model,
    )


class ReviewerProvenanceEligibilityTests(unittest.TestCase):
    def test_ordinary_review_preserves_default_implementer_review_valid_semantics(self):
        data = base_case()
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual("REVIEW_WORK", result["disposition"])
        self.assertEqual("kinoko34077/execution-coordinator#81", result["task_ref"])

    def test_same_signature_worker_is_ineligible_for_explicit_different_reviewer(self):
        data = base_case()
        require_different(data["evidence"]["frontier"]["candidates"][0])
        data["request"].update(
            reviewer_system="ChatGPT",
            reviewer_model="GPT-5.6 Sol",
        )
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual(
            ("NO_ELIGIBLE_WORK", "ALL_CANDIDATES_OMITTED"),
            (result["disposition"], result["reason_code"]),
        )
        self.assertEqual(
            "REVIEWER_PROVENANCE_CONFLICT",
            result["omissions"][0]["reason"],
        )

    def test_different_model_signature_remains_eligible(self):
        data = base_case()
        require_different(data["evidence"]["frontier"]["candidates"][0])
        data["request"].update(
            reviewer_system="ChatGPT",
            reviewer_model="GPT-5.7",
        )
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual("REVIEW_WORK", result["disposition"])

    def test_different_system_signature_remains_eligible(self):
        data = base_case()
        require_different(data["evidence"]["frontier"]["candidates"][0])
        data["request"].update(
            reviewer_system="Claude Code",
            reviewer_model="Claude Sonnet 5",
        )
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual("REVIEW_WORK", result["disposition"])

    def test_missing_or_unknown_worker_signature_fails_closed(self):
        for signature in (None, ("unknown", "unknown")):
            with self.subTest(signature=signature):
                data = base_case()
                require_different(data["evidence"]["frontier"]["candidates"][0])
                if signature is not None:
                    data["request"].update(
                        reviewer_system=signature[0],
                        reviewer_model=signature[1],
                    )
                result = cwb.classify(data["request"], data["evidence"])
                self.assertEqual(
                    ("NO_ELIGIBLE_WORK", "ALL_CANDIDATES_OMITTED"),
                    (result["disposition"], result["reason_code"]),
                )
                self.assertEqual(
                    "REVIEWER_PROVENANCE_UNAVAILABLE",
                    result["omissions"][0]["reason"],
                )

    def test_missing_candidate_implementer_signature_is_invalid_evidence(self):
        data = base_case()
        candidate = data["evidence"]["frontier"]["candidates"][0]
        candidate.update(
            different_reviewer_required=True,
            implementer_system="ChatGPT",
        )
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual(
            ("NEEDS_EVIDENCE", "EVIDENCE_INVALID"),
            (result["disposition"], result["reason_code"]),
        )

    def test_different_reviewer_requirement_on_non_reviewer_is_invalid(self):
        data = base_case()
        candidate = data["evidence"]["frontier"]["candidates"][0]
        candidate.update(
            role="implementer",
            action="IMPLEMENT",
            work_class="implementation",
            different_reviewer_required=True,
            implementer_system="ChatGPT",
            implementer_model="GPT-5.6 Sol",
        )
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual(
            ("NEEDS_EVIDENCE", "EVIDENCE_INVALID"),
            (result["disposition"], result["reason_code"]),
        )

    def test_request_signature_fields_are_both_or_neither(self):
        data = base_case()
        data["request"]["reviewer_system"] = "ChatGPT"
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual(
            ("NEEDS_EVIDENCE", "REQUEST_INVALID"),
            (result["disposition"], result["reason_code"]),
        )

    def test_schema_exposes_only_optional_reviewer_provenance_fields(self):
        request_schema = json.loads(
            (ROOT / "docs/spec/schemas/chat-worker-bootstrap-request.v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertIn("reviewer_system", request_schema["properties"])
        self.assertIn("reviewer_model", request_schema["properties"])
        self.assertNotIn("reviewer_system", request_schema["required"])
        self.assertNotIn("reviewer_model", request_schema["required"])

        evidence_schema = json.loads(
            (ROOT / "docs/spec/schemas/chat-worker-bootstrap-evidence.v1.schema.json").read_text(encoding="utf-8")
        )
        candidate = evidence_schema["properties"]["frontier"]["properties"]["candidates"]["items"]
        for field in (
            "different_reviewer_required",
            "implementer_system",
            "implementer_model",
        ):
            self.assertIn(field, candidate["properties"])

        result_schema = json.loads(
            (ROOT / "docs/spec/schemas/chat-worker-bootstrap-result.v1.schema.json").read_text(encoding="utf-8")
        )
        omission_enum = result_schema["properties"]["omissions"]["items"]["properties"]["reason"]["enum"]
        self.assertIn("REVIEWER_PROVENANCE_UNAVAILABLE", omission_enum)
        self.assertIn("REVIEWER_PROVENANCE_CONFLICT", omission_enum)


if __name__ == "__main__":
    unittest.main()
