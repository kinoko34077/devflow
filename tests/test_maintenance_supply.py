import unittest

try:
    from tools import maintenance_supply as ms
except ImportError:
    ms = None

try:
    from tools.maintenance_triage import TriageDecision
except ImportError:
    TriageDecision = None


BODY_SHA = "sha256:" + "a" * 64
OTHER_SHA = "sha256:" + "b" * 64


def decision(**overrides):
    value = {
        "action": "PUBLISH_EXISTING_OWNER",
        "report_id": "sha256:" + "c" * 64,
        "disposition": "AUTO_ADVANCE",
        "work_class": "sync-check",
        "owner_ref": "o/r#7",
        "reason_codes": ("EXACT_EXISTING_OWNER",),
    }
    value.update(overrides)
    if TriageDecision is None:
        return value
    return TriageDecision(**value)


def owner(**overrides):
    value = {
        "task_ref": "o/r#7",
        "repository": "o/r",
        "body_sha256": BODY_SHA,
        "state": "OPEN",
        "work_status": "READY_FOR_IMPLEMENTATION",
        "scope_ready": True,
        "blocked": False,
        "requires_user_confirmation": False,
        "conflict_keys": ("component:o/r:maintenance",),
        "trusted": True,
        "is_pull_request": False,
        "entry_ref": "https://github.com/o/r/issues/7",
        "human_gate": False,
        "reviewer_gate": False,
        "external_wait": False,
        "security_gate": False,
    }
    value.update(overrides)
    return value


def control(**overrides):
    value = {
        "repository": "o/r",
        "control_ref": "kinoko34077/devflow#1",
        "repository_state": "ACTIVE",
        "trusted": True,
        "human_gate": False,
        "external_wait": False,
        "observed_at": "2026-10-01T00:00:00Z",
        "fresh_until": "2026-10-01T01:00:00Z",
        "publisher_execution_attempt_id": "attempt-p5",
    }
    value.update(overrides)
    return value


class MaintenanceSupplyTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            ms,
            "maintenance_supply module must exist",
        )

    def test_existing_exact_owner_builds_sync_check_supply(self):
        supply = ms.build_existing_owner_candidate(
            decision(),
            owner(),
            control(),
        )
        self.assertIsNotNone(supply)
        self.assertEqual(
            supply["admission"]["task"],
            "o/r#7",
        )
        self.assertEqual(
            supply["admission"]["task_body_sha256"],
            BODY_SHA,
        )
        self.assertEqual(
            supply["admission"]["roles"],
            [{"role": "implementer", "next_action_tag": "IMPLEMENT"}],
        )
        self.assertEqual(
            supply["portfolio"]["work_class"],
            "sync-check",
        )
        self.assertEqual(
            supply["portfolio"]["task_body_sha256"],
            BODY_SHA,
        )
        self.assertEqual(
            supply["publisher_execution_attempt_id"],
            "attempt-p5",
        )
        self.assertTrue(
            supply["candidate_fingerprint"].startswith("sha256:")
        )

    def test_candidate_fingerprint_matches_execution_coordinator_contract(self):
        import hashlib
        import json

        supply = ms.build_existing_owner_candidate(
            decision(),
            owner(),
            control(),
        )
        admission = supply["admission"]
        role = admission["roles"][0]["role"]
        expected_payload = {
            "task": admission["task"],
            "role": role,
            "entry_ref": admission["entry_ref"],
            "conflict_keys": admission["conflict_keys"],
            "scope_ready": admission["scope_ready"],
            "blocked": admission["blocked"],
            "requires_user_confirmation": admission[
                "requires_user_confirmation"
            ],
        }
        encoded = json.dumps(
            expected_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        expected = "sha256:" + hashlib.sha256(encoded).hexdigest()
        self.assertEqual(
            supply["candidate_fingerprint"],
            expected,
        )
        self.assertEqual(
            supply["portfolio"]["candidate_fingerprint"],
            expected,
        )

    def test_no_existing_owner_never_creates_supply(self):
        self.assertIsNone(
            ms.build_existing_owner_candidate(
                decision(owner_ref=None),
                owner(),
                control(),
            )
        )

    def test_owner_identity_digest_and_ready_state_are_strict(self):
        cases = (
            owner(task_ref="o/r#8"),
            owner(body_sha256=OTHER_SHA),
            owner(state="CLOSED"),
            owner(work_status="IMPLEMENTING"),
            owner(scope_ready=False),
            owner(blocked=True),
            owner(trusted=False),
            owner(is_pull_request=True),
        )
        for snapshot in cases:
            with self.subTest(snapshot=snapshot):
                self.assertIsNone(
                    ms.build_existing_owner_candidate(
                        decision(),
                        snapshot,
                        control(
                            expected_owner_body_sha256=BODY_SHA,
                        ),
                    )
                )

    def test_any_stronger_gate_suppresses_supply(self):
        for field in (
            "human_gate",
            "reviewer_gate",
            "external_wait",
            "security_gate",
        ):
            with self.subTest(field=field):
                self.assertIsNone(
                    ms.build_existing_owner_candidate(
                        decision(),
                        owner(**{field: True}),
                        control(),
                    )
                )

    def test_same_evidence_has_stable_identity(self):
        first = ms.build_existing_owner_candidate(
            decision(),
            owner(),
            control(observed_at="2026-10-01T00:00:00Z"),
        )
        second = ms.build_existing_owner_candidate(
            decision(),
            owner(),
            control(observed_at="2026-10-01T00:10:00Z"),
        )
        self.assertEqual(
            first["candidate_fingerprint"],
            second["candidate_fingerprint"],
        )
        reconciled = ms.reconcile_existing_owner_supply(
            [first],
            first,
        )
        self.assertEqual(reconciled["active"], [first])
        self.assertEqual(reconciled["superseded_ids"], [])

    def test_owner_readiness_or_freshness_change_withdraws_old_supply(self):
        existing = ms.build_existing_owner_candidate(
            decision(),
            owner(),
            control(),
        )
        desired = ms.build_existing_owner_candidate(
            decision(),
            owner(work_status="IMPLEMENTING"),
            control(),
        )
        self.assertIsNone(desired)
        reconciled = ms.reconcile_existing_owner_supply(
            [existing],
            desired,
            task_ref="o/r#7",
        )
        self.assertEqual(reconciled["active"], [])
        self.assertEqual(
            reconciled["superseded_ids"],
            [existing["publication_id"]],
        )

    def test_publisher_attempt_cannot_consume_its_own_change(self):
        supply = ms.build_existing_owner_candidate(
            decision(),
            owner(),
            control(
                publisher_execution_attempt_id="attempt-p5",
            ),
        )
        self.assertTrue(
            ms.published_by_attempt(
                supply,
                "attempt-p5",
            )
        )
        self.assertFalse(
            ms.published_by_attempt(
                supply,
                "later-attempt",
            )
        )


def empty_control_body():
    return (
        "before\n"
        "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->\n"
        "{\n"
        '  "schema_version": 1,\n'
        '  "source_ref": "kinoko34077/devflow#1",\n'
        '  "repository": "o/r",\n'
        '  "candidates": []\n'
        "}\n"
        "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->\n"
        "middle\n"
        "<!-- DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1_BEGIN -->\n"
        "{\n"
        '  "schema_version": "execution-portfolio-metadata.v1",\n'
        '  "source_ref": "kinoko34077/devflow#1",\n'
        '  "repository": "o/r",\n'
        '  "entries": []\n'
        "}\n"
        "<!-- DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1_END -->\n"
        "after\n"
    )


def existing_candidate_control_body():
    supply = ms.build_existing_owner_candidate(
        decision(),
        owner(),
        control(),
    )
    admission = supply["admission"]
    payload = (
        "{\n"
        '  "schema_version": 1,\n'
        '  "source_ref": "kinoko34077/devflow#1",\n'
        '  "repository": "o/r",\n'
        '  "candidates": [\n'
        + __import__("json").dumps(
            admission,
            indent=4,
            ensure_ascii=False,
        ).replace("\n", "\n    ")
        + "\n  ]\n"
        "}\n"
    )
    return empty_control_body().replace(
        "{\n"
        '  "schema_version": 1,\n'
        '  "source_ref": "kinoko34077/devflow#1",\n'
        '  "repository": "o/r",\n'
        '  "candidates": []\n'
        "}\n",
        payload,
        1,
    )


class MaintenanceSupplyConsumerParityTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ms)

    def test_candidate_fingerprint_matches_execution_coordinator_contract(self):
        import hashlib
        import json

        supply = ms.build_existing_owner_candidate(
            decision(),
            owner(),
            control(),
        )
        payload = {
            "task": "o/r#7",
            "role": "implementer",
            "entry_ref": "https://github.com/o/r/issues/7",
            "conflict_keys": ["component:o/r:maintenance"],
            "scope_ready": True,
            "blocked": False,
            "requires_user_confirmation": False,
        }
        expected = "sha256:" + hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(
            supply["candidate_fingerprint"],
            expected,
        )
        self.assertEqual(
            supply["portfolio"]["candidate_fingerprint"],
            expected,
        )

    def test_invalid_protocol_conflict_key_is_not_publishable(self):
        self.assertIsNone(
            ms.build_existing_owner_candidate(
                decision(),
                owner(conflict_keys=("free-form key",)),
                control(),
            )
        )


class MaintenanceSupplyProjectionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ms)

    def test_projection_editor_adds_portfolio_metadata_without_manufacturing_candidate(self):
        supply = ms.build_existing_owner_candidate(
            decision(),
            owner(),
            control(),
        )
        first, changed = ms.reconcile_control_projection_body(
            existing_candidate_control_body(),
            supply,
            task_ref="o/r#7",
        )
        self.assertTrue(changed)
        self.assertIn('"task": "o/r#7"', first)
        self.assertIn('"work_class": "sync-check"', first)
        self.assertTrue(first.startswith("before\n"))
        self.assertTrue(first.endswith("after\n"))

        second, changed_again = ms.reconcile_control_projection_body(
            first,
            supply,
            task_ref="o/r#7",
        )
        self.assertFalse(changed_again)
        self.assertEqual(second, first)

    def test_projection_editor_refuses_to_create_missing_admission(self):
        supply = ms.build_existing_owner_candidate(
            decision(),
            owner(),
            control(),
        )
        with self.assertRaises(ms.MaintenanceSupplyError):
            ms.reconcile_control_projection_body(
                empty_control_body(),
                supply,
                task_ref="o/r#7",
            )

    def test_existing_admission_is_exact_machine_source(self):
        admission = ms.extract_existing_admission(
            existing_candidate_control_body(),
            repository="o/r",
            control_ref="kinoko34077/devflow#1",
            task_ref="o/r#7",
        )
        self.assertEqual(admission["task"], "o/r#7")
        self.assertEqual(
            admission["task_body_sha256"],
            BODY_SHA,
        )
        self.assertFalse(
            admission["requires_user_confirmation"],
        )
        self.assertFalse(admission["blocked"])

    def test_projection_editor_withdraws_both_blocks(self):
        supply = ms.build_existing_owner_candidate(
            decision(),
            owner(),
            control(),
        )
        published, _ = ms.reconcile_control_projection_body(
            existing_candidate_control_body(),
            supply,
            task_ref="o/r#7",
        )
        withdrawn, changed = ms.reconcile_control_projection_body(
            published,
            None,
            task_ref="o/r#7",
        )
        self.assertTrue(changed)
        self.assertNotIn('"task": "o/r#7"', withdrawn)
        self.assertIn('"candidates": []', withdrawn)
        self.assertIn('"entries": []', withdrawn)

    def test_cli_and_workflow_expose_manual_publish_only(self):
        from pathlib import Path
        from scripts import maintenance_audit as cli

        args = cli._parser().parse_args(
            [
                "publish-supply",
                "--repository",
                "o/r",
                "--control",
                "1",
                "--owner",
                "o/r#7",
                "--work-class",
                "sync-check",
                "--attempt-id",
                "attempt-p5",
                "--apply",
            ]
        )
        self.assertEqual(args.command, "publish-supply")
        self.assertTrue(args.apply)
        self.assertEqual(
            args.token_env,
            "MAINTENANCE_SUPPLY_TOKEN",
        )

        workflow = Path(
            ".github/workflows/maintenance-audit.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("- publish", workflow)
        self.assertIn("  publish:", workflow)
        self.assertIn("inputs.mode == 'publish'", workflow)
        publish_job = workflow.split("  publish:", 1)[1]
        self.assertIn("issues: write", publish_job)
        audit_job = workflow.split("  audit:", 1)[1].split(
            "  publish:", 1
        )[0]
        self.assertNotIn("issues: write", audit_job)
        self.assertNotIn("publish-supply", audit_job)


class MaintenanceSupplyPublisherProvenanceTests(unittest.TestCase):
    def _admission(self, **overrides):
        value = {
            "task": "o/r#7",
            "task_body_sha256": BODY_SHA,
            "task_work_status": "READY_FOR_IMPLEMENTATION",
            "entry_ref": "https://github.com/o/r/issues/7",
            "scope_ready": True,
            "blocked": False,
            "requires_user_confirmation": False,
            "conflict_keys": [],
            "roles": [
                {
                    "role": "implementer",
                    "next_action_tag": "IMPLEMENT",
                }
            ],
        }
        value.update(overrides)
        return value

    def test_owner_supply_snapshot_rejects_empty_owning_body(self):
        from scripts import maintenance_audit as cli

        class Transport:
            def get_issue(self, repository, number):
                self.assertEqual((repository, number), ("o/r", 7))
                return {
                    "state": "open",
                    "body": "",
                    "html_url": "https://github.com/o/r/issues/7",
                    "author_association": "OWNER",
                }

            def assertEqual(self, left, right):
                if left != right:
                    raise AssertionError((left, right))

        with self.assertRaises(cli.MaintenanceSupplyError):
            cli._owner_supply_snapshot(
                Transport(),
                "o/r",
                "o/r#7",
                self._admission(
                    task_body_sha256=cli.canonical_body_sha256("")
                ),
            )

    def test_owner_supply_snapshot_requires_valid_work_order_provenance(self):
        from scripts import maintenance_audit as cli

        admission = self._admission(
            work_order_ref="kinoko34077/devflow#9",
        )

        class Transport:
            def __init__(self, work_order):
                self.work_order = work_order

            def get_issue(self, repository, number):
                if (repository, number) == ("o/r", 7):
                    return {
                        "state": "open",
                        "body": "owner body",
                        "html_url": "https://github.com/o/r/issues/7",
                        "author_association": "OWNER",
                    }
                if (repository, number) == ("kinoko34077/devflow", 9):
                    return dict(self.work_order)
                raise AssertionError((repository, number))

        bad_cases = (
            {
                "state": "closed",
                "title": "[WORK ORDER] test",
                "body": "x",
                "author_association": "OWNER",
            },
            {
                "state": "open",
                "title": "[WORK ORDER] test",
                "body": "x",
                "author_association": "NONE",
            },
            {
                "state": "open",
                "title": "not a work order",
                "body": "x",
                "author_association": "OWNER",
            },
            {
                "state": "open",
                "title": "[WORK ORDER] test",
                "body": "x",
                "author_association": "OWNER",
                "pull_request": {},
            },
        )
        for work_order in bad_cases:
            with self.subTest(work_order=work_order):
                with self.assertRaises(cli.MaintenanceSupplyError):
                    cli._owner_supply_snapshot(
                        Transport(work_order),
                        "o/r",
                        "o/r#7",
                        admission,
                    )

        valid = {
            "state": "open",
            "title": "[WORK ORDER] test",
            "body": "x",
            "author_association": "OWNER",
        }
        snapshot = cli._owner_supply_snapshot(
            Transport(valid),
            "o/r",
            "o/r#7",
            admission,
        )
        self.assertEqual(
            snapshot["work_order_ref"],
            "kinoko34077/devflow#9",
        )


class MaintenanceSupplyApplyPathTests(unittest.TestCase):
    def test_write_transport_posts_compact_209_transition(self):
        import json
        from scripts import maintenance_audit as cli

        seen = []

        class Response:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"id": 1}).encode("utf-8")

        def opener(request, timeout=0):
            seen.append(request)
            return Response()

        transport = cli._SyncCheckGitHubTransport(
            "secret-token",
            opener=opener,
        )
        self.assertTrue(
            transport.post_supply_transition("compact transition")
        )
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].method, "POST")
        self.assertTrue(
            seen[0].full_url.endswith(
                "/repos/kinoko34077/devflow/issues/209/comments"
            )
        )
        self.assertIn(
            b"compact transition",
            seen[0].data,
        )

    def _run_publish(self, *, apply):
        import argparse
        import os
        from unittest.mock import patch
        from scripts import maintenance_audit as cli

        class FakeTransport:
            instances = []

            def __init__(self, token):
                self.token = token
                self.comments = []
                self.writes = []
                owner_body = "durable scope"
                digest = cli.canonical_body_sha256(owner_body)
                candidate_body = existing_candidate_control_body().replace(
                    BODY_SHA,
                    digest,
                )
                self.body = (
                    "## Repository\n\n`o/r`\n\n"
                    "## Repository State\n\n`ACTIVE`\n\n"
                    "## Next Action\n\n`[IMPLEMENT]`\n\n"
                    + candidate_body
                )
                self.owner_body = owner_body
                type(self).instances.append(self)

            def get_issue(self, repository, number):
                if (repository, number) == (
                    "kinoko34077/devflow",
                    1,
                ):
                    return {
                        "number": 1,
                        "state": "open",
                        "title": "[REPO] r",
                        "body": self.body,
                        "author_association": "OWNER",
                    }
                if (repository, number) == ("o/r", 7):
                    return {
                        "number": 7,
                        "state": "open",
                        "title": "owner",
                        "body": self.owner_body,
                        "html_url": "https://github.com/o/r/issues/7",
                        "author_association": "OWNER",
                    }
                raise AssertionError((repository, number))

            def update_control_body(
                self,
                repository,
                control_ref,
                expected_body_sha256,
                body,
            ):
                self.writes.append(body)
                self.body = body
                return True

            def get_control(self, repository, control_ref):
                return {
                    "repository": repository,
                    "control_ref": control_ref,
                    "body": self.body,
                }

            def post_supply_transition(self, body):
                self.comments.append(body)
                return True

        args = argparse.Namespace(
            repository="o/r",
            control=1,
            owner="o/r#7",
            work_class="sync-check",
            attempt_id="attempt-p5",
            token_env="MAINTENANCE_SUPPLY_TOKEN",
            observed_at="2026-10-01T00:00:00Z",
            output=None,
            apply=apply,
        )
        output = []
        with patch.dict(
            os.environ,
            {"MAINTENANCE_SUPPLY_TOKEN": "token"},
            clear=False,
        ), patch.object(
            cli,
            "_SyncCheckGitHubTransport",
            FakeTransport,
        ), patch.object(
            cli,
            "_write",
            lambda value, _output: output.append(value),
        ):
            result = cli._publish_supply(args)

        return (
            result,
            FakeTransport.instances[-1],
            output[-1],
        )

    def test_publish_supply_dry_run_never_posts_transition(self):
        result, transport, payload = self._run_publish(
            apply=False,
        )
        self.assertEqual(result, 0)
        self.assertTrue(payload["changed"])
        self.assertFalse(payload["applied"])
        self.assertEqual(transport.writes, [])
        self.assertEqual(transport.comments, [])

    def test_material_apply_posts_one_transition_after_control_confirm(self):
        result, transport, payload = self._run_publish(
            apply=True,
        )
        self.assertEqual(result, 0)
        self.assertTrue(payload["applied"])
        self.assertEqual(len(transport.writes), 1)
        self.assertEqual(len(transport.comments), 1)
        self.assertIn(
            "Stage-2 maintenance supply transition",
            transport.comments[0],
        )


    def test_reporting_failure_preserves_applied_partial_success(self):
        import argparse
        import os
        from unittest.mock import patch
        from scripts import maintenance_audit as cli

        class FakeTransport:
            instances = []

            def __init__(self, token):
                self.token = token
                self.owner_body = "durable scope"
                digest = cli.canonical_body_sha256(
                    self.owner_body
                )
                self.body = (
                    "## Repository\n\n`o/r`\n\n"
                    "## Repository State\n\n`ACTIVE`\n\n"
                    "## Next Action\n\n`[IMPLEMENT]`\n\n"
                    + existing_candidate_control_body().replace(
                        BODY_SHA,
                        digest,
                    )
                )
                self.writes = []
                self.posts = 0
                type(self).instances.append(self)

            def get_issue(self, repository, number):
                if (repository, number) == (
                    "kinoko34077/devflow",
                    1,
                ):
                    return {
                        "number": 1,
                        "state": "open",
                        "title": "[REPO] r",
                        "body": self.body,
                        "author_association": "OWNER",
                    }
                if (repository, number) == ("o/r", 7):
                    return {
                        "number": 7,
                        "state": "open",
                        "title": "owner",
                        "body": self.owner_body,
                        "html_url": "https://github.com/o/r/issues/7",
                        "author_association": "OWNER",
                    }
                raise AssertionError((repository, number))

            def update_control_body(
                self,
                repository,
                control_ref,
                expected_body_sha256,
                body,
            ):
                self.writes.append(body)
                self.body = body
                return True

            def get_control(self, repository, control_ref):
                return {
                    "repository": repository,
                    "control_ref": control_ref,
                    "body": self.body,
                }

            def post_supply_transition(self, body):
                self.posts += 1
                return False

        args = argparse.Namespace(
            repository="o/r",
            control=1,
            owner="o/r#7",
            work_class="sync-check",
            attempt_id="attempt-partial",
            token_env="MAINTENANCE_SUPPLY_TOKEN",
            observed_at="2026-10-01T00:00:00Z",
            output=None,
            apply=True,
        )
        output = []
        with patch.dict(
            os.environ,
            {"MAINTENANCE_SUPPLY_TOKEN": "token"},
            clear=False,
        ), patch.object(
            cli,
            "_SyncCheckGitHubTransport",
            FakeTransport,
        ), patch.object(
            cli,
            "_write",
            lambda value, _output: output.append(value),
        ):
            result = cli._publish_supply(args)

        transport = FakeTransport.instances[-1]
        payload = output[-1]
        self.assertNotEqual(result, 0)
        self.assertEqual(len(transport.writes), 1)
        self.assertEqual(transport.posts, 1)
        self.assertTrue(payload["applied"])
        self.assertFalse(payload["transition_recorded"])
        self.assertIn("reporting_error", payload)



class MaintenanceSupplyApplyPathTests(unittest.TestCase):
    def test_supply_transport_posts_compact_transition_to_209(self):
        import json
        from scripts import maintenance_audit as cli

        calls = []

        class Response:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"id": 1}'

        def opener(request, timeout=0):
            calls.append(request)
            return Response()

        transport = cli._SyncCheckGitHubTransport(
            "secret-token",
            opener=opener,
        )
        self.assertTrue(
            transport.post_supply_transition("compact transition")
        )
        self.assertEqual(len(calls), 1)
        request = calls[0]
        self.assertEqual(request.method, "POST")
        self.assertTrue(
            request.full_url.endswith(
                "/repos/kinoko34077/devflow/issues/209/comments"
            )
        )
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"body": "compact transition"},
        )

    def test_publish_supply_dry_run_never_posts_transition(self):
        import os
        import tempfile
        from unittest.mock import patch
        from scripts import maintenance_audit as cli

        class FakeTransport:
            instances = []

            def __init__(self, token):
                self.token = token
                self.posts = 0
                self.owner_body = "owner body"
                digest = cli.canonical_body_sha256(
                    self.owner_body
                )
                self.control_body = (
                    "## Repository\n\n`o/r`\n\n"
                    "## Repository State\n\n`ACTIVE`\n\n"
                    "## Next Action\n\n`[IMPLEMENT]`\n\n"
                    + existing_candidate_control_body().replace(
                        BODY_SHA,
                        digest,
                    )
                )
                self.__class__.instances.append(self)

            def get_issue(self, repository, number):
                if (repository, number) == (
                    "kinoko34077/devflow",
                    1,
                ):
                    return {
                        "state": "open",
                        "title": "[REPO] r",
                        "body": self.control_body,
                        "html_url": (
                            "https://github.com/kinoko34077/"
                            "devflow/issues/1"
                        ),
                        "author_association": "OWNER",
                    }
                if (repository, number) == ("o/r", 7):
                    return {
                        "state": "open",
                        "title": "owner",
                        "body": self.owner_body,
                        "html_url": "https://github.com/o/r/issues/7",
                        "author_association": "OWNER",
                    }
                raise AssertionError((repository, number))

            def post_supply_transition(self, body):
                self.posts += 1
                raise AssertionError("dry-run must not post")

        with tempfile.TemporaryDirectory() as directory:
            output = directory + "/result.json"
            args = cli._parser().parse_args(
                [
                    "publish-supply",
                    "--repository",
                    "o/r",
                    "--control",
                    "1",
                    "--owner",
                    "o/r#7",
                    "--work-class",
                    "sync-check",
                    "--attempt-id",
                    "attempt-p5",
                    "--observed-at",
                    "2026-10-01T00:00:00Z",
                    "--output",
                    output,
                ]
            )
            with patch.object(
                cli,
                "_SyncCheckGitHubTransport",
                FakeTransport,
            ), patch.dict(
                os.environ,
                {"MAINTENANCE_SUPPLY_TOKEN": "secret-token"},
            ):
                self.assertEqual(cli._publish_supply(args), 0)
            self.assertEqual(
                FakeTransport.instances[-1].posts,
                0,
            )


class MaintenanceSupplyTransitionTransportTests(unittest.TestCase):
    def test_sync_transport_posts_supply_transition_only_to_209_comments(self):
        import json
        from scripts import maintenance_audit as cli

        seen = []

        class Response:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(
                    {"body": "transition body"}
                ).encode("utf-8")

        def opener(request, timeout=0):
            seen.append(request)
            return Response()

        transport = cli._SyncCheckGitHubTransport(
            "secret-token",
            opener=opener,
        )
        self.assertTrue(
            transport.post_supply_transition(
                "transition body"
            )
        )
        self.assertEqual(len(seen), 1)
        request = seen[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            request.full_url,
            "https://api.github.com/repos/"
            "kinoko34077/devflow/issues/209/comments",
        )
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            payload,
            {"body": "transition body"},
        )
        self.assertEqual(
            request.get_header("Authorization"),
            "Bearer secret-token",
        )

    def test_publish_supply_dry_run_posts_no_transition(self):
        import argparse
        import json
        from scripts import maintenance_audit as cli

        owner_body = "durable owner body\n"
        owner_digest = cli.canonical_body_sha256(owner_body)
        admission = {
            "task": "o/r#7",
            "task_body_sha256": owner_digest,
            "task_work_status": "READY_FOR_IMPLEMENTATION",
            "entry_ref": "https://github.com/o/r/issues/7",
            "scope_ready": True,
            "blocked": False,
            "requires_user_confirmation": False,
            "conflict_keys": [],
            "roles": [
                {
                    "role": "implementer",
                    "next_action_tag": "IMPLEMENT",
                }
            ],
        }
        candidate = {
            "schema_version": 1,
            "source_ref": "kinoko34077/devflow#1",
            "repository": "o/r",
            "candidates": [admission],
        }
        portfolio = {
            "schema_version": "execution-portfolio-metadata.v1",
            "source_ref": "kinoko34077/devflow#1",
            "repository": "o/r",
            "entries": [],
        }
        control_body = (
            "## Repository\n\n`o/r`\n\n"
            "## Repository State\n\n`ACTIVE`\n\n"
            "## Next Action\n\n`[IMPLEMENT] continue`\n\n"
            "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->\n"
            + json.dumps(candidate)
            + "\n<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->\n"
            "<!-- DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1_BEGIN -->\n"
            + json.dumps(portfolio)
            + "\n<!-- DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1_END -->\n"
        )

        class FakeTransport:
            transition_calls = 0
            update_calls = 0

            def __init__(self, token):
                self.token = token

            def get_issue(self, repository, number):
                if (repository, number) == (
                    "kinoko34077/devflow",
                    1,
                ):
                    return {
                        "body": control_body,
                        "author_association": "OWNER",
                    }
                if (repository, number) == ("o/r", 7):
                    return {
                        "state": "open",
                        "body": owner_body,
                        "html_url": "https://github.com/o/r/issues/7",
                        "author_association": "OWNER",
                    }
                raise AssertionError((repository, number))

            def update_control_body(self, *args, **kwargs):
                type(self).update_calls += 1
                raise AssertionError("dry-run must not write")

            def post_supply_transition(self, body):
                type(self).transition_calls += 1
                raise AssertionError("dry-run must not comment")

        original = cli._SyncCheckGitHubTransport
        cli._SyncCheckGitHubTransport = FakeTransport
        old_token = __import__("os").environ.get(
            "MAINTENANCE_SUPPLY_TOKEN"
        )
        __import__("os").environ[
            "MAINTENANCE_SUPPLY_TOKEN"
        ] = "token"
        try:
            args = argparse.Namespace(
                token_env="MAINTENANCE_SUPPLY_TOKEN",
                observed_at="2026-10-01T00:00:00Z",
                repository="o/r",
                control=1,
                owner="o/r#7",
                work_class="sync-check",
                attempt_id="attempt-dry-run",
                output=None,
                apply=False,
            )
            self.assertEqual(cli._publish_supply(args), 0)
            self.assertEqual(FakeTransport.update_calls, 0)
            self.assertEqual(FakeTransport.transition_calls, 0)
        finally:
            cli._SyncCheckGitHubTransport = original
            if old_token is None:
                del __import__("os").environ[
                    "MAINTENANCE_SUPPLY_TOKEN"
                ]
            else:
                __import__("os").environ[
                    "MAINTENANCE_SUPPLY_TOKEN"
                ] = old_token


class MaintenanceSupplyReportingFailureTests(unittest.TestCase):
    def test_post_write_reporting_failure_preserves_partial_success_result(self):
        import argparse
        import json
        import os
        from unittest.mock import patch
        from scripts import maintenance_audit as cli

        owner_body = "durable owner body\n"
        owner_digest = cli.canonical_body_sha256(owner_body)
        admission = {
            "task": "o/r#7",
            "task_body_sha256": owner_digest,
            "task_work_status": "READY_FOR_IMPLEMENTATION",
            "entry_ref": "https://github.com/o/r/issues/7",
            "scope_ready": True,
            "blocked": False,
            "requires_user_confirmation": False,
            "conflict_keys": [],
            "roles": [
                {
                    "role": "implementer",
                    "next_action_tag": "IMPLEMENT",
                }
            ],
        }
        candidate = {
            "schema_version": 1,
            "source_ref": "kinoko34077/devflow#1",
            "repository": "o/r",
            "candidates": [admission],
        }
        portfolio = {
            "schema_version": "execution-portfolio-metadata.v1",
            "source_ref": "kinoko34077/devflow#1",
            "repository": "o/r",
            "entries": [],
        }
        initial_body = (
            "## Repository\n\n`o/r`\n\n"
            "## Repository State\n\n`ACTIVE`\n\n"
            "## Next Action\n\n`[IMPLEMENT] continue`\n\n"
            "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->\n"
            + json.dumps(candidate)
            + "\n<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->\n"
            "<!-- DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1_BEGIN -->\n"
            + json.dumps(portfolio)
            + "\n<!-- DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1_END -->\n"
        )

        class FakeTransport:
            instances = []

            def __init__(self, token):
                self.body = initial_body
                self.writes = 0
                self.comments = 0
                type(self).instances.append(self)

            def get_issue(self, repository, number):
                if (repository, number) == (
                    "kinoko34077/devflow",
                    1,
                ):
                    return {
                        "state": "open",
                        "title": "[REPO] r",
                        "body": self.body,
                        "author_association": "OWNER",
                    }
                if (repository, number) == ("o/r", 7):
                    return {
                        "state": "open",
                        "title": "owner",
                        "body": owner_body,
                        "html_url": "https://github.com/o/r/issues/7",
                        "author_association": "OWNER",
                    }
                raise AssertionError((repository, number))

            def update_control_body(
                self,
                repository,
                control_ref,
                expected_body_sha256,
                body,
            ):
                self.writes += 1
                self.body = body
                return True

            def get_control(self, repository, control_ref):
                return {
                    "repository": repository,
                    "control_ref": control_ref,
                    "body": self.body,
                }

            def post_supply_transition(self, body):
                self.comments += 1
                return False

        args = argparse.Namespace(
            repository="o/r",
            control=1,
            owner="o/r#7",
            work_class="sync-check",
            attempt_id="attempt-report-fail",
            token_env="MAINTENANCE_SUPPLY_TOKEN",
            observed_at="2026-10-01T00:00:00Z",
            output=None,
            apply=True,
        )
        output = []
        with patch.object(
            cli,
            "_SyncCheckGitHubTransport",
            FakeTransport,
        ), patch.dict(
            os.environ,
            {"MAINTENANCE_SUPPLY_TOKEN": "token"},
            clear=False,
        ), patch.object(
            cli,
            "_write",
            lambda value, _output: output.append(value),
        ):
            result = cli._publish_supply(args)

        transport = FakeTransport.instances[-1]
        self.assertEqual(result, 2)
        self.assertEqual(transport.writes, 1)
        self.assertEqual(transport.comments, 1)
        self.assertTrue(output[-1]["applied"])
        self.assertFalse(output[-1]["transition_recorded"])
        self.assertEqual(output[-1]["action"], "published")
        self.assertIn("reporting_error", output[-1])


if __name__ == "__main__":
    unittest.main()
