import base64
import json
import unittest
from dataclasses import replace
from pathlib import Path

from tools import maintenance_github as mg


BASELINE_PATH = "docs/spec/maintenance/common-baseline.v1.yaml"
CATALOG_PATH = ".devflow/maintenance.yaml"
REPO = "kinoko34077/example"
CONTROL = "kinoko34077/devflow#99"
HEAD = "a" * 40


def issue(number, title, *, association="OWNER", body="", state="open"):
    return {
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "repository_url": f"https://api.github.com/repos/{REPO}",
        "author_association": association,
    }


class FakeTransport:
    def __init__(
        self,
        *,
        baseline,
        catalog,
        issues,
        comments=None,
        control_state="ACTIVE",
        control_association="OWNER",
    ):
        self.baseline = baseline
        self.catalog = catalog
        self.issues = issues
        self.comments = comments or {}
        self.file_reads = []
        self.control_state = control_state
        self.control_association = control_association

    def get_default_branch(self, repository):
        return {"name": "main", "commit": {"sha": HEAD}}

    def get_repository_file(self, repository, path, ref=None):
        self.file_reads.append((repository, path, ref))
        if repository == "kinoko34077/devflow" and path == BASELINE_PATH:
            return {"content": self.baseline, "sha": "b" * 40}
        if repository == REPO and path == CATALOG_PATH:
            return self.catalog
        raise AssertionError((repository, path, ref))

    def get_issue(self, repository, number):
        if (repository, number) != ("kinoko34077/devflow", 99):
            raise AssertionError((repository, number))
        return {
            "number": 99,
            "title": "[REPO] example",
            "state": "open",
            "body": (
                "## Repository\n\n`kinoko34077/example`\n\n"
                "## Repository State\n\n"
                f"`{self.control_state}`\n"
            ),
            "author_association": self.control_association,
        }

    def list_issues(self, repository, state="open"):
        self.assert_repo(repository)
        return list(self.issues)

    def list_issue_comments(self, repository, issue_number):
        self.assert_repo(repository)
        return list(self.comments.get(issue_number, []))

    def assert_repo(self, repository):
        if repository != REPO:
            raise AssertionError(repository)


class CatalogCollectionTests(unittest.TestCase):
    def setUp(self):
        self.baseline = Path("docs/spec/maintenance/common-baseline.v1.yaml").read_text(encoding="utf-8")
        self.catalog = json.dumps({
            "schema_version": "maintenance-catalog.v1",
            "repository": REPO,
            "baseline": "maintenance-common-baseline.v1",
            "rollout": "PILOT",
            "risk_profile": "HIGH",
            "scope_risk_overrides": [],
            "repository_lenses": [],
            "common_slot_overrides": [],
            "repository_slots": [],
        })

    def test_transport_repository_file_supports_exact_ref(self):
        seen = []

        class Response:
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self):
                return json.dumps({
                    "type": "file",
                    "sha": "c" * 40,
                    "content": base64.b64encode(b"hello").decode(),
                }).encode()

        def opener(request, timeout=0):
            seen.append(request.full_url)
            return Response()

        transport = mg.GitHubReadTransport("token", opener=opener)
        value = transport.get_repository_file(REPO, ".devflow/maintenance.yaml", ref=HEAD)
        self.assertEqual("hello", value["content"])
        self.assertIn("ref=" + HEAD, seen[0])

    def test_collect_catalog_reads_target_exact_default_head(self):
        transport = FakeTransport(
            baseline=self.baseline,
            catalog={"content": self.catalog, "sha": "d" * 40},
            issues=[issue(7, "[MAINTENANCE] Audit Ledger")],
        )
        observation = mg.collect_maintenance_catalog(transport, REPO, CONTROL)
        self.assertEqual("OK", observation["status"])
        self.assertEqual(HEAD, observation["code_sha"])
        self.assertRegex(observation["catalog_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertIn((REPO, CATALOG_PATH, HEAD), transport.file_reads)

    def test_missing_catalog_is_no_catalog_not_guessed_work(self):
        transport = FakeTransport(
            baseline=self.baseline,
            catalog=None,
            issues=[issue(7, "[MAINTENANCE] Audit Ledger")],
        )
        observation = mg.collect_maintenance_catalog(transport, REPO, CONTROL)
        self.assertEqual(("NO_CATALOG", "CATALOG_NOT_FOUND"), (observation["status"], observation["reason_code"]))

    def test_malformed_catalog_is_needs_evidence(self):
        transport = FakeTransport(
            baseline=self.baseline,
            catalog={"content": "{bad", "sha": "d" * 40},
            issues=[issue(7, "[MAINTENANCE] Audit Ledger")],
        )
        observation = mg.collect_maintenance_catalog(transport, REPO, CONTROL)
        self.assertEqual(("NEEDS_EVIDENCE", "CATALOG_INVALID"), (observation["status"], observation["reason_code"]))

    def test_missing_or_multiple_ledger_is_typed_evidence_failure(self):
        for issues, code in (
            ([], "LEDGER_NOT_FOUND"),
            ([issue(7, "[MAINTENANCE] Audit Ledger"), issue(8, "[MAINTENANCE] Audit Ledger")], "LEDGER_DUPLICATE"),
        ):
            with self.subTest(code=code):
                transport = FakeTransport(
                    baseline=self.baseline,
                    catalog={"content": self.catalog, "sha": "d" * 40},
                    issues=issues,
                )
                result = mg.collect_maintenance_selection(transport, REPO, CONTROL, "2026-10-07T00:00:00Z")
                self.assertEqual(("NEEDS_EVIDENCE", code), (result["status"], result["reason_code"]))

    def test_only_trusted_ledger_comments_contribute_history(self):
        from tools.maintenance_ledger import RunRecord, render_run_comment
        trusted = RunRecord(
            repository=REPO,
            run_id=f"audit:{REPO}:common.correctness:1",
            slot_id="common.correctness",
            generation=1,
            lens="correctness",
            depth="STANDARD",
            fingerprint="sha256:" + "1" * 64,
            result="CLEAN",
            findings_summary="none",
            completed_at="2026-09-01T00:00:00Z",
            next_eligibility_reason=None,
            evidence_refs=(),
        )
        untrusted = replace(
            trusted,
            generation=2,
            run_id=f"audit:{REPO}:common.correctness:2",
            completed_at="2026-10-01T00:00:00Z",
        )
        transport = FakeTransport(
            baseline=self.baseline,
            catalog={"content": self.catalog, "sha": "d" * 40},
            issues=[issue(7, "[MAINTENANCE] Audit Ledger")],
            comments={
                7: [
                    {"body": render_run_comment(trusted), "author_association": "OWNER"},
                    {"body": render_run_comment(untrusted), "author_association": "NONE"},
                ]
            },
        )
        history = mg.collect_maintenance_history(transport, REPO, 7)
        self.assertEqual((trusted,), history)

    def test_inactive_repository_is_not_selectable(self):
        transport = FakeTransport(
            baseline=self.baseline,
            catalog={"content": self.catalog, "sha": "d" * 40},
            issues=[issue(7, "[MAINTENANCE] Audit Ledger")],
            control_state="PARKED",
        )
        result = mg.collect_maintenance_selection(
            transport,
            REPO,
            CONTROL,
            "2026-10-07T00:00:00Z",
        )
        self.assertEqual(("NO_ELIGIBLE_WORK", "REPOSITORY_NOT_ACTIVE"), (
            result["status"],
            result["reason_code"],
        ))

    def test_untrusted_control_fails_selection_closed(self):
        transport = FakeTransport(
            baseline=self.baseline,
            catalog={"content": self.catalog, "sha": "d" * 40},
            issues=[issue(7, "[MAINTENANCE] Audit Ledger")],
            control_association="NONE",
        )
        result = mg.collect_maintenance_selection(
            transport,
            REPO,
            CONTROL,
            "2026-10-07T00:00:00Z",
        )
        self.assertEqual(("NEEDS_EVIDENCE", "CONTROL_INVALID"), (
            result["status"],
            result["reason_code"],
        ))

    def test_external_observation_changes_fingerprint_without_code_change(self):
        first = mg.build_maintenance_fingerprint(
            HEAD,
            "sha256:" + "2" * 64,
            {"provider_spec": "v1"},
        )
        second = mg.build_maintenance_fingerprint(
            HEAD,
            "sha256:" + "2" * 64,
            {"provider_spec": "v2"},
        )
        self.assertNotEqual(first, second)

    def test_rollout_disable_reenable_preserves_history_and_restores_selection(self):
        from tools.maintenance_ledger import RunRecord, render_run_comment

        prior = RunRecord(
            repository=REPO,
            run_id=f"audit:{REPO}:common.correctness:1",
            slot_id="common.correctness",
            generation=1,
            lens="correctness",
            depth="STANDARD",
            fingerprint="sha256:" + "1" * 64,
            result="CLEAN",
            findings_summary="prior accepted history",
            completed_at="2026-09-01T00:00:00Z",
            next_eligibility_reason=None,
            evidence_refs=("https://example.invalid/evidence",),
        )
        comments = {
            7: [{
                "body": render_run_comment(prior),
                "author_association": "OWNER",
            }]
        }
        issues = [issue(7, "[MAINTENANCE] Audit Ledger")]

        pilot = FakeTransport(
            baseline=self.baseline,
            catalog={"content": self.catalog, "sha": "d" * 40},
            issues=issues,
            comments=comments,
        )
        history_before = mg.collect_maintenance_history(pilot, REPO, 7)
        selected_before = mg.collect_maintenance_selection(
            pilot,
            REPO,
            CONTROL,
            "2026-10-07T00:00:00Z",
        )
        self.assertEqual("SELECTED", selected_before["status"])

        disabled_catalog = json.loads(self.catalog)
        disabled_catalog["rollout"] = "DISABLED"
        disabled = FakeTransport(
            baseline=self.baseline,
            catalog={
                "content": json.dumps(disabled_catalog),
                "sha": "e" * 40,
            },
            issues=issues,
            comments=comments,
        )
        disabled_result = mg.collect_maintenance_selection(
            disabled,
            REPO,
            CONTROL,
            "2026-10-07T00:00:00Z",
        )
        self.assertEqual(
            ("NO_ELIGIBLE_WORK", "MAINTENANCE_DISABLED"),
            (disabled_result["status"], disabled_result["reason_code"]),
        )
        self.assertEqual(
            history_before,
            mg.collect_maintenance_history(disabled, REPO, 7),
        )

        restored = FakeTransport(
            baseline=self.baseline,
            catalog={"content": self.catalog, "sha": "f" * 40},
            issues=issues,
            comments=comments,
        )
        selected_after = mg.collect_maintenance_selection(
            restored,
            REPO,
            CONTROL,
            "2026-10-07T00:00:00Z",
        )
        self.assertEqual("SELECTED", selected_after["status"])
        self.assertEqual(
            history_before,
            mg.collect_maintenance_history(restored, REPO, 7),
        )
        self.assertEqual(
            selected_before["selected"],
            selected_after["selected"],
        )


class MultiRepoTransport:
    def __init__(
        self,
        *,
        baseline,
        catalogs,
        issues,
        comments=None,
        heads=None,
        control_states=None,
    ):
        self.baseline = baseline
        self.catalogs = catalogs
        self.issues = issues
        self.comments = comments or {}
        self.heads = heads or {}
        self.control_states = control_states or {}

    def get_default_branch(self, repository):
        default = {
            "kinoko34077/devflow": "d" * 40,
            "kinoko34077/a": "a" * 40,
            "kinoko34077/b": "b" * 40,
        }
        return {
            "name": "main",
            "commit": {"sha": self.heads.get(repository, default.get(repository, "c" * 40))},
        }

    def get_repository_file(self, repository, path, ref=None):
        if repository == "kinoko34077/devflow" and path == BASELINE_PATH:
            return {"content": self.baseline, "sha": "e" * 40}
        if path == CATALOG_PATH:
            return self.catalogs.get(repository)
        raise AssertionError((repository, path, ref))

    def get_issue(self, repository, number):
        if repository != "kinoko34077/devflow" or number not in {10, 11}:
            raise AssertionError((repository, number))
        managed = "kinoko34077/a" if number == 10 else "kinoko34077/b"
        return {
            "number": number,
            "title": f"[REPO] {managed.rsplit('/', 1)[-1]}",
            "state": "open",
            "body": (
                f"## Repository\n\n`{managed}`\n\n"
                "## Repository State\n\n"
                f"`{self.control_states.get(managed, 'ACTIVE')}`\n"
            ),
            "author_association": "OWNER",
        }

    def list_issues(self, repository, state="open"):
        return list(self.issues.get(repository, []))

    def list_issue_comments(self, repository, issue_number):
        return list(self.comments.get((repository, issue_number), []))


def portfolio_issue(repository, number=7):
    return {
        "number": number,
        "title": "[MAINTENANCE] Audit Ledger",
        "body": "## Work Status\n\n`AUDITED`\n",
        "state": "open",
        "html_url": f"https://github.com/{repository}/issues/{number}",
        "repository_url": f"https://api.github.com/repos/{repository}",
        "author_association": "OWNER",
    }


def portfolio_catalog(repository, *, risk="MEDIUM", rollout="PILOT"):
    return {
        "content": json.dumps({
            "schema_version": "maintenance-catalog.v1",
            "repository": repository,
            "baseline": "maintenance-common-baseline.v1",
            "rollout": rollout,
            "risk_profile": risk,
            "scope_risk_overrides": [],
            "repository_lenses": [],
            "common_slot_overrides": [],
            "repository_slots": [],
        }),
        "sha": ("1" if repository.endswith("/a") else "2") * 40,
    }


class PortfolioMaintenanceCollectionTests(unittest.TestCase):
    def setUp(self):
        self.baseline = Path(
            "docs/spec/maintenance/common-baseline.v1.yaml"
        ).read_text(encoding="utf-8")
        self.controls = [
            {"repository": "kinoko34077/a", "control_ref": "kinoko34077/devflow#10"},
            {"repository": "kinoko34077/b", "control_ref": "kinoko34077/devflow#11"},
        ]

    def transport(
        self,
        *,
        catalogs=None,
        issues=None,
        comments=None,
        control_states=None,
    ):
        return MultiRepoTransport(
            baseline=self.baseline,
            catalogs=catalogs or {
                "kinoko34077/a": portfolio_catalog("kinoko34077/a", risk="LOW"),
                "kinoko34077/b": portfolio_catalog("kinoko34077/b", risk="CRITICAL"),
            },
            issues=issues or {
                "kinoko34077/a": [portfolio_issue("kinoko34077/a")],
                "kinoko34077/b": [portfolio_issue("kinoko34077/b")],
            },
            comments=comments,
            control_states=control_states,
        )

    def test_portfolio_selection_scores_all_participating_repositories_together(self):
        result = mg.collect_maintenance_portfolio_selection(
            self.transport(),
            self.controls,
            "2026-10-07T00:00:00Z",
        )
        self.assertEqual("SELECTED", result["status"])
        self.assertEqual("kinoko34077/b", result["repository"])
        self.assertEqual("kinoko34077/devflow#11", result["control_ref"])
        self.assertEqual("kinoko34077/b#7", result["ledger_ref"])
        self.assertEqual("PORTFOLIO", result["selection_scope"])

    def test_missing_catalog_is_nonparticipant_not_guessed_work(self):
        result = mg.collect_maintenance_portfolio_selection(
            self.transport(catalogs={
                "kinoko34077/a": None,
                "kinoko34077/b": portfolio_catalog("kinoko34077/b", risk="HIGH"),
            }),
            self.controls,
            "2026-10-07T00:00:00Z",
        )
        self.assertEqual("SELECTED", result["status"])
        self.assertEqual("kinoko34077/b", result["repository"])

    def test_malformed_existing_catalog_fails_portfolio_closed(self):
        result = mg.collect_maintenance_portfolio_selection(
            self.transport(catalogs={
                "kinoko34077/a": portfolio_catalog("kinoko34077/a"),
                "kinoko34077/b": {"content": "{bad", "sha": "2" * 40},
            }),
            self.controls,
            "2026-10-07T00:00:00Z",
        )
        self.assertEqual(("NEEDS_EVIDENCE", "CATALOG_INVALID"), (
            result["status"],
            result["reason_code"],
        ))
        self.assertEqual("kinoko34077/b", result["repository"])

    def test_participating_repository_without_ledger_fails_closed(self):
        result = mg.collect_maintenance_portfolio_selection(
            self.transport(issues={
                "kinoko34077/a": [portfolio_issue("kinoko34077/a")],
                "kinoko34077/b": [],
            }),
            self.controls,
            "2026-10-07T00:00:00Z",
        )
        self.assertEqual(("NEEDS_EVIDENCE", "LEDGER_NOT_FOUND"), (
            result["status"],
            result["reason_code"],
        ))
        self.assertEqual("kinoko34077/b", result["repository"])

    def test_inactive_repository_is_filtered_before_global_scoring(self):
        result = mg.collect_maintenance_portfolio_selection(
            self.transport(control_states={
                "kinoko34077/b": "PARKED",
            }),
            self.controls,
            "2026-10-07T00:00:00Z",
        )
        self.assertEqual("SELECTED", result["status"])
        self.assertEqual("kinoko34077/a", result["repository"])

    def test_disabled_catalog_is_not_eligible(self):
        result = mg.collect_maintenance_portfolio_selection(
            self.transport(catalogs={
                "kinoko34077/a": portfolio_catalog("kinoko34077/a", risk="LOW"),
                "kinoko34077/b": portfolio_catalog(
                    "kinoko34077/b",
                    risk="CRITICAL",
                    rollout="DISABLED",
                ),
            }),
            self.controls,
            "2026-10-07T00:00:00Z",
        )
        self.assertEqual("SELECTED", result["status"])
        self.assertEqual("kinoko34077/a", result["repository"])

    def test_previous_repository_penalty_rotates_equal_candidates(self):
        catalogs = {
            "kinoko34077/a": portfolio_catalog("kinoko34077/a", risk="MEDIUM"),
            "kinoko34077/b": portfolio_catalog("kinoko34077/b", risk="MEDIUM"),
        }
        result = mg.collect_maintenance_portfolio_selection(
            self.transport(catalogs=catalogs),
            self.controls,
            "2026-10-07T00:00:00Z",
            previous_repository="kinoko34077/a",
        )
        self.assertEqual("kinoko34077/b", result["repository"])

    def test_no_catalogs_returns_true_maintenance_exhaustion(self):
        result = mg.collect_maintenance_portfolio_selection(
            self.transport(catalogs={
                "kinoko34077/a": None,
                "kinoko34077/b": None,
            }),
            self.controls,
            "2026-10-07T00:00:00Z",
        )
        self.assertEqual(("NO_ELIGIBLE_WORK", "MAINTENANCE_EXHAUSTED"), (
            result["status"],
            result["reason_code"],
        ))
        self.assertEqual("PORTFOLIO", result["selection_scope"])



if __name__ == "__main__":
    unittest.main()
