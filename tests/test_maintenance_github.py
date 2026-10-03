import io
import json
import unittest
from urllib.error import HTTPError
from pathlib import Path

from tests.test_repository_bootstrap import issue_body, request_payload

try:
    from tools import maintenance_github as mg
except ImportError:
    mg = None


WORKFLOW = Path(".github/workflows/maintenance-audit.yml")
HEAD = "a" * 40
OTHER = "b" * 40


class FakeResponse:
    def __init__(self, payload, headers=None):
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class MaintenanceGitHubTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            mg,
            "maintenance_github module must exist",
        )

    def test_transport_uses_get_only_and_bearer_token(self):
        seen = []

        def opener(request, timeout=0):
            seen.append(request)
            return FakeResponse({"full_name": "o/r"})

        transport = mg.GitHubReadTransport(
            "secret-token",
            opener=opener,
        )
        self.assertEqual(
            transport.get_json("/repos/o/r")["full_name"],
            "o/r",
        )
        self.assertEqual(seen[0].method, "GET")
        self.assertEqual(
            seen[0].get_header("Authorization"),
            "Bearer secret-token",
        )

    def test_pagination_follows_link_next(self):
        calls = []

        def opener(request, timeout=0):
            calls.append(request.full_url)
            if len(calls) == 1:
                return FakeResponse(
                    [{"number": 1}],
                    {
                        "Link": (
                            '<https://api.github.com/page2>; '
                            'rel="next"'
                        )
                    },
                )
            return FakeResponse([{"number": 2}])

        transport = mg.GitHubReadTransport(
            "token",
            opener=opener,
        )
        self.assertEqual(
            [
                item["number"]
                for item in transport.get_paginated("/items")
            ],
            [1, 2],
        )

    def test_http_failure_redacts_token(self):
        def opener(request, timeout=0):
            raise HTTPError(
                request.full_url,
                403,
                "forbidden secret-token",
                {},
                io.BytesIO(),
            )

        transport = mg.GitHubReadTransport(
            "secret-token",
            opener=opener,
        )
        with self.assertRaises(mg.GitHubReadError) as ctx:
            transport.get_json("/repos/o/r")
        self.assertNotIn(
            "secret-token",
            str(ctx.exception),
        )

    def test_collect_repository_preserves_source_failure(self):
        class Broken:
            def get_json(self, path):
                raise mg.GitHubReadError("unavailable")

        observation = mg.collect_repository(
            Broken(),
            "o/r",
            "o/r#1",
            "2026-10-01T00:00:00Z",
        )
        self.assertEqual(
            observation["source_status"],
            "UNAVAILABLE",
        )

    def test_pull_evidence_binds_checks_and_reviews_to_exact_head(self):
        calls = []

        def opener(request, timeout=0):
            url = request.full_url
            calls.append(url)
            if url.endswith("/repos/o/r/pulls/7"):
                return FakeResponse(
                    {
                        "number": 7,
                        "head": {"sha": HEAD},
                    }
                )
            if (
                f"/repos/o/r/commits/{HEAD}/check-runs"
                in url
                and "page=2" not in url
            ):
                return FakeResponse(
                    {"check_runs": [{"id": 11}]},
                    {
                        "Link": (
                            f"<https://api.github.com/repos/o/r/"
                            f"commits/{HEAD}/check-runs?"
                            'per_page=100&page=2>; rel="next"'
                        )
                    },
                )
            if (
                f"/repos/o/r/commits/{HEAD}/check-runs"
                in url
                and "page=2" in url
            ):
                return FakeResponse(
                    {"check_runs": [{"id": 12}]}
                )
            if "/repos/o/r/pulls/7/reviews" in url:
                return FakeResponse(
                    [
                        {
                            "id": 21,
                            "commit_id": HEAD,
                            "state": "COMMENTED",
                        },
                        {
                            "id": 22,
                            "commit_id": OTHER,
                            "state": "APPROVED",
                        },
                    ]
                )
            raise AssertionError(f"unexpected read: {url}")

        transport = mg.GitHubReadTransport(
            "token",
            opener=opener,
        )
        evidence = transport.get_pull_evidence("o/r", 7)

        self.assertEqual(evidence["head_sha"], HEAD)
        self.assertEqual(
            [item["id"] for item in evidence["check_runs"]],
            [11, 12],
        )
        self.assertEqual(
            [item["id"] for item in evidence["reviews"]],
            [21],
        )
        self.assertTrue(
            all(
                request_url.startswith("https://api.github.com/")
                for request_url in calls
            )
        )

    def test_duplicate_controls_fail_closed_before_owner_read(self):
        class Transport:
            def get_json(self, path):
                raise AssertionError(
                    "duplicate Control set must not read an owner"
                )

        observations = mg.collect_portfolio(
            Transport(),
            [
                {
                    "repository": "o/r",
                    "control_ref": "kinoko34077/devflow#1",
                },
                {
                    "repository": "o/r",
                    "control_ref": "kinoko34077/devflow#2",
                },
            ],
            "2026-10-01T00:00:00Z",
        )
        self.assertEqual(len(observations), 1)
        self.assertEqual(
            observations[0]["source_status"],
            "UNAVAILABLE",
        )
        self.assertIn(
            "duplicate",
            observations[0]["source_error"],
        )

    def test_control_discovery_re_reads_exact_issue(self):
        class Transport:
            def __init__(self):
                self.exact_reads = []

            def get_paginated(self, path):
                return [
                    {
                        "number": 16,
                        "title": "[REPO] example",
                    }
                ]

            def get_issue(self, repository, number):
                self.exact_reads.append(
                    (repository, number)
                )
                return {
                    "number": number,
                    "body": (
                        "## Repository\n\n"
                        "`kinoko34077/example`\n"
                    ),
                }

        transport = Transport()
        controls = mg.discover_controls(transport)

        self.assertEqual(
            controls,
            [
                {
                    "repository": "kinoko34077/example",
                    "control_ref": "kinoko34077/devflow#16",
                }
            ],
        )
        self.assertEqual(
            transport.exact_reads,
            [("kinoko34077/devflow", 16)],
        )

    def test_workflow_keeps_read_only_audit_permissions(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("contents: read", text)
        self.assertIn("issues: read", text)
        self.assertIn("pull-requests: read", text)
        audit_job = text.split("  audit:", 1)[1].split(
            "  publish:", 1
        )[0]
        self.assertNotIn("issues: write", audit_job)
        self.assertNotIn("pull-requests: write", audit_job)
        self.assertIn(
            "actions/checkout@"
            "3d3c42e5aac5ba805825da76410c181273ba90b1",
            text,
        )
        self.assertIn(
            "actions/setup-python@"
            "5fda3b95a4ea91299a34e894583c3862153e4b97",
            text,
        )
        self.assertIn("default: audit", text)
        self.assertIn("MAINTENANCE_AUDIT_TOKEN", text)
        self.assertIn(
            "maintenance-audit-report.json",
            text,
        )


    def test_collector_source_failure_classifies_as_needs_evidence(self):
        from tools import maintenance_audit as ma

        class Broken:
            def get_json(self, path):
                raise mg.GitHubReadError("unavailable")

        observation = mg.collect_repository(
            Broken(),
            "o/r",
            "kinoko34077/devflow#1",
            "2026-10-01T00:00:00Z",
        )
        report = ma.classify_repository(observation)
        self.assertEqual(report["disposition"], "NEEDS_EVIDENCE")
        self.assertIn(
            "SOURCE_UNAVAILABLE_OR_AMBIGUOUS",
            report["finding_classes"],
        )

    def test_duplicate_control_failure_classifies_as_needs_evidence(self):
        from tools import maintenance_audit as ma

        class NoReads:
            def get_json(self, path):
                raise AssertionError("must not read owner")

        observations = mg.collect_portfolio(
            NoReads(),
            [
                {
                    "repository": "o/r",
                    "control_ref": "kinoko34077/devflow#1",
                },
                {
                    "repository": "o/r",
                    "control_ref": "kinoko34077/devflow#2",
                },
            ],
            "2026-10-01T00:00:00Z",
        )
        reports = ma.classify_portfolio(observations)
        self.assertEqual(reports[0]["disposition"], "NEEDS_EVIDENCE")


    def test_audited_none_active_work_does_not_reactivate_historical_owner(self):
        from tools import maintenance_audit as ma

        body = (
            "## Repository\n\n`o/r`\n\n"
            "## Work Status\n\n`AUDITED`\n\n"
            "## Repository State\n\n`ACTIVE`\n\n"
            "## Active Work\n\n"
            "None. `o/r#9` was completed by PR #10 and main-verified.\n\n"
            "## Next Action\n\n"
            "`[WAIT] Resume only for a concrete new finding.`\n\n"
            "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->\n"
            '{"schema_version":1,"source_ref":"kinoko34077/devflow#1",'
            '"repository":"o/r","candidates":[]}\n'
            "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->\n"
        )

        class Transport:
            def __init__(self):
                self.paths = []

            def get_json(self, path):
                self.paths.append(path)
                if path.endswith("/issues/1"):
                    return {
                        "number": 1,
                        "title": "[REPO] r",
                        "state": "open",
                        "html_url": (
                            "https://github.com/kinoko34077/"
                            "devflow/issues/1"
                        ),
                        "body": body,
                        "author_association": "OWNER",
                        "updated_at": "2026-10-01T00:00:00Z",
                    }
                raise AssertionError(
                    "historical completed owner must not be fetched"
                )

        self.assertTrue(mg._explicit_no_active_work(body))
        self.assertEqual(
            mg._active_owner_ref(body, "o/r"),
            (None, False),
        )

        transport = Transport()
        observation = mg.collect_repository(
            transport,
            "o/r",
            "kinoko34077/devflow#1",
            "2026-10-01T00:05:00Z",
        )
        report = ma.classify_repository(observation)

        self.assertEqual(observation["source_status"], "OK")
        self.assertIsNone(
            observation["control"]["active_owner_ref"]
        )
        self.assertIsNone(observation["owner"]["ref"])
        self.assertEqual(report["disposition"], "NO_ACTION")
        self.assertIsNone(report["owner_ref"])
        self.assertEqual(
            report["reason_codes"],
            ["AUTHORITATIVE_SOURCES_CONSISTENT"],
        )
        self.assertEqual(
            transport.paths,
            ["/repos/kinoko34077/devflow/issues/1"],
        )


    def test_live_shape_reviewer_gate_yields_existing_owner(self):
        from tools import maintenance_audit as ma

        control_body = (
            "## Repository\n\n`kinoko34077/kinotch-repo-monitor`\n\n"
            "## Work Status\n\n`AWAITING_REVIEW`\n\n"
            "## Repository State\n\n`ACTIVE`\n\n"
            "## Active Work\n\n"
            "Owner `kinotch-repo-monitor#35` / PR #36 implements "
            "the bounded archive listener.\n\n"
            "## Next Action\n\n"
            "`[REVIEW] Obtain one fresh qualifying different-system/model "
            "Formal Review.`\n"
        )
        owner_body = (
            "## Work Status\n\n`AWAITING_REVIEW`\n\n"
            "## Current blocker\n\n"
            "`DIFFERENT_REVIEWER_REQUIRED` on current exact head.\n"
        )

        class Transport:
            def get_json(self, path):
                if path.endswith("/issues/59"):
                    return {
                        "number": 59,
                        "title": "[REPO] kinotch-repo-monitor",
                        "state": "open",
                        "html_url": (
                            "https://github.com/kinoko34077/"
                            "devflow/issues/59"
                        ),
                        "body": control_body,
                        "author_association": "OWNER",
                        "updated_at": "2026-09-30T02:06:31Z",
                    }
                if path.endswith("/issues/35"):
                    return {
                        "number": 35,
                        "state": "open",
                        "html_url": (
                            "https://github.com/kinoko34077/"
                            "kinotch-repo-monitor/issues/35"
                        ),
                        "body": owner_body,
                        "author_association": "OWNER",
                        "updated_at": "2026-09-30T00:00:00Z",
                    }
                raise AssertionError(path)

        observation = mg.collect_repository(
            Transport(),
            "kinoko34077/kinotch-repo-monitor",
            "kinoko34077/devflow#59",
            "2026-10-01T00:10:00Z",
        )
        report = ma.classify_repository(observation)

        self.assertEqual(
            observation["control"]["active_owner_ref"],
            "kinoko34077/kinotch-repo-monitor#35",
        )
        self.assertTrue(observation["reviewer_gate"])
        self.assertEqual(report["disposition"], "NEEDS_REVIEWER")
        self.assertIn(
            "REVIEW_GATE_YIELD",
            report["finding_classes"],
        )
        self.assertEqual(
            report["owner_ref"],
            "kinoko34077/kinotch-repo-monitor#35",
        )



class MaintenanceBootstrapDerivedTrustTests(unittest.TestCase):
    repository = "kinoko34077/BootstrapTrustFixture"
    request_ref = "kinoko34077/devflow#313"
    request_url = "https://github.com/kinoko34077/devflow/issues/313"

    def _request(self):
        payload = request_payload()
        payload["repository"] = {
            "owner": "kinoko34077",
            "name": "BootstrapTrustFixture",
            "description": "test",
            "visibility": "private",
        }
        return {
            "number": 313,
            "title": "[REPO CREATE] BootstrapTrustFixture",
            "repository_url": "https://api.github.com/repos/kinoko34077/devflow",
            "url": "https://api.github.com/repos/kinoko34077/devflow/issues/313",
            "html_url": self.request_url,
            "state": "open",
            "author_association": "OWNER",
            "body": issue_body(payload),
        }

    def _control(self, *, active_work="None."):
        return {
            "number": 314,
            "title": "[REPO] BootstrapTrustFixture",
            "repository_url": "https://api.github.com/repos/kinoko34077/devflow",
            "url": "https://api.github.com/repos/kinoko34077/devflow/issues/314",
            "html_url": "https://github.com/kinoko34077/devflow/issues/314",
            "state": "open",
            "author_association": "NONE",
            "updated_at": "2026-10-03T00:00:00Z",
            "body": (
                "## Repository\n\n"
                f"`{self.repository}`\n\n"
                "## Work Status\n\n`AUDITED`\n\n"
                "## Repository State\n\n`ACTIVE`\n\n"
                "## Active Work\n\n"
                f"{active_work}\n\n"
                "## Detailed Current State\n\n"
                f"Repository was initialized through `{self.request_ref}` "
                "using `repository-bootstrap.v1`. "
                "Accepted initial head is `" + ("a" * 40) + "`.\n\n"
                "## Control Notes\n\n"
                f"Cross-repository routing summary only. Bootstrap request: {self.request_url}. "
                f"Detailed technical truth belongs in `{self.repository}`.\n"
            ),
        }

    def _provenance(self):
        return json.dumps(
            {
                "schema": "repository-bootstrap-provenance.v1",
                "request_ref": self.request_ref,
                "request_url": self.request_url,
                "repository": self.repository,
            },
            indent=2,
            sort_keys=True,
        ) + "\n"

    def _done_comment(self):
        return {
            "body": (
                "Repository-Bootstrap-State: DONE\n"
                f"Repository: https://github.com/{self.repository}\n"
                "Initial-Accepted-SHA: `" + ("a" * 40) + "`\n"
                "Initial-Issue: https://github.com/kinoko34077/BootstrapTrustFixture/issues/1\n"
                "Repository-Control: https://github.com/kinoko34077/devflow/issues/314"
            ),
            "author_association": "NONE",
            "user": {"login": "github-actions[bot]"},
            "performed_via_github_app": {"slug": "github-actions"},
        }

    def _transport(self, *, active_work="None.", owner=None, comments=None):
        control = self._control(active_work=active_work)
        request = self._request()
        provenance = self._provenance()
        comments = [self._done_comment()] if comments is None else comments
        test_case = self

        class Transport:
            def get_json(inner_self, path):
                if path.endswith("/repos/kinoko34077/devflow/issues/314"):
                    return dict(control)
                if path.endswith("/repos/kinoko34077/devflow/issues/313"):
                    return dict(request)
                if owner is not None and path.endswith("/issues/7"):
                    return dict(owner)
                raise AssertionError(path)

            def list_issues(inner_self, repository, state="open"):
                test_case.assertEqual(repository, "kinoko34077/devflow")
                return [dict(control), dict(request)]

            def get_issue(inner_self, repository, number):
                if repository == "kinoko34077/devflow" and number == 313:
                    return dict(request)
                if repository == "kinoko34077/devflow" and number == 314:
                    return dict(control)
                if owner is not None and repository == test_case.repository and number == 7:
                    return dict(owner)
                raise AssertionError((repository, number))

            def list_issue_comments(inner_self, repository, number):
                test_case.assertEqual(
                    (repository, number),
                    ("kinoko34077/devflow", 313),
                )
                return list(comments)

            def get_file(inner_self, repository, path):
                test_case.assertEqual(
                    (repository, path),
                    (test_case.repository, ".github/repository-bootstrap.json"),
                )
                return {"content": provenance}

        return Transport()

    def test_bootstrap_derived_idle_control_is_trusted_by_maintenance_observation(self):
        observation = mg.collect_repository(
            self._transport(),
            self.repository,
            "kinoko34077/devflow#314",
            "2026-10-03T00:05:00Z",
        )

        self.assertEqual(observation["source_status"], "OK")
        self.assertTrue(observation["control"]["trusted"])
        self.assertIsNone(observation["owner"]["ref"])

    def test_bootstrap_derived_control_can_continue_to_exact_owner_classification(self):
        owner = {
            "number": 7,
            "state": "open",
            "repository_url": f"https://api.github.com/repos/{self.repository}",
            "html_url": f"https://github.com/{self.repository}/issues/7",
            "author_association": "OWNER",
            "updated_at": "2026-10-03T00:01:00Z",
            "body": "## Work Status\n\n`READY_FOR_IMPLEMENTATION`\n",
        }
        observation = mg.collect_repository(
            self._transport(
                active_work=f"`{self.repository}#7` — primary owner.",
                owner=owner,
            ),
            self.repository,
            "kinoko34077/devflow#314",
            "2026-10-03T00:05:00Z",
        )

        self.assertEqual(observation["source_status"], "OK")
        self.assertTrue(observation["control"]["trusted"])
        self.assertEqual(observation["owner"]["ref"], f"{self.repository}#7")
        self.assertTrue(observation["owner"]["runnable"])

    def test_arbitrary_bot_control_without_terminal_provenance_remains_untrusted(self):
        observation = mg.collect_repository(
            self._transport(comments=[]),
            self.repository,
            "kinoko34077/devflow#314",
            "2026-10-03T00:05:00Z",
        )

        self.assertEqual(observation["source_status"], "AMBIGUOUS")
        self.assertFalse(observation["control"]["trusted"])


class MaintenanceGitHubPreReviewHardeningTests(unittest.TestCase):
    def test_control_exact_issue_identity_is_required(self):
        class Transport:
            def __init__(self, issue):
                self.issue = issue

            def get_json(self, path):
                return dict(self.issue)

        base = {
            "number": 16,
            "title": "[REPO] example",
            "state": "open",
            "html_url": "https://github.com/kinoko34077/devflow/issues/16",
            "author_association": "OWNER",
            "body": (
                "## Repository\n\n"
                "`kinoko34077/example`\n\n"
                "## Active Work\n\n"
                "`kinoko34077/example#7`\n"
            ),
        }
        bad = (
            {**base, "number": 17},
            {**base, "title": "[REPO] other"},
            {**base, "state": "closed"},
            {**base, "pull_request": {"url": "x"}},
            {
                **base,
                "html_url": "https://github.com/kinoko34077/devflow/issues/99",
            },
        )
        for issue in bad:
            with self.subTest(issue=issue):
                observation = mg.collect_repository(
                    Transport(issue),
                    "kinoko34077/example",
                    "kinoko34077/devflow#16",
                    "2026-10-01T00:00:00Z",
                )
                self.assertEqual(
                    observation["source_status"],
                    "UNAVAILABLE",
                )

    def test_owner_exact_issue_identity_is_required(self):
        class Transport:
            def get_json(self, path):
                if path.endswith("/issues/16"):
                    return {
                        "number": 16,
                        "title": "[REPO] example",
                        "state": "open",
                        "html_url": (
                            "https://github.com/kinoko34077/"
                            "devflow/issues/16"
                        ),
                        "author_association": "OWNER",
                        "body": (
                            "## Repository\n\n"
                            "`kinoko34077/example`\n\n"
                            "## Active Work\n\n"
                            "`kinoko34077/example#7`\n"
                        ),
                    }
                if path.endswith("/issues/7"):
                    return {
                        "number": 8,
                        "state": "open",
                        "html_url": (
                            "https://github.com/kinoko34077/"
                            "example/issues/8"
                        ),
                        "author_association": "OWNER",
                        "body": (
                            "## Work Status\n\n"
                            "`READY_FOR_IMPLEMENTATION`\n"
                        ),
                    }
                raise AssertionError(path)

        observation = mg.collect_repository(
            Transport(),
            "kinoko34077/example",
            "kinoko34077/devflow#16",
            "2026-10-01T00:00:00Z",
        )
        self.assertEqual(
            observation["source_status"],
            "UNAVAILABLE",
        )

    def test_malformed_candidate_projection_is_not_treated_as_absent(self):
        class Transport:
            def __init__(self):
                self.owner_reads = 0

            def get_json(self, path):
                if path.endswith("/issues/16"):
                    return {
                        "number": 16,
                        "title": "[REPO] example",
                        "state": "open",
                        "html_url": (
                            "https://github.com/kinoko34077/"
                            "devflow/issues/16"
                        ),
                        "author_association": "OWNER",
                        "body": (
                            "## Repository\n\n"
                            "`kinoko34077/example`\n\n"
                            "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->\n"
                            "{not-json}\n"
                            "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->\n\n"
                            "## Active Work\n\n"
                            "`kinoko34077/example#7`\n"
                        ),
                    }
                self.owner_reads += 1
                raise AssertionError(
                    "malformed candidate source must fail before owner read"
                )

        transport = Transport()
        observation = mg.collect_repository(
            transport,
            "kinoko34077/example",
            "kinoko34077/devflow#16",
            "2026-10-01T00:00:00Z",
        )
        self.assertEqual(
            observation["source_status"],
            "UNAVAILABLE",
        )
        self.assertEqual(transport.owner_reads, 0)

    def test_action_portfolio_runs_deterministic_triage(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        portfolio_call = text.split(
            "python scripts/maintenance_audit.py portfolio",
            1,
        )[1]
        self.assertIn("--triage", portfolio_call)

    def test_targeted_cross_repository_audit_requires_cross_repo_token(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            '[[ "$AUDIT_REPOSITORY" == "kinoko34077/devflow" ]]',
            text,
        )
        self.assertIn(
            "--token-env MAINTENANCE_AUDIT_TOKEN",
            text,
        )
        self.assertIn(
            "--token-env GITHUB_TOKEN",
            text,
        )


    def test_transport_get_issue_rejects_mismatched_exact_identity(self):
        bad = {
            "number": 2,
            "state": "open",
            "html_url": "https://github.com/o/r/issues/2",
            "body": "x",
        }

        def opener(request, timeout=0):
            return FakeResponse(bad)

        transport = mg.GitHubReadTransport(
            "token",
            opener=opener,
        )
        with self.assertRaises(mg.GitHubReadError):
            transport.get_issue("o/r", 1)

    def test_untrusted_owner_fails_closed(self):
        class Transport:
            def get_json(self, path):
                if path.endswith("/issues/16"):
                    return {
                        "number": 16,
                        "title": "[REPO] example",
                        "state": "open",
                        "html_url": (
                            "https://github.com/kinoko34077/"
                            "devflow/issues/16"
                        ),
                        "author_association": "OWNER",
                        "body": (
                            "## Repository\n\n"
                            "`kinoko34077/example`\n\n"
                            "## Active Work\n\n"
                            "`kinoko34077/example#7`\n"
                        ),
                    }
                if path.endswith("/issues/7"):
                    return {
                        "number": 7,
                        "state": "closed",
                        "html_url": (
                            "https://github.com/kinoko34077/"
                            "example/issues/7"
                        ),
                        "author_association": "NONE",
                        "body": "## Work Status\n\n`DONE`\n",
                    }
                raise AssertionError(path)

        observation = mg.collect_repository(
            Transport(),
            "kinoko34077/example",
            "kinoko34077/devflow#16",
            "2026-10-01T00:00:00Z",
        )
        self.assertEqual(
            observation["source_status"],
            "UNAVAILABLE",
        )

    def test_control_human_gate_yields_needs_human(self):
        from tools import maintenance_audit as ma

        class Transport:
            def get_json(self, path):
                if path.endswith("/issues/16"):
                    return {
                        "number": 16,
                        "title": "[REPO] example",
                        "state": "open",
                        "html_url": (
                            "https://github.com/kinoko34077/"
                            "devflow/issues/16"
                        ),
                        "author_association": "OWNER",
                        "body": (
                            "## Repository\n\n"
                            "`kinoko34077/example`\n\n"
                            "## Active Work\n\n"
                            "`kinoko34077/example#7`\n\n"
                            "## Next Action\n\n"
                            "`[HUMAN_GATE] confirm permission`\n"
                        ),
                    }
                if path.endswith("/issues/7"):
                    return {
                        "number": 7,
                        "state": "closed",
                        "html_url": (
                            "https://github.com/kinoko34077/"
                            "example/issues/7"
                        ),
                        "author_association": "OWNER",
                        "body": "## Work Status\n\n`DONE`\n",
                    }
                raise AssertionError(path)

        observation = mg.collect_repository(
            Transport(),
            "kinoko34077/example",
            "kinoko34077/devflow#16",
            "2026-10-01T00:00:00Z",
        )
        self.assertTrue(observation["human_gate"])
        report = ma.classify_repository(observation)
        self.assertEqual(report["disposition"], "NEEDS_HUMAN")


    def test_audited_idle_control_human_gate_is_not_clean(self):
        from tools import maintenance_audit as ma

        body = (
            "## Repository\n\n`o/r`\n\n"
            "## Work Status\n\n`AUDITED`\n\n"
            "## Repository State\n\n`ACTIVE`\n\n"
            "## Active Work\n\n"
            "None.\n\n"
            "## Next Action\n\n"
            "`[HUMAN_GATE] await explicit decision`\n\n"
            "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->\n"
            '{"schema_version":1,'
            '"source_ref":"kinoko34077/devflow#1",'
            '"repository":"o/r","candidates":[]}\n'
            "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->\n"
        )

        class Transport:
            def get_json(self, path):
                if path.endswith("/issues/1"):
                    return {
                        "number": 1,
                        "title": "[REPO] r",
                        "state": "open",
                        "html_url": (
                            "https://github.com/kinoko34077/"
                            "devflow/issues/1"
                        ),
                        "body": body,
                        "author_association": "OWNER",
                    }
                raise AssertionError(path)

        observation = mg.collect_repository(
            Transport(),
            "o/r",
            "kinoko34077/devflow#1",
            "2026-10-01T00:00:00Z",
        )
        self.assertTrue(observation["human_gate"])
        self.assertEqual(
            ma.classify_repository(observation)["disposition"],
            "NEEDS_HUMAN",
        )


class MaintenanceGitHubP6PilotRegressionTests(unittest.TestCase):
    def test_no_active_phrase_does_not_resurrect_completed_owner(self):
        from tools import maintenance_audit as ma

        body = (
            "## Repository\n\n`kinoko34077/example`\n\n"
            "## Work Status\n\n`AUDITED`\n\n"
            "## Active Work\n\n"
            "No active `devflow#153` repair remains for this repository.\n\n"
            "Completed:\n"
            "- `example#5` / PR #10 — historical completed repair.\n\n"
            "## Next Action\n\n"
            "`[WAIT] Re-audit when state changes.`\n"
        )

        class Transport:
            def __init__(self):
                self.owner_reads = 0

            def get_json(self, path):
                if path.endswith("/issues/16"):
                    return {
                        "number": 16,
                        "title": "[REPO] example",
                        "state": "open",
                        "html_url": (
                            "https://github.com/kinoko34077/"
                            "devflow/issues/16"
                        ),
                        "body": body,
                        "author_association": "OWNER",
                    }
                self.owner_reads += 1
                raise AssertionError(
                    "historical Completed owner must not be re-read as active"
                )

        transport = Transport()
        observation = mg.collect_repository(
            transport,
            "kinoko34077/example",
            "kinoko34077/devflow#16",
            "2026-10-01T08:42:21Z",
        )
        self.assertEqual(transport.owner_reads, 0)
        self.assertEqual(observation["source_status"], "OK")
        self.assertIsNone(observation["control"]["active_owner_ref"])
        self.assertEqual(observation["owner"]["state"], "NONE")
        self.assertEqual(
            ma.classify_repository(observation)["disposition"],
            "NO_ACTION",
        )

    def test_wait_none_control_is_valid_intentional_idle(self):
        from tools import maintenance_audit as ma

        body = (
            "## Repository\n\n`kinoko34077/example`\n\n"
            "## Work Status\n\n`WAIT`\n\n"
            "## Active Work\n\nNone.\n\n"
            "## Next Action\n\n"
            "`[WAIT] No active repository-local implementation.`\n"
        )

        class Transport:
            def get_json(self, path):
                if path.endswith("/issues/16"):
                    return {
                        "number": 16,
                        "title": "[REPO] example",
                        "state": "open",
                        "html_url": (
                            "https://github.com/kinoko34077/"
                            "devflow/issues/16"
                        ),
                        "body": body,
                        "author_association": "OWNER",
                    }
                raise AssertionError(path)

        observation = mg.collect_repository(
            Transport(),
            "kinoko34077/example",
            "kinoko34077/devflow#16",
            "2026-10-01T08:42:21Z",
        )
        self.assertEqual(observation["source_status"], "OK")
        self.assertEqual(observation["owner"]["state"], "NONE")
        self.assertEqual(
            ma.classify_repository(observation)["disposition"],
            "NO_ACTION",
        )


if __name__ == "__main__":
    unittest.main()
