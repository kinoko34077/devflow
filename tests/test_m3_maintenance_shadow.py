"""M3 Maintenance consumer shadow: no authority or runtime classifier changes."""
import argparse
import copy
import unittest
from unittest import mock

from tools import maintenance_github as mg
from tools import maintenance_audit as ma


REPOSITORY = "kinoko34077/testapp"
CONTROL_REF = "kinoko34077/devflow#32"
CONTROL_URL = "https://github.com/kinoko34077/devflow/issues/32"
OWNER_REF = "kinoko34077/testapp#30"
ACTIVE = "kinoko34077/testapp#30"
NEXT = "`[WAIT] Retain Human policy and manual routing.`"


def task(number=30, status="AWAITING_REVIEW"):
    return {
        "issue_number": number,
        "record_role": "TASK",
        "source_kind": "MACHINE",
        "work_status": status,
        "url": f"https://github.com/{REPOSITORY}/issues/{number}",
    }


def view(*records):
    return {
        "repository": REPOSITORY,
        "control_ref": CONTROL_URL,
        "source_status": "AVAILABLE",
        "source_freshness": "CURRENT",
        "source_error": None,
        "coverage_status": "COMPLETE",
        "view_mode": "MACHINE_COMPLETE_SHADOW",
        "can_replace_manual_active_work": False,
        "machine_task_count": len(records),
        "legacy_hint_count": 0,
        "unclassified_count": 0,
        "invalid_metadata_count": 0,
        "untrusted_metadata_count": 0,
        "manual_control": {"active_work": ACTIVE, "next_action": NEXT},
        "task_records": list(records),
    }


def shadow(
    work_view, manual_owner_ref=OWNER_REF, *, trusted=True,
    source_status="OK", legacy_owner_work_status="AWAITING_REVIEW",
):
    return mg._m3_owner_shadow(
        work_view,
        repository=REPOSITORY,
        control_ref=CONTROL_REF,
        sections={"Active Work": ACTIVE, "Next Action": NEXT},
        trusted=trusted,
        source_status=source_status,
        manual_owner_ref=manual_owner_ref,
        legacy_owner_work_status=legacy_owner_work_status,
    )


class M3OwnerShadowTests(unittest.TestCase):
    def test_review_and_blocked_are_retained_without_runtime_authority(self):
        for state in ("READY_FOR_IMPLEMENTATION", "IMPLEMENTING", "AWAITING_REVIEW", "BLOCKED", "DONE"):
            with self.subTest(state=state):
                result = shadow(
                    view(task(status=state)),
                    legacy_owner_work_status=state,
                )
                self.assertEqual(result["status"], "MATCHED_SHADOW")
                self.assertEqual(
                    result["reason"], "SAME_SINGLE_OWNER_AND_WORK_STATUS",
                )
                self.assertEqual(result["machine_task_refs"], [OWNER_REF])
                self.assertFalse(result["can_replace_manual_active_work"])

    def test_same_owner_reference_does_not_hide_missing_or_conflicting_status(self):
        current = view(task(status="IMPLEMENTING"))
        missing = shadow(current, legacy_owner_work_status=None)
        self.assertEqual(missing["status"], "MANUAL_CONTROL_FALLBACK")
        self.assertEqual(missing["reason"], "OWNER_STATUS_NOT_VERIFIED")
        self.assertIsNone(missing["legacy_owner_work_status"])
        self.assertEqual(missing["machine_owner_work_status"], "IMPLEMENTING")
        mismatch = shadow(current, legacy_owner_work_status="AWAITING_REVIEW")
        self.assertEqual(mismatch["status"], "MANUAL_CONTROL_FALLBACK")
        self.assertEqual(mismatch["reason"], "MANUAL_MACHINE_STATUS_DISAGREEMENT")
        self.assertEqual(mismatch["machine_owner_work_status"], "IMPLEMENTING")
        self.assertEqual(mismatch["legacy_owner_work_status"], "AWAITING_REVIEW")
        self.assertFalse(missing["can_replace_manual_active_work"])
        self.assertFalse(mismatch["can_replace_manual_active_work"])
        matched = shadow(current, legacy_owner_work_status="IMPLEMENTING")
        self.assertEqual(matched["status"], "MATCHED_SHADOW")
        self.assertFalse(matched["can_replace_manual_active_work"])

    def test_multiple_full_state_tasks_never_become_one_maintenance_owner(self):
        result = shadow(view(task(), task(31, "BLOCKED")))
        self.assertEqual(result["status"], "MULTIPLE_TASKS_SHADOW")
        self.assertEqual(result["reason"], "ONE_OWNER_CONTRACT_INSUFFICIENT")
        self.assertEqual(result["machine_task_refs"], [OWNER_REF, f"{REPOSITORY}#31"])
        self.assertFalse(result["can_replace_manual_active_work"])

    def test_empty_true_complete_is_not_a_nonempty_cutover_proof(self):
        result = shadow(view(), manual_owner_ref=None)
        self.assertEqual(result["status"], "MATCHED_EMPTY_SHADOW")
        self.assertFalse(result["can_replace_manual_active_work"])

    def test_stale_manual_owner_is_only_diagnostic(self):
        result = shadow(view(task(31)))
        self.assertEqual(result["status"], "DIVERGENT_SHADOW")
        self.assertEqual(result["manual_owner_ref"], OWNER_REF)
        self.assertFalse(result["can_replace_manual_active_work"])

    def test_all_unsafe_coverage_and_integrity_cases_fallback(self):
        good = view(task())
        mutations = [
            ("repository", "other/repo"),
            ("control_ref", "https://github.com/kinoko34077/devflow/issues/31"),
            ("source_status", "UNAVAILABLE"),
            ("source_freshness", "STALE"),
            ("source_error", "transport unavailable"),
            ("coverage_status", "INCOMPLETE"),
            ("view_mode", "MANUAL_CONTROL_FALLBACK"),
            ("can_replace_manual_active_work", True),
            ("legacy_hint_count", 1),
            ("unclassified_count", 1),
            ("invalid_metadata_count", 1),
            ("untrusted_metadata_count", 1),
            ("machine_task_count", 2),
            ("machine_task_count", True),
            ("task_records", []),
            ("task_records", [task(), task()]),
            ("task_records", [dict(task(), record_role="TRACKER")]),
            ("task_records", [dict(task(), source_kind="LEGACY")]),
            ("task_records", [dict(task(), url="https://github.com/evil/repo/issues/30")]),
            ("manual_control", {"active_work": "different", "next_action": NEXT}),
        ]
        for key, value in mutations:
            with self.subTest(field=key, value=str(value)[:40]):
                bad = copy.deepcopy(good)
                bad[key] = value
                out = shadow(bad)
                self.assertEqual(out["status"], "MANUAL_CONTROL_FALLBACK")
                self.assertFalse(out["can_replace_manual_active_work"])
        for bad in (None, {}, [], "not a view"):
            self.assertEqual(shadow(bad)["status"], "MANUAL_CONTROL_FALLBACK")
        self.assertEqual(shadow(good, trusted=False)["status"], "MANUAL_CONTROL_FALLBACK")
        self.assertEqual(shadow(good, source_status="UNAVAILABLE")["status"], "MANUAL_CONTROL_FALLBACK")

    def test_default_collector_and_classifier_unchanged_and_opt_in_is_diagnostic(self):
        body = (
            f"## Repository\n\n`{REPOSITORY}`\n\n"
            "## Work Status\n\n`AWAITING_REVIEW`\n\n"
            f"## Active Work\n\n{ACTIVE}\n\n"
            f"## Next Action\n\n{NEXT}\n\n"
        )

        class Transport:
            def __init__(self):
                self.paths = []

            def get_json(self, path):
                self.paths.append(path)
                if path.endswith("/issues/32"):
                    return {
                        "number": 32, "title": "[REPO] testapp", "state": "open",
                        "html_url": CONTROL_URL, "body": body,
                        "author_association": "OWNER",
                        "user": {"id": 79015263, "login": "kinoko34077"},
                        "updated_at": "2026-10-12T07:00:00Z",
                    }
                if path.endswith("/issues/30"):
                    return {
                        "number": 30, "title": "M3 real task", "state": "open",
                        "html_url": f"https://github.com/{REPOSITORY}/issues/30",
                        "body": "## Work Status\n\n`AWAITING_REVIEW`\n",
                        "author_association": "OWNER",
                        "user": {"id": 79015263, "login": "kinoko34077"},
                        "updated_at": "2026-10-12T07:00:00Z",
                    }
                raise AssertionError(path)

        no_shadow = mg.collect_repository(Transport(), REPOSITORY, CONTROL_REF, "2026-10-12T07:01:00Z")
        self.assertNotIn("m3_shadow", no_shadow)
        baseline = ma.classify_repository(no_shadow)
        transport = Transport()
        # Work View's canonical parser strips the enclosing Markdown ticks
        # from the Control's scalar Next Action. The Maintenance collector
        # must not misdiagnose that formatting as a changed Control revision.
        canonical_view = view(task())
        canonical_view["manual_control"]["next_action"] = NEXT.strip("`")
        with_shadow = mg.collect_repository(
            transport, REPOSITORY, CONTROL_REF, "2026-10-12T07:01:00Z",
            m3_work_view=canonical_view,
        )
        self.assertEqual(with_shadow["m3_shadow"]["status"], "MATCHED_SHADOW")
        self.assertEqual(transport.paths, [
            "/repos/kinoko34077/devflow/issues/32", "/repos/kinoko34077/testapp/issues/30",
        ])
        with_shadow.pop("m3_shadow")
        self.assertEqual(no_shadow, with_shadow)
        self.assertEqual(ma.classify_repository(with_shadow), baseline)

        changed = copy.deepcopy(canonical_view)
        changed["manual_control"]["next_action"] = "[WAIT] A different Human gate."
        conflict = mg.collect_repository(
            Transport(), REPOSITORY, CONTROL_REF, "2026-10-12T07:01:00Z",
            m3_work_view=changed,
        )
        self.assertEqual(
            conflict["m3_shadow"]["status"], "MANUAL_CONTROL_FALLBACK",
        )
        self.assertEqual(
            conflict["m3_shadow"]["reason"], "MANUAL_CONTROL_REVISION_MISMATCH",
        )
        self.assertFalse(conflict["m3_shadow"]["can_replace_manual_active_work"])
        self.assertEqual(ma.classify_repository(conflict), baseline)

    def test_collector_never_calls_matching_owner_status_parity_on_missing_heading(self):
        body = (
            f"## Repository\n\n`{REPOSITORY}`\n\n"
            f"## Active Work\n\n{ACTIVE}\n\n"
            f"## Next Action\n\n{NEXT}\n"
        )

        class Transport:
            def get_json(self, path):
                if path.endswith("/issues/32"):
                    return {
                        "number": 32, "title": "[REPO] testapp", "state": "open",
                        "html_url": CONTROL_URL, "body": body,
                        "author_association": "OWNER",
                        "user": {"id": 79015263, "login": "kinoko34077"},
                        "updated_at": "2026-10-12T07:00:00Z",
                    }
                if path.endswith("/issues/30"):
                    return {
                        "number": 30, "title": "M3 genuine Issue metadata only",
                        "state": "open",
                        "html_url": f"https://github.com/{REPOSITORY}/issues/30",
                        "body": "## Scope\n\nThe Work Status is in trusted V1 metadata.",
                        "author_association": "OWNER",
                        "user": {"id": 79015263, "login": "kinoko34077"},
                        "updated_at": "2026-10-12T07:00:00Z",
                    }
                raise AssertionError(path)

        canonical = view(task(status="IMPLEMENTING"))
        canonical["manual_control"]["next_action"] = NEXT.strip("`")
        baseline = mg.collect_repository(
            Transport(), REPOSITORY, CONTROL_REF, "2026-10-12T07:01:00Z",
        )
        observed = mg.collect_repository(
            Transport(), REPOSITORY, CONTROL_REF, "2026-10-12T07:01:00Z",
            m3_work_view=canonical,
        )
        self.assertEqual(
            observed["m3_shadow"]["reason"], "OWNER_STATUS_NOT_VERIFIED",
        )
        self.assertFalse(observed["m3_shadow"]["can_replace_manual_active_work"])
        observed.pop("m3_shadow")
        self.assertEqual(observed, baseline)
        self.assertEqual(
            ma.classify_repository(observed),
            ma.classify_repository(baseline),
        )

    def test_mismatched_optional_view_does_not_change_maintenance_result(self):
        control = (
            f"## Repository\n\n`{REPOSITORY}`\n\n"
            "## Work Status\n\n`AUDITED`\n\n"
            "## Active Work\n\nNo active repository-local implementation owner.\n\n"
            f"## Next Action\n\n{NEXT}\n"
        )
        class Transport:
            def get_json(self, path):
                if path.endswith("/issues/32"):
                    return {"number": 32, "title": "[REPO] testapp", "state": "open",
                            "html_url": CONTROL_URL, "author_association": "OWNER",
                            "user": {"id": 79015263, "login": "kinoko34077"},
                            "body": control, "updated_at": "2026-10-12T07:00:00Z"}
                raise AssertionError(path)
        out = mg.collect_repository(Transport(), REPOSITORY, CONTROL_REF,
                                    "2026-10-12T07:01:00Z", m3_work_view=view(task()))
        self.assertEqual(out["m3_shadow"]["status"], "MANUAL_CONTROL_FALLBACK")
        self.assertEqual(ma.classify_repository(out)["disposition"], "NO_ACTION")


class MaintenanceCLIParityTests(unittest.TestCase):
    def _run_repository(self, *, opt_in, source_unavailable=False):
        from scripts import maintenance_audit as cli

        args = argparse.Namespace(
            repository=REPOSITORY, control=32, observed_at="2026-10-12T07:01:00Z",
            output=None, token_env="GITHUB_TOKEN", m3_read_parity=opt_in,
        )
        writes = []
        work_view = view(task(status="IMPLEMENTING"))
        shadow_value = {
            "status": "MANUAL_CONTROL_FALLBACK",
            "reason": "OWNER_STATUS_NOT_VERIFIED",
            "manual_owner_ref": OWNER_REF,
            "legacy_owner_work_status": None,
            "machine_owner_work_status": "IMPLEMENTING",
            "can_replace_manual_active_work": False,
        }
        seen = []

        def collect(_transport, repository, control_ref, observed_at, *,
                    m3_work_view=None):
            seen.append(m3_work_view)
            data = {"source_status": "OK", "owner": {"ref": OWNER_REF}}
            if m3_work_view is not None:
                data["m3_shadow"] = dict(shadow_value)
            return data

        with (
            mock.patch.object(cli, "_token_from_env", return_value="opaque-test-token"),
            mock.patch.object(cli, "GitHubReadTransport"),
            mock.patch.object(cli, "_classify_observation",
                              return_value={"disposition": "NO_ACTION"}),
            mock.patch.object(cli, "collect_repository", side_effect=collect),
            mock.patch.object(cli, "_write", side_effect=lambda value, _: writes.append(value)),
            mock.patch.object(cli.devflow_mcp_core, "GitHubReader"),
            mock.patch.object(cli.devflow_mcp_core, "DevflowService") as service_type,
        ):
            service = service_type.return_value
            if source_unavailable:
                service.get_repository_work_view.side_effect = (
                    cli.devflow_mcp_core.DevflowMCPError("unavailable")
                )
            else:
                service.get_repository_work_view.return_value = work_view
            code = cli._repository(args)
            self.assertEqual(code, 0)
            self.assertEqual(service.get_repository_work_view.call_count,
                             1 if opt_in else 0)
        return writes[0], seen

    def test_default_cli_does_not_read_m3_or_change_existing_report(self):
        result, seen = self._run_repository(opt_in=False)
        self.assertEqual(result, {"disposition": "NO_ACTION"})
        self.assertEqual(seen, [None])

    def test_opt_in_cli_exposes_existing_shadow_without_changing_classification(self):
        result, seen = self._run_repository(opt_in=True)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["task_records"][0]["work_status"], "IMPLEMENTING")
        self.assertEqual(result["disposition"], "NO_ACTION")
        diagnostic = result["m3_read_parity"]
        self.assertEqual(diagnostic["reason"], "OWNER_STATUS_NOT_VERIFIED")
        self.assertEqual(diagnostic["use_level"], "READ_ONLY_DIAGNOSTIC")
        self.assertFalse(diagnostic["can_authorize_execution"])
        self.assertFalse(diagnostic["can_replace_manual_active_work"])

    def test_opt_in_unavailable_m3_source_preserves_manual_disposition(self):
        result, seen = self._run_repository(opt_in=True, source_unavailable=True)
        self.assertEqual(seen, [None])
        self.assertEqual(result["disposition"], "NO_ACTION")
        self.assertEqual(result["m3_read_parity"]["status"], "MANUAL_CONTROL_FALLBACK")
        self.assertEqual(result["m3_read_parity"]["reason"], "MACHINE_SOURCE_UNAVAILABLE")
        self.assertFalse(result["m3_read_parity"]["can_authorize_execution"])

    def test_flag_is_not_available_on_effectful_subcommands(self):
        from scripts import maintenance_audit as cli
        parser = cli._parser()
        args = parser.parse_args([
            "repository", "--repository", REPOSITORY, "--control", "32",
            "--m3-read-parity",
        ])
        self.assertTrue(args.m3_read_parity)
        with mock.patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                parser.parse_args([
                    "select-maintenance", "--repository", REPOSITORY,
                    "--control", "32", "--m3-read-parity",
                ])


if __name__ == "__main__":
    unittest.main()
