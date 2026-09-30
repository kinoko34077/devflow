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


def body_with_second_candidate():
    first = control_snapshot()["body"]
    second = (
        "    },\n"
        "    {\n"
        '      "task": "o/r#8",\n'
        '      "task_body_sha256": "sha256:' + "d" * 64 + '",\n'
        '      "task_work_status": "READY_FOR_IMPLEMENTATION",\n'
        '      "entry_ref": "https://github.com/o/r/issues/8",\n'
        '      "scope_ready": true,\n'
        '      "blocked": false,\n'
        '      "requires_user_confirmation": false,\n'
        '      "conflict_keys": ["component:o/r:other"],\n'
        '      "roles": [{"role":"implementer","next_action_tag":"IMPLEMENT"}]\n'
        "    }\n"
    )
    return first.replace("    }\n  ]\n}", second + "  ]\n}")


class FakeSyncTransport:
    def __init__(self, control, owner):
        self.control = dict(control)
        self.owner = dict(owner)
        self.writes = []

    def get_control(self, repository, control_ref):
        self.assert_identity(
            repository == self.control["repository"],
            control_ref == self.control["control_ref"],
        )
        return dict(self.control)

    def get_owner(self, repository, owner_ref):
        self.assert_identity(
            repository == self.owner["repository"],
            owner_ref == self.owner["owner_ref"],
        )
        return dict(self.owner)

    def update_control_body(
        self,
        repository,
        control_ref,
        expected_body_sha256,
        body,
    ):
        self.assert_identity(
            repository == self.control["repository"],
            control_ref == self.control["control_ref"],
            expected_body_sha256 == self.control["body_sha256"],
        )
        self.writes.append(body)
        self.control["body"] = body
        self.control["body_sha256"] = ms.canonical_body_sha256(body)
        self.control["candidate_tasks"] = (
            ["o/r#7"] if '"task": "o/r#7"' in body else []
        )
        return True

    @staticmethod
    def assert_identity(*conditions):
        if not all(conditions):
            raise AssertionError("transport identity guard failed")


class MaintenanceSyncCheckExecutorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            ms,
            "maintenance_sync_check module must exist",
        )

    def _plan_and_transport(self):
        control = control_snapshot()
        owner = owner_snapshot()
        plan = ms.build_sync_check_plan(
            report(),
            control,
            owner,
        )
        self.assertIsNotNone(plan)
        return plan, FakeSyncTransport(control, owner)

    def test_projection_editor_preserves_outside_and_other_candidate(self):
        body = body_with_second_candidate()
        edited = ms.withdraw_candidate_projection(
            body,
            repository="o/r",
            task_ref="o/r#7",
        )
        self.assertNotIn('"task": "o/r#7"', edited)
        self.assertIn('"task": "o/r#8"', edited)
        before_prefix, before_rest = body.split(
            "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->",
            1,
        )
        after_prefix, after_rest = edited.split(
            "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->",
            1,
        )
        self.assertEqual(after_prefix, before_prefix)
        before_suffix = before_rest.split(
            "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->",
            1,
        )[1]
        after_suffix = after_rest.split(
            "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->",
            1,
        )[1]
        self.assertEqual(after_suffix, before_suffix)

    def test_projection_editor_rejects_duplicate_markers(self):
        body = control_snapshot()["body"]
        malformed = body + (
            "\n<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->\n"
            "{}\n"
        )
        with self.assertRaises(ms.SyncCheckContractError):
            ms.withdraw_candidate_projection(
                malformed,
                repository="o/r",
                task_ref="o/r#7",
            )

    def test_executor_unchanged_identity_writes_once_and_confirms(self):
        plan, transport = self._plan_and_transport()
        result = ms.execute_sync_check(plan, transport)
        self.assertTrue(result.applied)
        self.assertFalse(result.already_applied)
        self.assertEqual(result.disposition, "AUTO_ADVANCE")
        self.assertEqual(len(transport.writes), 1)
        self.assertNotIn(
            '"task": "o/r#7"',
            transport.control["body"],
        )

    def test_executor_control_or_owner_drift_writes_nothing(self):
        for target in ("control", "owner"):
            with self.subTest(target=target):
                plan, transport = self._plan_and_transport()
                if target == "control":
                    transport.control["body_sha256"] = (
                        "sha256:" + "e" * 64
                    )
                else:
                    transport.owner["body_sha256"] = (
                        "sha256:" + "f" * 64
                    )
                result = ms.execute_sync_check(
                    plan,
                    transport,
                )
                self.assertFalse(result.applied)
                self.assertFalse(result.already_applied)
                self.assertEqual(
                    result.disposition,
                    "NEEDS_EVIDENCE",
                )
                self.assertEqual(transport.writes, [])

    def test_executor_new_gate_writes_nothing(self):
        cases = (
            ("human_gate", "NEEDS_HUMAN"),
            ("security_gate", "NEEDS_HUMAN"),
            ("reviewer_gate", "NEEDS_REVIEWER"),
            ("external_wait", "WAIT_EXTERNAL"),
            ("producer_active", "NO_ACTION"),
        )
        for field, disposition in cases:
            with self.subTest(field=field):
                plan, transport = self._plan_and_transport()
                transport.owner[field] = True
                result = ms.execute_sync_check(
                    plan,
                    transport,
                )
                self.assertFalse(result.applied)
                self.assertEqual(
                    result.disposition,
                    disposition,
                )
                self.assertEqual(transport.writes, [])

    def test_executor_second_run_is_already_applied_noop(self):
        plan, transport = self._plan_and_transport()
        first = ms.execute_sync_check(plan, transport)
        second = ms.execute_sync_check(plan, transport)
        self.assertTrue(first.applied)
        self.assertFalse(second.applied)
        self.assertTrue(second.already_applied)
        self.assertEqual(
            second.disposition,
            "NO_ACTION",
        )
        self.assertEqual(len(transport.writes), 1)

    def test_semantic_report_never_reaches_executor_plan(self):
        self.assertIsNone(
            ms.build_sync_check_plan(
                report(
                    disposition="NEEDS_EVIDENCE",
                    finding_classes=[
                        "SEMANTIC_PROJECTION_SUSPECTED"
                    ],
                    next_transition=None,
                ),
                control_snapshot(),
                owner_snapshot(),
            )
        )


class MaintenanceSyncCheckCliContractTests(unittest.TestCase):
    def test_cli_exposes_manual_sync_check_apply_only(self):
        from scripts import maintenance_audit as cli

        parser = cli._parser()
        dry = parser.parse_args(
            [
                "sync-check",
                "--repository",
                "o/r",
                "--control",
                "1",
            ]
        )
        self.assertEqual(dry.command, "sync-check")
        self.assertFalse(dry.apply)
        self.assertEqual(
            dry.token_env,
            "MAINTENANCE_SYNC_TOKEN",
        )

        apply = parser.parse_args(
            [
                "sync-check",
                "--repository",
                "o/r",
                "--control",
                "1",
                "--apply",
            ]
        )
        self.assertTrue(apply.apply)

    def test_maintenance_action_never_invokes_sync_check_apply(self):
        from pathlib import Path

        workflow = Path(
            ".github/workflows/maintenance-audit.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("sync-check", workflow)
        self.assertNotIn("--apply", workflow)


if __name__ == "__main__":
    unittest.main()
