import json
import unittest
from pathlib import Path

from tools import outcome_observation_pilot as pilot


TASK = "kinoko34077/devflow#839"
BODY_SHA = "b" * 64


def packet(**overrides):
    value = {
        "task_ref": TASK,
        "issue_body_sha256": BODY_SHA,
        "required_surface": "PUBLIC_BROWSER",
        "required_target": "git:f38d562edfda0bbaefaa3e1b6d71ccb078c26364",
        "observed_surface": "PUBLIC_BROWSER",
        "observed_target": "git:f38d562edfda0bbaefaa3e1b6d71ccb078c26364",
        "observed_result": "SUCCESS",
        "evidence_refs": [
            "https://github.com/kinoko34077/japanese-orthography/issues/310#issuecomment-6106750343",
        ],
    }
    value.update(overrides)
    return value


def event(body):
    return {"pull_request": {"body": body}}


def marked(value):
    return f"PR notes\n{pilot.BEGIN}\n{json.dumps(value)}\n{pilot.END}\n"


class OutcomeObservationPilotTests(unittest.TestCase):
    def test_missing_packet_is_an_explicit_skip(self):
        self.assertEqual(pilot.evaluate_event(event("ordinary PR")), (0, "SKIPPED_NO_OUTCOME_PACKET"))

    def test_null_pr_body_is_an_explicit_skip_but_missing_event_shape_is_invalid(self):
        self.assertEqual(
            pilot.evaluate_event({"pull_request": {"body": None}}),
            (0, "SKIPPED_NO_OUTCOME_PACKET"),
        )
        self.assertEqual(
            pilot.evaluate_event({}),
            (2, "OUTCOME_PILOT=INVALID_EVENT"),
        )

    def test_duplicate_or_malformed_packet_fails_closed(self):
        for body in (
            f"{pilot.BEGIN}{{\"a\":1,\"a\":2}}{pilot.END}",
            f"{pilot.BEGIN}{{bad}}{pilot.END}",
            f"{pilot.BEGIN}{{}}",
        ):
            with self.subTest(body=body):
                code, message = pilot.evaluate_event(event(body))
                self.assertEqual(code, 2)
                self.assertIn("INVALID_PACKET", message)

    def test_public_browser_success_packet_is_only_declaration_consistency(self):
        code, message = pilot.evaluate_event(event(marked(packet())))
        self.assertEqual(code, 0)
        self.assertIn("OUTCOME_PILOT=DECLARED_ALIGNED", message)

    def test_fixture_pass_cannot_claim_public_browser_success(self):
        fixture_ref = "https://github.com/kinoko34077/japanese-orthography/issues/310#issuecomment-6106079188"
        fixture_target = "git:380b395cf735fafed717fed7b33a22f2a88401de"
        code, message = pilot.evaluate_event(event(marked(packet(
            required_target=fixture_target,
            observed_target=fixture_target,
            observed_surface="FIXTURE_PARITY",
            evidence_refs=[fixture_ref],
        ))))
        self.assertEqual(code, 1)
        self.assertIn("SURFACE_MISMATCH", message)

    def test_target_mismatch_is_detected_even_when_surface_matches(self):
        code, message = pilot.evaluate_event(event(marked(packet(observed_target="git:ccb788aeeda0c5dee1e37b57aa1e8a26f7bb4769"))))
        self.assertEqual(code, 1)
        self.assertIn("TARGET_MISMATCH", message)

    def test_valid_negative_is_not_misclassified_as_failure_or_acceptance(self):
        code, message = pilot.evaluate_event(event(marked(packet(observed_result="VALID_NEGATIVE"))))
        self.assertEqual(code, 0)
        self.assertIn("observed_result=VALID_NEGATIVE", message)

    def test_unknown_and_not_run_remain_nonblocking_but_explicit(self):
        for status in ("UNKNOWN", "NOT_RUN"):
            with self.subTest(status=status):
                code, message = pilot.evaluate_event(event(marked(packet(observed_result=status))))
                self.assertEqual(code, 0)
                self.assertIn(f"OUTCOME_PILOT={status}", message)

    def test_live_physical_failure_report_with_unknown_ipa_is_not_promoted(self):
        report = packet(
            task_ref="kinoko34077/gesture-ime#203",
            issue_body_sha256="c" * 64,
            required_surface="PHYSICAL_RUNTIME",
            required_target="installed-ipa:identified-build",
            observed_surface="PHYSICAL_RUNTIME",
            observed_target=None,
            observed_result="FAILURE",
            evidence_refs=[
                "https://github.com/kinoko34077/gesture-ime/issues/203#issuecomment-6116020441",
            ],
        )
        code, message = pilot.evaluate_event(event(marked(report)))
        self.assertEqual(code, 0)
        self.assertIn("OUTCOME_PILOT=UNKNOWN", message)
        self.assertIn("observed_result=FAILURE", message)

    def test_missing_evidence_and_observed_failure_are_not_success(self):
        for value, expected in (
            (packet(evidence_refs=[]), "EVIDENCE_REFERENCE_MISSING"),
            (packet(observed_result="FAILURE"), "DECLARED_FAILURE"),
        ):
            with self.subTest(expected=expected):
                code, message = pilot.evaluate_event(event(marked(value)))
                self.assertEqual(code, 1)
                self.assertIn(expected, message)

    def test_workflow_runs_base_pinned_unprivileged_optional_evaluator(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/goal-plan-assessment-pilot.yml").read_text(encoding="utf-8")
        self.assertIn("permissions: {}", workflow)
        self.assertIn("pull_request:", workflow)
        self.assertIn("BASE_SHA: ${{ github.event.pull_request.base.sha }}", workflow)
        self.assertIn('git cat-file -e "${BASE_SHA}:tools/outcome_observation_pilot.py"', workflow)
        self.assertIn("python -m tools.outcome_observation_pilot", workflow)
        self.assertIn("OUTCOME_PILOT=SKIPPED_EVALUATOR_NOT_ON_BASE", workflow)


if __name__ == "__main__":
    unittest.main()
