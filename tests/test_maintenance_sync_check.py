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


class _P4DFakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        import json
        return json.dumps(self.payload).encode("utf-8")


def _p4d_live_snapshots(
    *,
    control_body,
    owner_work_status="DONE",
    owner_state="closed",
):
    from scripts import maintenance_audit as cli

    def opener(request, timeout=0):
        url = request.full_url
        if url.endswith(
            "/repos/kinoko34077/devflow/issues/1"
        ):
            return _P4DFakeResponse(
                {
                    "number": 1,
                    "title": "[REPO] r",
                    "state": "open",
                    "html_url": (
                        "https://github.com/kinoko34077/"
                        "devflow/issues/1"
                    ),
                    "body": (
                        "## Repository\n\n`o/r`\n\n"
                        "## Repository State\n\n`ACTIVE`\n\n"
                        "## Next Action\n\n`[WAIT] exact test`\n\n"
                        + control_body
                    ),
                    "author_association": "OWNER",
                    "user": {"id": 79015263, "login": "kinoko34077"},
                }
            )
        if url.endswith("/repos/o/r/issues/7"):
            return _P4DFakeResponse(
                {
                    "number": 7,
                    "state": owner_state,
                    "html_url": "https://github.com/o/r/issues/7",
                    "body": (
                        "## Work Status\n\n"
                        f"`{owner_work_status}`\n"
                    ),
                    "author_association": "OWNER",
                    "user": {"id": 79015263, "login": "kinoko34077"},
                }
            )
        raise AssertionError(f"unexpected read: {url}")

    transport = cli._SyncCheckGitHubTransport(
        "token",
        opener=opener,
    )
    return (
        transport.get_control(
            "o/r",
            "kinoko34077/devflow#1",
        ),
        transport.get_owner("o/r", "o/r#7"),
    )


class MaintenanceSyncCheckStructuredGateEvidenceTests(unittest.TestCase):
    def test_candidate_user_confirmation_blocks_plan(self):
        body = control_snapshot()["body"].replace(
            '"requires_user_confirmation": false',
            '"requires_user_confirmation": true',
        )
        control, owner = _p4d_live_snapshots(
            control_body=body,
        )
        self.assertTrue(control["human_gate"])
        self.assertIsNone(
            ms.build_sync_check_plan(
                report(),
                control,
                owner,
            )
        )

    def test_candidate_blocked_flag_blocks_plan(self):
        body = control_snapshot()["body"].replace(
            '"blocked": false',
            '"blocked": true',
        )
        control, owner = _p4d_live_snapshots(
            control_body=body,
        )
        self.assertTrue(control["external_wait"])
        self.assertIsNone(
            ms.build_sync_check_plan(
                report(),
                control,
                owner,
            )
        )

    def test_terminal_owner_blocked_or_wait_status_blocks_plan(self):
        for status in ("BLOCKED", "WAIT"):
            with self.subTest(status=status):
                control, owner = _p4d_live_snapshots(
                    control_body=control_snapshot()["body"],
                    owner_work_status=status,
                )
                self.assertTrue(owner["external_wait"])
                self.assertIsNone(
                    ms.build_sync_check_plan(
                        report(),
                        control,
                        owner,
                    )
                )

    def test_candidate_gate_fields_must_be_boolean(self):
        body = control_snapshot()["body"].replace(
            '"requires_user_confirmation": false',
            '"requires_user_confirmation": "false"',
        )
        with self.assertRaises(ms.SyncCheckContractError):
            _p4d_live_snapshots(control_body=body)


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
        audit_job = workflow.split("  audit:", 1)[1]
        if "  publish:" in audit_job:
            audit_job = audit_job.split("  publish:", 1)[0]
        self.assertNotIn(
            "maintenance_audit.py sync-check",
            audit_job,
        )
        self.assertNotIn("--apply", audit_job)


class MaintenanceSyncCheckLiveTransportTests(unittest.TestCase):
    def test_live_control_next_action_human_gate_blocks_recheck(self):
        import json
        from scripts import maintenance_audit as cli

        body = control_snapshot()["body"].replace(
            "before\n",
            (
                "## Repository\n\n`o/r`\n\n"
                "## Repository State\n\n`ACTIVE`\n\n"
                "## Next Action\n\n"
                "`[HUMAN_GATE] confirm`\n\n"
            ),
        )
        issue = {
            "number": 1,
            "title": "[REPO] r",
            "state": "open",
            "html_url": (
                "https://github.com/kinoko34077/"
                "devflow/issues/1"
            ),
            "author_association": "OWNER",
            "user": {"id": 79015263, "login": "kinoko34077"},
            "body": body,
        }

        class Response:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(issue).encode()

        transport = cli._SyncCheckGitHubTransport(
            "token",
            opener=lambda request, timeout=0: Response(),
        )
        snapshot = transport.get_control(
            "o/r",
            "kinoko34077/devflow#1",
        )
        self.assertTrue(snapshot["human_gate"])

    def test_write_transport_redacts_token_from_url_error(self):
        import json
        from urllib.error import URLError
        from scripts import maintenance_audit as cli

        token = "secret-write-token"
        live_body = (
            "## Repository\n\n`o/r`\n\n"
            + control_snapshot()["body"]
        )
        issue = {
            "number": 1,
            "title": "[REPO] r",
            "state": "open",
            "html_url": (
                "https://github.com/kinoko34077/"
                "devflow/issues/1"
            ),
            "author_association": "OWNER",
            "user": {"id": 79015263, "login": "kinoko34077"},
            "body": live_body,
            "updated_at": "2026-10-16T00:00:00Z",
        }

        class Response:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(issue).encode()

        def opener(request, timeout=0):
            if request.method == "GET":
                return Response()
            raise URLError("transport failed " + token)

        transport = cli._SyncCheckGitHubTransport(
            token,
            opener=opener,
        )
        with self.assertRaises(Exception) as ctx:
            transport.update_control_body(
                "o/r",
                "kinoko34077/devflow#1",
                canonical_body_sha256(live_body),
                live_body + "\nmodified\n",
            )
        self.assertNotIn(token, str(ctx.exception))



class CandidateScopedSyncCheckEndToEndTests(unittest.TestCase):
    def test_terminal_a_is_dry_run_and_withdrawn_while_manual_b_remains(self):
        """Exact candidate scope must not rewrite Active Work to find stale A."""
        from unittest.mock import patch
        from scripts import maintenance_audit as cli

        body = (
            "## Repository\n\n`o/r`\n\n"
            "## Work Status\n\n`AUDITED`\n\n"
            "## Repository State\n\n`ACTIVE`\n\n"
            "## Active Work\n\n`o/r#8` in progress\n\n"
            "## Next Action\n\nContinue B\n\n"
            + body_with_second_candidate()
        )

        class Transport:
            def __init__(self):
                self.body = body
                self.writes = []
                self.owner_bodies = {
                    "o/r#7": "## Work Status\n\n`DONE`\n",
                    "o/r#8": "## Work Status\n\n`IMPLEMENTING`\n",
                }

            def get_json(self, path):
                if path == "/repos/kinoko34077/devflow/issues/1":
                    return {
                        "number": 1, "title": "[REPO] r", "state": "open",
                        "html_url": "https://github.com/kinoko34077/devflow/issues/1",
                        "body": self.body, "author_association": "OWNER",
                        "user": {"id": 79015263, "login": "kinoko34077"},
                        "updated_at": "2026-11-13T00:00:00Z",
                    }
                for ref, issue_body in self.owner_bodies.items():
                    if path == "/repos/o/r/issues/" + ref.split("#")[1]:
                        return {
                            "number": int(ref.split("#")[1]),
                            "state": "closed" if ref == "o/r#7" else "open",
                            "html_url": "https://github.com/o/r/issues/" + ref.split("#")[1],
                            "body": issue_body, "author_association": "OWNER",
                            "user": {"id": 79015263, "login": "kinoko34077"},
                            "updated_at": "2026-11-13T00:00:00Z",
                        }
                raise AssertionError("unexpected GET: " + path)

            def get_control(self, repository, control_ref):
                self.assert_scope(repository, control_ref)
                return {
                    "repository": repository, "control_ref": control_ref,
                    "body": self.body,
                    "body_sha256": ms.canonical_body_sha256(self.body),
                    "candidate_tasks": [
                        ref for ref in ("o/r#7", "o/r#8")
                        if '"task": "' + ref + '"' in self.body
                    ],
                    "producer_active": False, "human_gate": False,
                    "reviewer_gate": False, "external_wait": False,
                    "security_gate": False,
                }

            def get_owner(self, repository, owner_ref):
                if repository != "o/r" or owner_ref not in self.owner_bodies:
                    raise AssertionError("wrong candidate")
                return {
                    "repository": repository, "owner_ref": owner_ref,
                    "body_sha256": ms.canonical_body_sha256(
                        self.owner_bodies[owner_ref]
                    ),
                    "state": "CLOSED" if owner_ref == "o/r#7" else "OPEN",
                    "terminal": owner_ref == "o/r#7",
                    "runnable": False,
                    "producer_active": owner_ref == "o/r#8",
                    "human_gate": False, "reviewer_gate": False,
                    "external_wait": False, "security_gate": False,
                }

            def update_control_body(
                self, repository, control_ref, expected_body_sha256, edited,
            ):
                self.assert_scope(repository, control_ref)
                if ms.canonical_body_sha256(self.body) != expected_body_sha256:
                    return False
                self.writes.append(edited)
                self.body = edited
                return True

            @staticmethod
            def assert_scope(repository, control_ref):
                if repository != "o/r" or control_ref != "kinoko34077/devflow#1":
                    raise AssertionError("Control scope changed")

        transport = Transport()
        outputs = []
        parser = cli._parser()
        with patch.object(cli, "_SyncCheckGitHubTransport", return_value=transport), \
                patch.object(cli, "_token_from_env", return_value="token"), \
                patch.object(cli, "_write", side_effect=lambda payload, _path: outputs.append(payload)):
            baseline = parser.parse_args([
                "sync-check", "--repository", "o/r", "--control", "1",
                "--observed-at", "2026-11-13T00:01:00Z",
            ])
            self.assertEqual(cli._sync_check(baseline), 0)
            self.assertEqual(outputs[-1]["plan"]["owner_ref"], "o/r#7")
            self.assertEqual(outputs[-1]["report"]["owner_ref"], "o/r#7")
            self.assertIsNone(outputs[-1]["result"])
            self.assertEqual(transport.writes, [])

            scoped = parser.parse_args([
                "sync-check", "--repository", "o/r", "--control", "1",
                "--candidate-owner", "o/r#7",
                "--observed-at", "2026-11-13T00:01:00Z",
            ])
            self.assertEqual(cli._sync_check(scoped), 0)
            self.assertEqual(outputs[-1]["plan"]["owner_ref"], "o/r#7")
            self.assertIsNone(outputs[-1]["result"])
            self.assertEqual(transport.writes, [])

            # No candidate flag or manual Active Work update is required.
            baseline.apply = True
            self.assertEqual(cli._sync_check(baseline), 0)
            self.assertEqual(outputs[-1]["result"]["disposition"], "AUTO_ADVANCE")
            self.assertTrue(outputs[-1]["result"]["applied"])
            self.assertEqual(len(transport.writes), 1)
            self.assertNotIn('"task": "o/r#7"', transport.body)
            self.assertIn('"task": "o/r#8"', transport.body)
            self.assertIn("## Active Work\n\n`o/r#8`", transport.body)





class SourceFirstPortfolioAuditTests(unittest.TestCase):
    def _run(self, *, candidate_count=2, close_b=False, fail_a=False):
        import argparse
        import json
        from unittest.mock import patch
        from scripts import maintenance_audit as cli
        from tools.maintenance_github import GitHubReadError

        tasks = [
            {"task": f"o/r#{number}", "blocked": False,
             "requires_user_confirmation": False}
            for number in ([7, 8] if candidate_count == 2 else [])
        ]
        candidate_block = (
            "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->\n"
            + json.dumps({
                "schema_version": 1,
                "repository": "o/r",
                "source_ref": "kinoko34077/devflow#1",
                "candidates": tasks,
            })
            + "\n<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->\n"
        ) if candidate_count else ""
        body = (
            "## Repository\n\n\x60o/r\x60\n\n"
            + "## Work Status\n\n\x60AUDITED\x60\n\n"
            + "## Repository State\n\n\x60ACTIVE\x60\n\n"
            + "## Active Work\n\n\x60o/r#8\x60 in progress\n\n"
            + "## Next Action\n\nContinue B\n\n"
            + candidate_block
        )

        class Transport:
            def __init__(self):
                self.read_paths = []
                self.control_reads = 0

            def get_json(self, path):
                self.read_paths.append(path)
                if path == "/repos/kinoko34077/devflow/issues/1":
                    return {
                        "number": 1, "title": "[REPO] r", "state": "open",
                        "html_url": "https://github.com/kinoko34077/devflow/issues/1",
                        "body": body, "author_association": "OWNER",
                        "user": {"id": 79015263, "login": "kinoko34077"},
                        "updated_at": "2026-11-14T00:00:00Z",
                    }
                if path == "/repos/o/r/issues/7":
                    if fail_a:
                        raise GitHubReadError("original A source unavailable")
                    return {
                        "number": 7, "state": "closed",
                        "html_url": "https://github.com/o/r/issues/7",
                        "body": "## Work Status\n\n\x60DONE\x60\n",
                        "author_association": "OWNER",
                        "user": {"id": 79015263, "login": "kinoko34077"},
                        "updated_at": "2026-11-14T00:00:00Z",
                    }
                if path == "/repos/o/r/issues/8":
                    return {
                        "number": 8,
                        "state": "closed" if close_b else "open",
                        "html_url": "https://github.com/o/r/issues/8",
                        "body": ("## Work Status\n\n\x60DONE\x60\n" if close_b
                                 else "## Work Status\n\n\x60IMPLEMENTING\x60\n"),
                        "author_association": "OWNER",
                        "user": {"id": 79015263, "login": "kinoko34077"},
                        "updated_at": "2026-11-14T00:00:00Z",
                    }
                raise AssertionError("unexpected read: " + path)

            def get_control(self, repository, control_ref):
                self.control_reads += 1
                if repository != "o/r" or control_ref != "kinoko34077/devflow#1":
                    raise AssertionError("Unexpected Control")
                return {"candidate_tasks": [task["task"] for task in tasks]}

        transport = Transport()
        args = argparse.Namespace(
            token_env="GITHUB_TOKEN", observed_at="2026-11-14T00:01:00Z",
            triage=False, output=None,
        )
        outputs = []
        with (
            patch.object(cli, "_SyncCheckGitHubTransport",
                         return_value=transport),
            patch.object(cli, "_token_from_env", return_value="test"),
            patch.object(cli, "discover_controls", return_value=[
                {"repository": "o/r", "control_ref": "kinoko34077/devflow#1"},
            ]),
            patch.object(cli, "_write",
                         side_effect=lambda data, _: outputs.append(data)),
        ):
            self.assertEqual(cli._portfolio(args), 0)
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0]["repository_count"], 1)
        self.assertEqual(len(outputs[0]["reports"]), 1)
        return outputs[0]["reports"][0], transport

    def test_portfolio_discovers_closed_a_without_manual_active_work_edit(self):
        report, transport = self._run()
        self.assertEqual(report["owner_ref"], "o/r#7")
        self.assertEqual(report["disposition"], "AUTO_ADVANCE")
        self.assertEqual(
            report["next_transition"], "WITHDRAW_STALE_CONTROL_CANDIDATE",
        )
        self.assertIn("/repos/o/r/issues/7", transport.read_paths)
        self.assertIn("/repos/o/r/issues/8", transport.read_paths)
        self.assertEqual(transport.control_reads, 1)
        self.assertFalse(hasattr(transport, "update_control_body"))

    def test_portfolio_preserves_unregistered_legacy_manual_read(self):
        report, transport = self._run(candidate_count=0)
        self.assertEqual(report["owner_ref"], "o/r#8")
        self.assertEqual(report["disposition"], "NO_ACTION")
        self.assertEqual(transport.control_reads, 0)
        self.assertNotIn("/repos/o/r/issues/7", transport.read_paths)

    def test_portfolio_fails_closed_if_original_a_is_unavailable(self):
        report, _ = self._run(fail_a=True)
        self.assertEqual(report["disposition"], "NEEDS_EVIDENCE")
        self.assertNotIn("next_transition", report)

    def test_portfolio_fails_closed_if_two_terminal_candidates(self):
        report, _ = self._run(close_b=True)
        self.assertEqual(report["disposition"], "NEEDS_EVIDENCE")
        self.assertNotIn("next_transition", report)


class SourceFirstRepositoryAuditTests(unittest.TestCase):
    def test_readonly_repository_agrees_with_source_first_sync_check(self):
        """The normal audit must surface A, not the manual B owner."""
        from unittest.mock import patch
        from scripts import maintenance_audit as cli
        from tools import maintenance_github as mg

        body = (
            "## Repository\n\n`o/r`\n\n"
            "## Work Status\n\n`AUDITED`\n\n"
            "## Repository State\n\n`ACTIVE`\n\n"
            "## Active Work\n\n`o/r#8` in progress\n\n"
            "## Next Action\n\nContinue B\n\n"
            + body_with_second_candidate()
        )

        class Transport:
            def __init__(self):
                self.reads = []
                self.fail_b = False
                self.closed_b = False

            def get_json(self, path):
                self.reads.append(path)
                if path == "/repos/kinoko34077/devflow/issues/1":
                    return {
                        "number": 1, "title": "[REPO] r", "state": "open",
                        "html_url": "https://github.com/kinoko34077/devflow/issues/1",
                        "body": body, "author_association": "OWNER",
                        "user": {"id": 79015263, "login": "kinoko34077"},
                        "updated_at": "2026-11-14T00:00:00Z",
                    }
                if path == "/repos/o/r/issues/7":
                    return {
                        "number": 7, "state": "closed",
                        "html_url": "https://github.com/o/r/issues/7",
                        "body": "## Work Status\n\n`DONE`\n",
                        "author_association": "OWNER",
                        "user": {"id": 79015263, "login": "kinoko34077"},
                        "updated_at": "2026-11-14T00:00:00Z",
                    }
                if path == "/repos/o/r/issues/8":
                    if self.fail_b:
                        raise mg.GitHubReadError("source B unavailable")
                    return {
                        "number": 8, "state": "closed" if self.closed_b else "open",
                        "html_url": "https://github.com/o/r/issues/8",
                        "body": ("## Work Status\n\n`DONE`\n"
                                 if self.closed_b
                                 else "## Work Status\n\n`IMPLEMENTING`\n"),
                        "author_association": "OWNER",
                        "user": {"id": 79015263, "login": "kinoko34077"},
                        "updated_at": "2026-11-14T00:00:00Z",
                    }
                raise AssertionError("unexpected GET " + path)

            def get_control(self, repository, control_ref):
                if repository != "o/r" or control_ref != "kinoko34077/devflow#1":
                    raise AssertionError("unexpected Control scope")
                return {"candidate_tasks": ["o/r#7", "o/r#8"]}

        parser = cli._parser()
        args = parser.parse_args([
            "repository", "--repository", "o/r", "--control", "1",
            "--observed-at", "2026-11-14T00:01:00Z",
        ])
        transport = Transport()
        results = []
        with patch.object(cli, "_SyncCheckGitHubTransport", return_value=transport), \
                patch.object(cli, "_token_from_env", return_value="token"), \
                patch.object(cli, "_write", side_effect=lambda payload, output: results.append(payload)):
            self.assertEqual(cli._repository(args), 0)
            self.assertEqual(results[-1]["owner_ref"], "o/r#7")
            self.assertEqual(results[-1]["disposition"], "AUTO_ADVANCE")
            self.assertEqual(
                results[-1]["next_transition"],
                "WITHDRAW_STALE_CONTROL_CANDIDATE",
            )
            self.assertIn("/repos/o/r/issues/7", transport.reads)
            self.assertIn("/repos/o/r/issues/8", transport.reads)
            # This is strictly read-only, even for an actionable report.
            self.assertTrue(all(path.startswith("/repos/") for path in transport.reads))

            # Optional parity compares the unchanged legacy Active Work source.
            args.m3_read_parity = True
            with patch.object(
                cli.devflow_mcp_core, "DevflowService",
                side_effect=RuntimeError("optional read unavailable"),
            ):
                self.assertEqual(cli._repository(args), 0)
            self.assertEqual(results[-1]["owner_ref"], "o/r#8")
            self.assertEqual(results[-1]["disposition"], "NO_ACTION")
            self.assertEqual(
                results[-1]["m3_read_parity"]["use_level"], "READ_ONLY_DIAGNOSTIC",
            )

            args.m3_read_parity = False
            transport.fail_b = True
            self.assertEqual(cli._repository(args), 0)
            self.assertEqual(results[-1]["disposition"], "NEEDS_EVIDENCE")
            self.assertNotIn("next_transition", results[-1])

            transport.fail_b = False
            transport.closed_b = True
            self.assertEqual(cli._repository(args), 0)
            self.assertEqual(results[-1]["disposition"], "NEEDS_EVIDENCE")
            self.assertNotIn("next_transition", results[-1])


class SourceFirstSyncCheckSelectionTests(unittest.TestCase):
    def test_ambiguous_terminal_set_fails_closed_without_manual_owner_authority(self):
        from unittest.mock import patch
        from scripts import maintenance_audit as cli

        class Transport:
            def get_control(self, repository, control_ref):
                return {"candidate_tasks": ["o/r#7", "o/r#9"]}

        reads = []
        def collect(_transport, _repository, _control_ref, _when,
                    *, candidate_owner_ref=None):
            reads.append(candidate_owner_ref)
            return {
                "source_status": "OK",
                "owner": {
                    "ref": candidate_owner_ref or "o/r#9",
                    "state": "CLOSED", "runnable": False,
                },
            }

        with patch.object(cli, "collect_repository", side_effect=collect), \
                patch.object(
                    cli, "_classify_observation",
                    return_value={
                        "disposition": "AUTO_ADVANCE",
                        "next_transition": "WITHDRAW_STALE_CONTROL_CANDIDATE",
                    },
                ):
            observed = cli._sync_check_source_first_observation(
                Transport(), "o/r", "kinoko34077/devflow#1",
                "2026-11-14T00:00:00Z",
            )
        self.assertEqual(observed["source_status"], "UNAVAILABLE")
        self.assertEqual(observed["source_error"], "MULTIPLE_TERMINAL_CANDIDATES")
        self.assertEqual(reads, [None, "o/r#7", "o/r#9"])

    def test_unavailable_candidate_fails_closed_not_to_manual_owner(self):
        from unittest.mock import patch
        from scripts import maintenance_audit as cli

        class Transport:
            def get_control(self, repository, control_ref):
                return {"candidate_tasks": ["o/r#7", "o/r#8"]}

        def collect(_transport, _repository, _control_ref, _when,
                    *, candidate_owner_ref=None):
            if candidate_owner_ref == "o/r#8":
                return {"source_status": "UNAVAILABLE", "owner": {"ref": "o/r#8"}}
            return {"source_status": "OK", "owner": {"ref": candidate_owner_ref}}

        with patch.object(cli, "collect_repository", side_effect=collect), \
                patch.object(
                    cli, "_classify_observation",
                    return_value={
                        "disposition": "AUTO_ADVANCE",
                        "next_transition": "WITHDRAW_STALE_CONTROL_CANDIDATE",
                    },
                ):
            observed = cli._sync_check_source_first_observation(
                Transport(), "o/r", "kinoko34077/devflow#1",
                "2026-11-14T00:00:00Z",
            )
        self.assertEqual(observed["source_status"], "UNAVAILABLE")

    def test_open_done_does_not_count_as_an_executable_terminal(self):
        from unittest.mock import patch
        from scripts import maintenance_audit as cli

        class Transport:
            def get_control(self, repository, control_ref):
                return {"candidate_tasks": ["o/r#7", "o/r#8"]}

        def collect(_transport, _repository, _control_ref, _when,
                    *, candidate_owner_ref=None):
            return {
                "source_status": "OK",
                "owner": {
                    "ref": candidate_owner_ref or "o/r#8",
                    "state": "OPEN" if candidate_owner_ref == "o/r#7" else "CLOSED",
                    "runnable": False,
                },
            }

        with patch.object(cli, "collect_repository", side_effect=collect), \
                patch.object(cli, "_classify_observation", return_value={
                    "disposition": "AUTO_ADVANCE",
                    "next_transition": "WITHDRAW_STALE_CONTROL_CANDIDATE",
                }):
            actual = cli._sync_check_source_first_observation(
                Transport(), "o/r", "kinoko34077/devflow#1",
                "2026-11-14T00:00:00Z",
            )
        self.assertEqual(actual["owner"]["ref"], "o/r#8")

    def test_oversized_candidate_set_and_invalid_ref_are_not_scanned(self):
        from unittest.mock import patch
        from scripts import maintenance_audit as cli

        class Transport:
            def __init__(self, tasks):
                self.tasks = tasks

            def get_control(self, repository, control_ref):
                return {"candidate_tasks": self.tasks}

        for tasks in (
            [f"o/r#{i}" for i in range(1, 18)],
            ["o/r#7", "other/repo#8"],
            ["o/r#7", "o/r#7"],
        ):
            with self.subTest(tasks=tasks), patch.object(
                cli, "collect_repository", return_value={
                    "source_status": "OK", "owner": {"ref": "o/r#8"},
                },
            ) as reader:
                observed = cli._sync_check_source_first_observation(
                    Transport(tasks), "o/r", "kinoko34077/devflow#1",
                    "2026-11-14T00:00:00Z",
                )
                self.assertEqual(observed["source_status"], "UNAVAILABLE")
                reader.assert_called_once()

    def test_no_admitted_candidates_retains_existing_fallback(self):
        from unittest.mock import patch
        from scripts import maintenance_audit as cli

        class Transport:
            def get_control(self, repository, control_ref):
                return {"candidate_tasks": []}

        fallback = {"source_status": "OK", "owner": {"ref": "o/r#8"}}
        with patch.object(cli, "collect_repository", return_value=fallback) as reader:
            actual = cli._sync_check_source_first_observation(
                Transport(), "o/r", "kinoko34077/devflow#1",
                "2026-11-14T00:00:00Z",
            )
        self.assertIs(actual, fallback)
        reader.assert_called_once()


class CandidateScopedSyncCheckCliTests(unittest.TestCase):
    def test_exact_candidate_requires_explicit_flag_and_apply_opt_in(self):
        from scripts import maintenance_audit as cli

        parser = cli._parser()
        default = parser.parse_args(
            ["sync-check", "--repository", "o/r", "--control", "1"]
        )
        self.assertIsNone(default.candidate_owner)
        self.assertFalse(default.apply)
        scoped = parser.parse_args([
            "sync-check", "--repository", "o/r", "--control", "1",
            "--candidate-owner", "o/r#7",
        ])
        self.assertEqual(scoped.candidate_owner, "o/r#7")
        self.assertFalse(scoped.apply)
        self.assertTrue(parser.parse_args([
            "sync-check", "--repository", "o/r", "--control", "1",
            "--candidate-owner", "o/r#7", "--apply",
        ]).apply)


if __name__ == "__main__":
    unittest.main()
