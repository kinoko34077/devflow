import unittest

try:
    from tools import maintenance_audit as ma
    from tools import maintenance_triage as mt
except ImportError:
    ma = None
    mt = None


REPORT_ID = "sha256:" + "a" * 64
OTHER_REPORT_ID = "sha256:" + "b" * 64


def report(**overrides):
    value = {
        "schema_version": "maintenance-audit-report.v1",
        "report_id": REPORT_ID,
        "repository": "o/r",
        "control_ref": "kinoko34077/devflow#1",
        "observed_at": "2026-10-01T00:00:00Z",
        "disposition": "NO_ACTION",
        "reason_codes": ["AUTHORITATIVE_SOURCES_CONSISTENT"],
        "finding_classes": [],
        "owner_class": "INACTIVE",
        "owner_ref": "o/r#7",
        "evidence_refs": [
            "kinoko34077/devflow#1",
            "o/r#7",
        ],
        "recheck_trigger": "AUTHORITATIVE_EVIDENCE_CHANGED",
    }
    value.update(overrides)
    return value


class MaintenanceTriageTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            mt,
            "maintenance_triage module must exist",
        )
        self.assertIsNotNone(
            ma,
            "maintenance_audit module must exist",
        )

    def test_clean_state_is_not_tracked(self):
        decision = mt.triage(report())
        self.assertEqual(decision.action, "NO_TRACK")
        self.assertIsNone(decision.work_class)

    def test_active_producer_does_not_create_supply(self):
        decision = mt.triage(
            report(
                reason_codes=["TRUSTED_PRODUCER_ACTIVE"],
                finding_classes=["ACTIVE_PRODUCER_YIELD"],
                owner_class="ACTIVE_PRODUCER",
            )
        )
        self.assertEqual(decision.action, "NO_TRACK")

    def test_existing_gates_are_routed_not_republished(self):
        cases = (
            ("NEEDS_REVIEWER", "REVIEW_GATE_YIELD"),
            ("NEEDS_HUMAN", "HUMAN_GATE_YIELD"),
            ("WAIT_EXTERNAL", "EXTERNAL_WAIT_YIELD"),
        )
        for disposition, finding in cases:
            with self.subTest(disposition=disposition):
                decision = mt.triage(
                    report(
                        disposition=disposition,
                        finding_classes=[finding],
                    )
                )
                self.assertEqual(
                    decision.action,
                    "ROUTE_EXISTING_GATE",
                )
                self.assertIsNone(decision.work_class)

    def test_ambiguous_or_semantic_finding_is_nonrunnable(self):
        for finding in (
            "SOURCE_UNAVAILABLE_OR_AMBIGUOUS",
            "SEMANTIC_PROJECTION_SUSPECTED",
        ):
            with self.subTest(finding=finding):
                decision = mt.triage(
                    report(
                        disposition="NEEDS_EVIDENCE",
                        finding_classes=[finding],
                    )
                )
                self.assertEqual(
                    decision.action,
                    "RECORD_NONRUNNABLE_FINDING",
                )
                self.assertIsNone(decision.work_class)

    def test_allowlisted_projection_drift_plans_sync_check(self):
        decision = mt.triage(
            report(
                disposition="AUTO_ADVANCE",
                reason_codes=["EXACT_OWNER_TERMINAL"],
                finding_classes=[
                    "CONTROL_ACTIVE_WORK_TERMINAL"
                ],
                next_transition=(
                    "WITHDRAW_STALE_CONTROL_CANDIDATE"
                ),
                owner_class="TERMINAL",
            )
        )
        self.assertEqual(decision.action, "PLAN_SYNC_CHECK")
        self.assertEqual(decision.work_class, "sync-check")
        self.assertEqual(decision.owner_ref, "o/r#7")

    def test_non_allowlisted_auto_advance_uses_existing_owner_only(self):
        decision = mt.triage(
            report(
                disposition="AUTO_ADVANCE",
                finding_classes=["RECOVERY_CANDIDATE"],
                next_transition="RECOVERY_ASSESSMENT",
            )
        )
        self.assertEqual(
            decision.action,
            "PUBLISH_EXISTING_OWNER",
        )
        self.assertEqual(decision.owner_ref, "o/r#7")
        self.assertEqual(decision.work_class, "triage")

        missing_owner = mt.triage(
            report(
                disposition="AUTO_ADVANCE",
                owner_ref=None,
                finding_classes=["RECOVERY_CANDIDATE"],
                next_transition="RECOVERY_ASSESSMENT",
            )
        )
        self.assertEqual(
            missing_owner.action,
            "RECORD_NONRUNNABLE_FINDING",
        )
        self.assertIsNone(missing_owner.work_class)


    def test_real_audit_report_carries_owner_into_sync_check_triage(self):
        observation = {
            "repository": "o/r",
            "observed_at": "2026-10-01T00:00:00Z",
            "control_count": 1,
            "control": {
                "ref": "kinoko34077/devflow#1",
                "repository": "o/r",
                "trusted": True,
                "revision": "a" * 40,
                "active_owner_ref": "o/r#7",
                "candidate_present": True,
            },
            "owner": {
                "ref": "o/r#7",
                "repository": "o/r",
                "revision": "b" * 40,
                "state": "CLOSED",
                "runnable": False,
                "terminal": True,
            },
            "source_status": "OK",
            "producer_active": False,
            "reviewer_gate": False,
            "human_gate": False,
            "external_wait": False,
            "semantic_projection_suspected": False,
            "search_state": None,
            "evidence_refs": [
                "kinoko34077/devflow#1",
                "o/r#7",
            ],
        }

        audit_report = ma.classify_repository(observation)
        decision = mt.triage(audit_report)

        self.assertEqual(decision.action, "PLAN_SYNC_CHECK")
        self.assertEqual(decision.owner_ref, "o/r#7")

    def test_same_report_identity_yields_same_decision(self):
        first = mt.triage(report())
        second = mt.triage(
            report(observed_at="2026-10-01T00:30:00Z")
        )
        self.assertEqual(first, second)

    def test_changed_report_identity_changes_decision_identity(self):
        first = mt.triage(report())
        second = mt.triage(
            report(report_id=OTHER_REPORT_ID)
        )
        self.assertNotEqual(
            first.report_id,
            second.report_id,
        )

    def test_unknown_disposition_fails_closed(self):
        with self.assertRaises(mt.TriageContractError):
            mt.triage(
                report(disposition="MADE_UP")
            )


if __name__ == "__main__":
    unittest.main()
