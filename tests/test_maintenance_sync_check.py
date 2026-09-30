import unittest

try:
    from tools import maintenance_sync_check as ms
except ImportError:
    ms = None


CONTROL_BODY_SHA = "sha256:" + "a" * 64
OWNER_BODY_SHA = "sha256:" + "b" * 64
REPORT_ID = "sha256:" + "c" * 64


def report(**overrides):
    value = {
        "schema_version": "maintenance-audit-report.v1",
        "report_id": REPORT_ID,
        "repository": "o/r",
        "control_ref": "kinoko34077/devflow#1",
        "disposition": "AUTO_ADVANCE",
        "reason_codes": ["EXACT_OWNER_TERMINAL"],
        "finding_classes": ["CONTROL_ACTIVE_WORK_TERMINAL"],
        "owner_class": "TERMINAL",
        "owner_ref": "o/r#7",
        "next_transition": "WITHDRAW_STALE_CONTROL_CANDIDATE",
        "producer_active": False,
        "human_gate": False,
        "reviewer_gate": False,
        "external_wait": False,
        "security_gate": False,
    }
    value.update(overrides)
    return value


def control_snapshot(**overrides):
    value = {
        "repository": "o/r",
        "control_ref": "kinoko34077/devflow#1",
        "body_sha256": CONTROL_BODY_SHA,
        "body": (
            "before\n"
            "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->\n"
            "{\n"
            '  "schema_version": 1,\n'
            '  "source_ref": "kinoko34077/devflow#1",\n'
            '  "repository": "o/r",\n'
            '  "candidates": [\n'
            "    {\n"
            '      "task": "o/r#7",\n'
            '      "task_body_sha256": "' + OWNER_BODY_SHA + '",\n'
            '      "task_work_status": "READY_FOR_IMPLEMENTATION",\n'
            '      "entry_ref": "https://github.com/o/r/issues/7",\n'
            '      "scope_ready": true,\n'
            '      "blocked": false,\n'
            '      "requires_user_confirmation": false,\n'
            '      "conflict_keys": ["component:o/r:test"],\n'
            '      "roles": [{"role":"implementer","next_action_tag":"IMPLEMENT"}]\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->\n"
            "after\n"
        ),
        "candidate_tasks": ["o/r#7"],
        "producer_active": False,
        "human_gate": False,
        "reviewer_gate": False,
        "external_wait": False,
        "security_gate": False,
    }
    value.update(overrides)
    return value


def owner_snapshot(**overrides):
    value = {
        "repository": "o/r",
        "owner_ref": "o/r#7",
        "body_sha256": OWNER_BODY_SHA,
        "state": "CLOSED",
        "runnable": False,
        "terminal": True,
        "human_gate": False,
        "reviewer_gate": False,
        "external_wait": False,
        "security_gate": False,
    }
    value.update(overrides)
    return value


class MaintenanceSyncCheckPlanningTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            ms,
            "maintenance_sync_check module must exist",
        )

    def test_eligible_stale_candidate_builds_single_allowlisted_plan(self):
        plan = ms.build_sync_check_plan(
            report(),
            control_snapshot(),
            owner_snapshot(),
        )
        self.assertIsNotNone(plan)
        self.assertEqual(
            plan.kind,
            "WITHDRAW_STALE_CONTROL_CANDIDATE",
        )
        self.assertEqual(plan.repository, "o/r")
        self.assertEqual(plan.control_ref, "kinoko34077/devflow#1")
        self.assertEqual(plan.owner_ref, "o/r#7")
        self.assertEqual(
            plan.expected_control_body_sha256,
            CONTROL_BODY_SHA,
        )
        self.assertEqual(
            plan.expected_owner_body_sha256,
            OWNER_BODY_SHA,
        )
        self.assertEqual(plan.candidate_task_ref, "o/r#7")
        self.assertEqual(plan.report_id, REPORT_ID)

    def test_owner_must_be_terminal_and_nonrunnable(self):
        for owner in (
            owner_snapshot(terminal=False),
            owner_snapshot(runnable=True),
            owner_snapshot(state="OPEN"),
        ):
            with self.subTest(owner=owner):
                self.assertIsNone(
                    ms.build_sync_check_plan(
                        report(),
                        control_snapshot(),
                        owner,
                    )
                )

    def test_candidate_must_still_exist(self):
        self.assertIsNone(
            ms.build_sync_check_plan(
                report(),
                control_snapshot(candidate_tasks=[]),
                owner_snapshot(),
            )
        )

    def test_any_active_gate_or_producer_blocks_plan(self):
        for field in (
            "producer_active",
            "human_gate",
            "reviewer_gate",
            "external_wait",
            "security_gate",
        ):
            with self.subTest(field=field):
                self.assertIsNone(
                    ms.build_sync_check_plan(
                        report(**{field: True}),
                        control_snapshot(),
                        owner_snapshot(),
                    )
                )

    def test_only_exact_allowlisted_transition_is_plannable(self):
        cases = (
            report(disposition="NO_ACTION"),
            report(next_transition="RECOVERY_ASSESSMENT"),
            report(owner_ref=None),
            report(finding_classes=["SEMANTIC_PROJECTION_SUSPECTED"]),
        )
        for value in cases:
            with self.subTest(value=value):
                self.assertIsNone(
                    ms.build_sync_check_plan(
                        value,
                        control_snapshot(),
                        owner_snapshot(),
                    )
                )

    def test_identity_mismatch_fails_closed(self):
        with self.assertRaises(ms.SyncCheckContractError):
            ms.build_sync_check_plan(
                report(),
                control_snapshot(repository="other/repo"),
                owner_snapshot(),
            )


if __name__ == "__main__":
    unittest.main()
