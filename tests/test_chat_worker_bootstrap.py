import copy
import json
import unittest
from pathlib import Path

from tools import chat_worker_bootstrap as cwb


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((ROOT / "docs/spec/examples/chat-worker-bootstrap").glob("*.json"))
SCHEMAS = ROOT / "docs/spec/schemas"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def example(name):
    return load(next(path for path in EXAMPLES if path.name.startswith(name)))


class ExampleTests(unittest.TestCase):
    def test_examples_cover_every_disposition(self):
        seen = {load(path)["expected"]["disposition"] for path in EXAMPLES}
        self.assertEqual(set(cwb.DISPOSITIONS), seen)

    def test_every_example_classifies_to_its_expected_result(self):
        self.assertGreaterEqual(len(EXAMPLES), 20)
        for path in EXAMPLES:
            with self.subTest(example=path.name):
                data = load(path)
                result = cwb.classify(data["request"], data["evidence"])
                cwb.validate_result(result)
                self.assertEqual(data["expected"], result)

    def test_required_negative_cases_from_191(self):
        expected = {
            "07-control-not-found": ("NEEDS_EVIDENCE", "CONTROL_NOT_FOUND"),
            "08-duplicate-controls": ("NEEDS_EVIDENCE", "CONTROL_DUPLICATE"),
            "09-untrusted-control": ("NEEDS_EVIDENCE", "CONTROL_UNTRUSTED"),
            "10-stale-digest-only": ("NO_ELIGIBLE_WORK", "ALL_CANDIDATES_OMITTED"),
            "11-candidate-human-gate": ("NEEDS_HUMAN", "HUMAN_GATE"),
            "13-control-external-blocker": ("WAIT_EXTERNAL", "EXTERNAL_BLOCKER"),
            "14-capability-mismatch": ("NO_ELIGIBLE_WORK", "ALL_CANDIDATES_OMITTED"),
            "16-live-claim-conflict": ("NO_ELIGIBLE_WORK", "ALL_CANDIDATES_OMITTED"),
            "17-reviewer-independence-conflict": ("NO_ELIGIBLE_WORK", "ALL_CANDIDATES_OMITTED"),
            "04-recovery-only": ("RECOVERY_WORK", "ELIGIBLE_RECOVERY_DEMAND"),
            "25-unknown-request-schema": ("NEEDS_EVIDENCE", "SCHEMA_UNSUPPORTED"),
            "19-provider-surface-missing": ("NEEDS_EVIDENCE", "PROVIDER_SURFACE_MISSING"),
            "20-no-candidates-published": ("NO_ELIGIBLE_WORK", "NO_CANDIDATES_PUBLISHED"),
        }
        for name, (disposition, reason) in expected.items():
            with self.subTest(case=name):
                result = example(name)["expected"]
                self.assertEqual((disposition, reason), (result["disposition"], result["reason_code"]))


class ContractPropertyTests(unittest.TestCase):
    def test_broad_instruction_without_issue_number_proceeds_without_question(self):
        data = example("01-broad-instruction-fresh-claim")
        self.assertNotIn("#", data["request"]["work_intent"])
        result = cwb.classify(data["request"], data["evidence"])
        self.assertEqual("CLAIM_AND_WORK", result["disposition"])
        self.assertEqual("CLAIM_THEN_ACKNOWLEDGE", result["next_authoritative_step"])

    def test_same_inputs_are_provider_neutral(self):
        for path in EXAMPLES:
            data = load(path)
            if data["request"].get("schema_version") != cwb.REQUEST_SCHEMA:
                continue
            baseline = cwb.classify(data["request"], data["evidence"])
            for system in cwb.WORKER_SYSTEMS:
                with self.subTest(example=path.name, system=system):
                    request = dict(data["request"], worker_system=system)
                    result = cwb.classify(request, data["evidence"])
                    for field in ("disposition", "reason_code", "task_ref", "role", "action", "omissions"):
                        self.assertEqual(baseline[field], result[field])

    def test_work_intent_never_changes_selection(self):
        data = example("02-two-fresh-candidates-rank-order")
        baseline = cwb.classify(data["request"], data["evidence"])
        for intent in (None, "", "please work on #81 first", "レビューだけして"):
            with self.subTest(intent=intent):
                result = cwb.classify(dict(data["request"], work_intent=intent), data["evidence"])
                self.assertEqual(baseline["task_ref"], result["task_ref"])
                self.assertEqual(baseline["disposition"], result["disposition"])

    def test_candidate_order_does_not_change_selection(self):
        for name in ("02-two-fresh-candidates-rank-order", "05-recovery-precedes-fresh"):
            with self.subTest(example=name):
                data = example(name)
                evidence = copy.deepcopy(data["evidence"])
                evidence["frontier"]["candidates"].reverse()
                self.assertEqual(data["expected"], cwb.classify(data["request"], evidence))

    def test_provider_identity_never_supplies_capabilities(self):
        data = example("14-capability-mismatch")
        for system in cwb.WORKER_SYSTEMS:
            with self.subTest(system=system):
                request = dict(data["request"], worker_system=system)
                self.assertEqual("NO_ELIGIBLE_WORK", cwb.classify(request, data["evidence"])["disposition"])

    def test_tool_surfaces_are_not_capabilities(self):
        data = example("14-capability-mismatch")
        request = dict(data["request"], tool_surfaces=sorted(data["request"]["tool_surfaces"] + ["rust"]))
        self.assertEqual("NO_ELIGIBLE_WORK", cwb.classify(request, data["evidence"])["disposition"])

    def test_at_most_one_candidate_is_selected(self):
        result = example("02-two-fresh-candidates-rank-order")["expected"]
        self.assertEqual("kinoko34077/execution-coordinator#80", result["task_ref"])
        self.assertIsInstance(result["task_ref"], str)

    def test_same_publication_attempt_is_omitted_but_fresh_attempt_can_consume(self):
        from tools import maintenance_supply as ms

        data = copy.deepcopy(example("01-broad-instruction-fresh-claim"))
        candidate = data["evidence"]["frontier"]["candidates"][0]
        publisher_attempt = data["request"]["execution_attempt_id"]
        supply = {"publisher_execution_attempt_id": publisher_attempt}

        candidate["published_by_this_attempt"] = ms.published_by_attempt(
            supply,
            data["request"]["execution_attempt_id"],
        )
        same = cwb.classify(data["request"], data["evidence"])
        self.assertEqual("NO_ELIGIBLE_WORK", same["disposition"])
        self.assertIn(
            {
                "task_ref": candidate["task_ref"],
                "role": candidate["role"],
                "reason": "PUBLISHED_BY_THIS_ATTEMPT",
            },
            same["omissions"],
        )

        later_request = dict(
            data["request"],
            execution_attempt_id="chatgpt-maintenance-fresh-attempt",
        )
        candidate["published_by_this_attempt"] = ms.published_by_attempt(
            supply,
            later_request["execution_attempt_id"],
        )
        later = cwb.classify(later_request, data["evidence"])
        self.assertEqual("CLAIM_AND_WORK", later["disposition"])
        self.assertEqual(candidate["task_ref"], later["task_ref"])

    def test_coordinator_worker_id_binds_system_and_session(self):
        result = example("01-broad-instruction-fresh-claim")["expected"]
        self.assertEqual("claude:claude-20260928-a", result["coordinator_worker_id"])

    def test_malformed_requests_fail_closed(self):
        base = example("01-broad-instruction-fresh-claim")
        mutations = {
            "unknown field": {"extra": 1},
            "bad system": {"worker_system": "gemini"},
            "bad repo": {"target_repository": "no-slash"},
            "dup tag": {"capabilities": ["python", "python"]},
            "upper tag": {"capabilities": ["Python"]},
            "secret id": {"worker_session_id": "ghp_abcdef"},
            "long intent": {"work_intent": "x" * 501},
        }
        for label, patch in mutations.items():
            with self.subTest(case=label):
                result = cwb.classify(dict(base["request"], **patch), base["evidence"])
                self.assertEqual("NEEDS_EVIDENCE", result["disposition"])
                self.assertEqual("REQUEST_INVALID", result["reason_code"])
                cwb.validate_result(result)

    def test_malformed_evidence_fails_closed(self):
        base = example("01-broad-instruction-fresh-claim")
        cases = {
            "not object": "x",
            "bad schema": dict(base["evidence"], schema_version="v0"),
            "naive time": dict(base["evidence"], observed_at="2026-09-28T14:59:00"),
            "bad claimability": dict(
                base["evidence"],
                frontier={"complete": True, "candidates": [dict(base["evidence"]["frontier"]["candidates"][0], claimability="MAYBE")]},
            ),
            "duplicate candidate": dict(
                base["evidence"],
                frontier={"complete": True, "candidates": base["evidence"]["frontier"]["candidates"] * 2},
            ),
        }
        for label, evidence in cases.items():
            with self.subTest(case=label):
                result = cwb.classify(base["request"], evidence)
                self.assertEqual("NEEDS_EVIDENCE", result["disposition"])
                self.assertIsNone(result["task_ref"])


class PortfolioV2ContractTests(unittest.TestCase):
    def _portfolio_case(self):
        data = copy.deepcopy(example("02-two-fresh-candidates-rank-order"))
        data["request"]["target_repository"] = None
        data["request"]["worker_session_id"] = "chatgpt-portfolio-a"
        data["request"]["execution_attempt_id"] = "chatgpt-portfolio-a:c1"
        data["request"]["worker_system"] = "chatgpt"
        data["request"]["tool_surfaces"] = ["coordinator:claim", "github:read", "github:write"]
        data["evidence"]["controls"] = [
            {"ref":"kinoko34077/devflow#28","managed_repository":"kinoko34077/refil-viewer","state":"open","trusted":True,"repository_state":"ACTIVE","human_gate":False,"external_blocker":False},
            {"ref":"kinoko34077/devflow#59","managed_repository":"kinoko34077/kinotch-repo-monitor","state":"open","trusted":True,"repository_state":"ACTIVE","human_gate":False,"external_blocker":False},
        ]
        a,b=data["evidence"]["frontier"]["candidates"][:2]
        a.update(task_ref="kinoko34077/refil-viewer#6", role="reviewer", action="REVIEW", fingerprint="sha256:"+"a"*64, rank_key=[1,0,0,3,1,""])
        b.update(task_ref="kinoko34077/kinotch-repo-monitor#30", role="implementer", action="IMPLEMENT", fingerprint="sha256:"+"b"*64, rank_key=[2,0,0,1,1,""])
        for item in (a,b):
            item.update(digest_fresh=True, dependency_ready=True, human_gate=False, external_blocker=False, reviewer_independence_conflict=False, published_by_this_attempt=False, claimability="CLAIMABLE", required_capabilities=[], required_environment=[])
        data["evidence"]["frontier"]["candidates"]=[a,b]
        return data

    def test_null_target_selects_from_complete_cross_repository_frontier(self):
        data=self._portfolio_case()
        result=cwb.classify(data["request"], data["evidence"])
        self.assertEqual("REVIEW_WORK", result["disposition"])
        self.assertEqual("kinoko34077/refil-viewer#6", result["task_ref"])
        self.assertEqual(["kinoko34077/devflow#28", "kinoko34077/refil-viewer#6"], result["source_refs"])

    def test_portfolio_candidate_order_does_not_change_selection(self):
        data=self._portfolio_case()
        baseline=cwb.classify(data["request"], data["evidence"])
        data["evidence"]["frontier"]["candidates"].reverse()
        self.assertEqual(baseline, cwb.classify(data["request"], data["evidence"]))

    def test_portfolio_skips_human_gated_repository_when_another_candidate_is_eligible(self):
        data=self._portfolio_case()
        data["evidence"]["controls"][0]["human_gate"] = True
        result=cwb.classify(data["request"], data["evidence"])
        self.assertEqual("CLAIM_AND_WORK", result["disposition"])
        self.assertEqual("kinoko34077/kinotch-repo-monitor#30", result["task_ref"])

    def test_portfolio_does_not_apply_control_external_blocker_to_unblocked_candidate(self):
        data=self._portfolio_case()
        candidate=data["evidence"]["frontier"]["candidates"][0]
        candidate.update(role="implementer", action="IMPLEMENT", rank_key=[1,0,0,1,1,""])
        data["evidence"]["controls"][0]["external_blocker"] = True

        result=cwb.classify(data["request"], data["evidence"])

        self.assertEqual("CLAIM_AND_WORK", result["disposition"])
        self.assertEqual("kinoko34077/refil-viewer#6", result["task_ref"])

    def test_portfolio_still_omits_candidate_level_external_blocker(self):
        data=self._portfolio_case()
        candidate=data["evidence"]["frontier"]["candidates"][0]
        candidate.update(role="implementer", action="IMPLEMENT", rank_key=[1,0,0,1,1,""], external_blocker=True)

        result=cwb.classify(data["request"], data["evidence"])

        self.assertEqual("CLAIM_AND_WORK", result["disposition"])
        self.assertEqual("kinoko34077/kinotch-repo-monitor#30", result["task_ref"])
        self.assertIn(
            {"task_ref":"kinoko34077/refil-viewer#6","role":"implementer","reason":"EXTERNAL_BLOCKER"},
            result["omissions"],
        )

    def test_portfolio_duplicate_control_for_candidate_repository_fails_closed(self):
        data=self._portfolio_case()
        duplicate=copy.deepcopy(data["evidence"]["controls"][0])
        duplicate["ref"]="kinoko34077/devflow#228"
        data["evidence"]["controls"].append(duplicate)
        result=cwb.classify(data["request"], data["evidence"])
        self.assertEqual(("NEEDS_EVIDENCE","CONTROL_DUPLICATE"),(result["disposition"],result["reason_code"]))

    def test_portfolio_spreads_equal_rank_class_by_worker_attempt_hash(self):
        import hashlib
        data=self._portfolio_case()
        a,b=data["evidence"]["frontier"]["candidates"]
        a.update(role="implementer", action="IMPLEMENT", rank_key=[1,0,0,1,1,""])
        b.update(role="implementer", action="IMPLEMENT", rank_key=[1,0,0,1,1,""])
        worker="chatgpt:" + data["request"]["worker_session_id"]
        attempt=data["request"]["execution_attempt_id"]
        expected=min(
            (a,b),
            key=lambda item:(hashlib.sha256((worker+"\0"+item["task_ref"]+"\0"+attempt).encode()).hexdigest(),item["task_ref"],item["role"]),
        )["task_ref"]
        self.assertEqual(expected, cwb.classify(data["request"],data["evidence"])["task_ref"])

    def test_portfolio_metadata_schema_encodes_dependency_pair_invariant(self):
        schema=load(SCHEMAS / "execution-portfolio-metadata.v1.schema.json")
        entry=schema["properties"]["entries"]["items"]
        self.assertIn("allOf", entry)
        encoded=json.dumps(entry["allOf"], sort_keys=True)
        self.assertIn("dependency_ready", encoded)
        self.assertIn("dependency_order", encoded)

    def test_portfolio_metadata_contract_is_versioned_and_fingerprint_bound(self):
        schema_path=SCHEMAS / "execution-portfolio-metadata.v1.schema.json"
        self.assertTrue(schema_path.exists(), "portfolio metadata schema must exist")
        schema=load(schema_path)
        self.assertEqual("execution-portfolio-metadata.v1", schema["properties"]["schema_version"]["const"])
        required=set(schema["properties"]["entries"]["items"]["required"])
        self.assertTrue({"task","role","task_body_sha256","candidate_fingerprint","dependency_ready","dependency_order","readiness_class","required_capabilities","required_environment","observed_at","fresh_until"} <= required)
        spec=(ROOT / "docs/spec/PORTFOLIO_PICKUP_V2.md").read_text(encoding="utf-8") if (ROOT / "docs/spec/PORTFOLIO_PICKUP_V2.md").exists() else ""
        self.assertIn("DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1_BEGIN", spec)
        self.assertIn("worker-scoped", spec)


class SchemaConsistencyTests(unittest.TestCase):
    def schema(self, name):
        return load(SCHEMAS / f"chat-worker-bootstrap-{name}.v1.schema.json")

    def test_request_schema_matches_contract(self):
        schema = self.schema("request")
        self.assertEqual(sorted(cwb.REQUEST_FIELDS), sorted(schema["required"]))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(cwb.REQUEST_SCHEMA, schema["properties"]["schema_version"]["const"])
        self.assertEqual(list(cwb.WORKER_SYSTEMS), schema["properties"]["worker_system"]["enum"])

    def test_result_schema_matches_contract(self):
        schema = self.schema("result")
        props = schema["properties"]
        self.assertEqual(list(cwb.RESULT_FIELDS), schema["required"])
        self.assertEqual(list(cwb.DISPOSITIONS), props["disposition"]["enum"])
        self.assertEqual(list(cwb.REASON_CODES), props["reason_code"]["enum"])
        self.assertEqual(list(cwb.OMISSION_REASONS), props["omissions"]["items"]["properties"]["reason"]["enum"])
        self.assertEqual(sorted(set(cwb.NEXT_STEPS.values())), props["next_authoritative_step"]["enum"])

    def test_spec_lists_every_reason_code_and_disposition(self):
        spec = (ROOT / "docs/spec/CHAT_WORKER_BOOTSTRAP.md").read_text(encoding="utf-8")
        for token in cwb.REASON_CODES + cwb.DISPOSITIONS + cwb.OMISSION_REASONS:
            with self.subTest(token=token):
                self.assertIn(f"`{token}`", spec)


if __name__ == "__main__":
    unittest.main()
