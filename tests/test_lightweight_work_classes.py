import copy
import json
import unittest
from pathlib import Path

from tools import chat_worker_bootstrap as cwb


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs/spec/examples/chat-worker-bootstrap"
SCHEMAS = ROOT / "docs/spec/schemas"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def example(prefix):
    return load(next(path for path in EXAMPLES.glob("*.json") if path.name.startswith(prefix)))


class LightweightWorkClassTests(unittest.TestCase):
    def _portfolio_case(self):
        data = copy.deepcopy(example("02-two-fresh-candidates-rank-order"))
        data["request"]["target_repository"] = None
        data["request"]["worker_session_id"] = "chatgpt-df215-a"
        data["request"]["execution_attempt_id"] = "chatgpt-df215-a:c1"
        data["request"]["worker_system"] = "chatgpt"
        data["request"]["tool_surfaces"] = ["coordinator:claim", "github:read", "github:write"]
        data["evidence"]["controls"] = [
            {
                "ref": "kinoko34077/devflow#28",
                "managed_repository": "kinoko34077/refil-viewer",
                "state": "open",
                "trusted": True,
                "repository_state": "ACTIVE",
                "human_gate": False,
                "external_blocker": False,
            },
            {
                "ref": "kinoko34077/devflow#59",
                "managed_repository": "kinoko34077/kinotch-repo-monitor",
                "state": "open",
                "trusted": True,
                "repository_state": "ACTIVE",
                "human_gate": False,
                "external_blocker": False,
            },
        ]
        reviewer, quickfix = data["evidence"]["frontier"]["candidates"][:2]
        reviewer.update(
            task_ref="kinoko34077/refil-viewer#6",
            role="reviewer",
            action="REVIEW",
            fingerprint="sha256:" + "a" * 64,
            rank_key=[1, 0, 0, 1, 1, ""],
            work_class="formal-review",
        )
        quickfix.update(
            task_ref="kinoko34077/kinotch-repo-monitor#30",
            role="implementer",
            action="IMPLEMENT",
            fingerprint="sha256:" + "b" * 64,
            rank_key=[2, 0, 0, 1, 1, ""],
            work_class="quickfix",
        )
        for item in (reviewer, quickfix):
            item.update(
                digest_fresh=True,
                dependency_ready=True,
                human_gate=False,
                external_blocker=False,
                reviewer_independence_conflict=False,
                published_by_this_attempt=False,
                claimability="CLAIMABLE",
                required_capabilities=[],
                required_environment=[],
            )
        data["evidence"]["frontier"]["candidates"] = [reviewer, quickfix]
        return data

    def test_legacy_request_preserves_reviewer_precedence(self):
        data = self._portfolio_case()
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual("REVIEW_WORK", result["disposition"])
        self.assertEqual("kinoko34077/refil-viewer#6", result["task_ref"])

    def test_maintenance_filter_excludes_unrelated_formal_review_before_track_selection(self):
        data = self._portfolio_case()
        data["request"]["accepted_work_classes"] = ["audit", "triage", "sync-check", "quickfix"]
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual("CLAIM_AND_WORK", result["disposition"])
        self.assertEqual("kinoko34077/kinotch-repo-monitor#30", result["task_ref"])
        self.assertIn(
            {
                "task_ref": "kinoko34077/refil-viewer#6",
                "role": "reviewer",
                "reason": "WORK_CLASS_MISMATCH",
            },
            result["omissions"],
        )

    def test_review_only_filter_keeps_formal_review_lane(self):
        data = self._portfolio_case()
        data["request"]["accepted_work_classes"] = ["formal-review"]
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual("REVIEW_WORK", result["disposition"])
        self.assertEqual("kinoko34077/refil-viewer#6", result["task_ref"])

    def test_explicit_reviewer_non_formal_review_fails_closed(self):
        data = self._portfolio_case()
        data["evidence"]["frontier"]["candidates"][0]["work_class"] = "quickfix"
        data["request"]["accepted_work_classes"] = ["quickfix"]
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual(
            ("NEEDS_EVIDENCE", "EVIDENCE_INVALID"),
            (result["disposition"], result["reason_code"]),
        )

    def test_explicit_formal_review_non_reviewer_fails_closed(self):
        data = self._portfolio_case()
        implementer = data["evidence"]["frontier"]["candidates"][1]
        implementer["work_class"] = "formal-review"
        data["evidence"]["frontier"]["candidates"] = [implementer]
        data["request"]["accepted_work_classes"] = ["formal-review"]
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual(
            ("NEEDS_EVIDENCE", "EVIDENCE_INVALID"),
            (result["disposition"], result["reason_code"]),
        )

    def test_missing_candidate_work_class_uses_narrow_legacy_role_default(self):
        data = self._portfolio_case()
        for item in data["evidence"]["frontier"]["candidates"]:
            item.pop("work_class", None)
        data["request"]["accepted_work_classes"] = ["formal-review"]
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual("REVIEW_WORK", result["disposition"])
        self.assertEqual("kinoko34077/refil-viewer#6", result["task_ref"])

    def test_legacy_implementer_does_not_masquerade_as_quickfix(self):
        data = self._portfolio_case()
        for item in data["evidence"]["frontier"]["candidates"]:
            item.pop("work_class", None)
        data["request"]["accepted_work_classes"] = ["quickfix"]
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual(("NO_ELIGIBLE_WORK", "ALL_CANDIDATES_OMITTED"), (result["disposition"], result["reason_code"]))
        self.assertTrue(result["omissions"])
        self.assertTrue(all(item["reason"] == "WORK_CLASS_MISMATCH" for item in result["omissions"]))

    def test_invalid_or_empty_work_class_preference_fails_closed(self):
        data = self._portfolio_case()
        for value in ([], ["not-a-class"], ["quickfix", "quickfix"], "quickfix"):
            with self.subTest(value=value):
                request = dict(data["request"], accepted_work_classes=value)
                result = cwb.classify(request, data["evidence"])
                self.assertEqual(("NEEDS_EVIDENCE", "REQUEST_INVALID"), (result["disposition"], result["reason_code"]))

    def test_work_intent_remains_non_authoritative_without_structured_preference(self):
        data = self._portfolio_case()
        baseline = cwb.classify(data["request"], data["evidence"])
        data["request"]["work_intent"] = "簡単な修正だけやって"
        self.assertEqual(baseline["task_ref"], cwb.classify(data["request"], data["evidence"])["task_ref"])

    def test_schema_additions_are_optional_and_closed(self):
        request_schema = load(SCHEMAS / "chat-worker-bootstrap-request.v1.schema.json")
        self.assertIn("accepted_work_classes", request_schema["properties"])
        self.assertNotIn("accepted_work_classes", request_schema["required"])
        enum = request_schema["properties"]["accepted_work_classes"]["items"]["enum"]
        self.assertEqual(list(cwb.WORK_CLASSES), enum)

        evidence_schema = load(SCHEMAS / "chat-worker-bootstrap-evidence.v1.schema.json")
        candidate = evidence_schema["properties"]["frontier"]["properties"]["candidates"]["items"]
        self.assertIn("work_class", candidate["properties"])
        self.assertNotIn("work_class", candidate["required"])
        self.assertEqual(list(cwb.WORK_CLASSES), candidate["properties"]["work_class"]["enum"])

        portfolio_schema = load(SCHEMAS / "execution-portfolio-metadata.v1.schema.json")
        entry = portfolio_schema["properties"]["entries"]["items"]
        self.assertIn("work_class", entry["properties"])
        self.assertNotIn("work_class", entry["required"])
        self.assertEqual(list(cwb.WORK_CLASSES), entry["properties"]["work_class"]["enum"])

        result_schema = load(SCHEMAS / "chat-worker-bootstrap-result.v1.schema.json")
        reasons = result_schema["properties"]["omissions"]["items"]["properties"]["reason"]["enum"]
        self.assertIn("WORK_CLASS_MISMATCH", reasons)


if __name__ == "__main__":
    unittest.main()
