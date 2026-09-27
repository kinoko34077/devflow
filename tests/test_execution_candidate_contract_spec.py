import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / ".devflow" / "execution-candidate.schema.json"
FIXTURES_PATH = ROOT / ".devflow" / "execution-candidate.conformance.json"


class ExecutionCandidateContractSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.fixtures = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))

    def test_schema_is_strict_and_matches_claim_candidate_surface(self):
        expected = {
            "schema",
            "mode",
            "task",
            "role",
            "entry_ref",
            "control_ref",
            "parent_ref",
            "scope_ready",
            "blocked",
            "requires_user_confirmation",
            "conflict_keys",
        }
        self.assertEqual(set(self.schema["required"]), expected)
        self.assertEqual(set(self.schema["properties"]), expected)
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(self.schema["properties"]["schema"]["const"], 1)
        self.assertEqual(self.schema["properties"]["mode"]["const"], "ordinary")
        self.assertEqual(
            self.schema["properties"]["role"]["enum"],
            ["implementer", "reviewer", "verifier", "integrator"],
        )
        self.assertTrue(self.schema["properties"]["conflict_keys"]["uniqueItems"])

    def test_fixture_payloads_conform_to_structural_schema_contract(self):
        required = set(self.schema["required"])
        properties = self.schema["properties"]
        roles = set(properties["role"]["enum"])
        task_pattern = re.compile(properties["task"]["pattern"])
        entry_pattern = re.compile(properties["entry_ref"]["pattern"])
        control_pattern = re.compile(properties["control_ref"]["pattern"])

        names = []
        for case in self.fixtures["cases"]:
            names.append(case["name"])
            payload = case["payload"]
            self.assertEqual(set(payload), required, case["name"])
            self.assertEqual(payload["schema"], 1, case["name"])
            self.assertEqual(payload["mode"], "ordinary", case["name"])
            self.assertIn(payload["role"], roles, case["name"])
            self.assertRegex(payload["task"], task_pattern, case["name"])
            self.assertRegex(payload["entry_ref"], entry_pattern, case["name"])
            self.assertRegex(payload["control_ref"], control_pattern, case["name"])
            self.assertIsInstance(payload["scope_ready"], bool, case["name"])
            self.assertIsInstance(payload["blocked"], bool, case["name"])
            self.assertIsInstance(
                payload["requires_user_confirmation"], bool, case["name"]
            )
            self.assertEqual(
                len(payload["conflict_keys"]),
                len(set(payload["conflict_keys"])),
                case["name"],
            )
        self.assertEqual(len(names), len(set(names)))

    @staticmethod
    def _context_valid(case):
        if case["marker_count"] != 1:
            return False
        if not case["issue_open"] or not case["entry_open"]:
            return False
        if not case["task_identity_matches"]:
            return False
        if not case["control_unique_and_matches"]:
            return False

        payload = case["payload"]
        status = case["control_work_status"]
        tag = case["next_action_tag"]

        if payload["blocked"]:
            if status != "BLOCKED":
                return False
            if payload["requires_user_confirmation"] and tag != "USER_DECISION":
                return False
            return True

        if payload["requires_user_confirmation"]:
            # v1 has no canonical autonomous mapping for ad-hoc/manual Human Gates.
            return False

        if not payload["scope_ready"]:
            return True

        required_stage = {
            "implementer": ("READY_FOR_IMPLEMENTATION", "IMPLEMENT"),
            "reviewer": ("AWAITING_REVIEW", "REVIEW"),
            "verifier": ("AWAITING_REVIEW", "VERIFY"),
            "integrator": ("AWAITING_REVIEW", "MERGE"),
        }
        return (status, tag) == required_stage[payload["role"]]

    def test_normative_context_and_claimability_fixtures(self):
        for case in self.fixtures["cases"]:
            with self.subTest(case=case["name"]):
                valid = self._context_valid(case)
                self.assertEqual(valid, case["expected_context_valid"])

                payload = case["payload"]
                claimable_before_runtime = (
                    valid
                    and payload["scope_ready"]
                    and not payload["blocked"]
                    and not payload["requires_user_confirmation"]
                )
                self.assertEqual(
                    claimable_before_runtime,
                    case["expected_claimable_before_runtime_conflicts"],
                )

                if "expected_claimable_after_runtime_conflicts" in case:
                    claimable_after_runtime = claimable_before_runtime and not case.get(
                        "runtime_conflict", False
                    )
                    self.assertEqual(
                        claimable_after_runtime,
                        case["expected_claimable_after_runtime_conflicts"],
                    )


if __name__ == "__main__":
    unittest.main()
