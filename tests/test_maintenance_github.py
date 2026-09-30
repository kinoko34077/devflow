import io
import json
import unittest
from urllib.error import HTTPError
from pathlib import Path

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

    def test_manual_workflow_is_read_only_and_unscheduled(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("schedule:", text)
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


if __name__ == "__main__":
    unittest.main()
