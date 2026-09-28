from datetime import datetime, timedelta, timezone
import unittest

from tools.recovery_assessment import ArtifactEvidence, SessionEvidence, assess_session


UTC = timezone.utc
NOW = datetime(2026, 9, 28, 5, 0, tzinfo=UTC)


def session(**overrides):
    values = {
        "task_ref": "owner/repository#7",
        "session_id": "session-7",
        "status": "RUNNING",
        "last_trusted_update": NOW - timedelta(hours=2),
        "checkpoint": "committed partial implementation",
    }
    values.update(overrides)
    return SessionEvidence(**values)


class RecoveryAssessmentTests(unittest.TestCase):
    def test_recent_activity_keeps_running_session_out_of_recovery(self):
        result = assess_session(
            session(last_trusted_update=NOW - timedelta(minutes=20)),
            ArtifactEvidence(),
            observed_at=NOW,
        )

        self.assertEqual(result["disposition"], "NO_ACTION")
        self.assertEqual(result["assessment_kind"], "ACTIVE_SESSION")
        self.assertIn("TRUSTED_ACTIVITY_RECENT", result["reason_codes"])
        self.assertIsNone(result["transition"])

    def test_stale_session_without_artifact_requests_successor_eligibility_assessment(self):
        result = assess_session(session(), ArtifactEvidence(), observed_at=NOW)

        self.assertEqual(result["disposition"], "NEEDS_RECOVERY")
        self.assertEqual(result["assessment_kind"], "NO_ARTIFACT")
        self.assertIn("STALE_SESSION_WITHOUT_ARTIFACT", result["reason_codes"])
        self.assertEqual(result["transition"]["kind"], "SUCCESSOR_ELIGIBILITY_EVALUATION")

    def test_stale_partial_artifact_requests_recovery_without_session_mutation(self):
        result = assess_session(
            session(branch_ref="refs/heads/work/7"),
            ArtifactEvidence(
                has_durable_artifact=True,
                first_unfinished_action="run the repository regression suite",
            ),
            observed_at=NOW,
        )

        self.assertEqual(result["disposition"], "NEEDS_RECOVERY")
        self.assertEqual(result["assessment_kind"], "RECOVERABLE_PARTIAL_ARTIFACT")
        self.assertEqual(
            result["next_action"],
            "run the repository regression suite",
        )
        self.assertEqual(result["transition"]["kind"], "RECOVERY_ASSESSMENT")
        self.assertEqual(result["observed_status"], "RUNNING")

    def test_complete_enough_artifact_routes_to_pr_reconciliation(self):
        result = assess_session(
            session(),
            ArtifactEvidence(
                has_durable_artifact=True,
                complete_enough=True,
                pr_number=27,
                head_sha="a" * 40,
            ),
            observed_at=NOW,
        )

        self.assertEqual(result["disposition"], "AUTO_ADVANCE")
        self.assertEqual(result["assessment_kind"], "COMPLETE_ENOUGH_ARTIFACT")
        self.assertEqual(result["transition"]["kind"], "PR_RECONCILIATION")
        self.assertEqual(result["transition"]["expected_head_sha"], "a" * 40)

    def test_waiting_named_blocker_is_external_wait_not_recovery(self):
        result = assess_session(
            session(
                status="WAITING",
                last_trusted_update=NOW - timedelta(hours=3),
                named_blocker="required browser smoke",
                blocker_resolved=False,
            ),
            ArtifactEvidence(),
            observed_at=NOW,
        )

        self.assertEqual(result["disposition"], "WAIT_EXTERNAL")
        self.assertEqual(result["assessment_kind"], "STILL_WAITING")
        self.assertIn("NAMED_BLOCKER_ACTIVE", result["reason_codes"])
        self.assertIsNone(result["transition"])

    def test_explicit_terminal_session_never_gets_stale_inferred(self):
        result = assess_session(
            session(status="HANDOFF"),
            ArtifactEvidence(),
            observed_at=NOW,
        )

        self.assertEqual(result["disposition"], "NO_ACTION")
        self.assertEqual(result["assessment_kind"], "EXPLICIT_TERMINAL")
        self.assertIn("EXPLICIT_SESSION_TERMINAL", result["reason_codes"])

    def test_successor_collision_fails_closed(self):
        result = assess_session(
            session(successor_present=True),
            ArtifactEvidence(),
            observed_at=NOW,
        )

        self.assertEqual(result["disposition"], "NEEDS_EVIDENCE")
        self.assertEqual(result["assessment_kind"], "AMBIGUOUS_COLLISION")
        self.assertIn("SUCCESSOR_COLLISION", result["reason_codes"])

    def test_human_gate_never_becomes_recovery_ready(self):
        result = assess_session(
            session(),
            ArtifactEvidence(human_gate="release approval"),
            observed_at=NOW,
        )

        self.assertEqual(result["disposition"], "NEEDS_HUMAN")
        self.assertEqual(result["assessment_kind"], "HUMAN_GATE")
        self.assertIn("EXPLICIT_HUMAN_GATE", result["reason_codes"])
        self.assertIsNone(result["transition"])


if __name__ == "__main__":
    unittest.main()
