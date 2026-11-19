from __future__ import annotations

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import re
import sys
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import bootstrap_token_probe as probe  # noqa: E402


class FakeResponse:
    def __init__(self, body: object, *, status: int = 200, headers: dict[str, str] | None = None):
        self.status = status
        self.headers = headers or {}
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


class BootstrapTokenProbeTests(unittest.TestCase):
    def test_uses_only_fixed_read_only_endpoints_and_reports_safe_identity(self):
        responses = [
            FakeResponse(
                {"id": 79015263, "login": "kinoko34077", "token": "must-not-log"},
                headers={"X-GitHub-Request-Id": "ABCD:12345:6ABC:DEADBEEF"},
            ),
            FakeResponse(
                {"required_status_checks": {"secret-like-field": "must-not-log"}},
                headers={"X-GitHub-Request-Id": "BCDE:12345:7ABC:CAFEBABE"},
            ),
        ]
        requests = []

        def opener(request, *, timeout):
            requests.append((request, timeout))
            return responses.pop(0)

        report = probe.run_probe(
            "github_pat_sensitive_value",
            opener=opener,
            now=datetime(2026, 11, 19, tzinfo=timezone.utc),
            run_id="12345",
        )

        self.assertEqual(
            [probe.USER_ENDPOINT, probe.PROTECTED_MAIN_ENDPOINT],
            [request.full_url for request, _ in requests],
        )
        self.assertEqual(["GET", "GET"], [request.get_method() for request, _ in requests])
        self.assertTrue(all(timeout == probe.REQUEST_TIMEOUT_SECONDS for _, timeout in requests))
        self.assertTrue(
            all(
                request.get_header("Authorization") == "Bearer github_pat_sensitive_value"
                for request, _ in requests
            )
        )
        self.assertTrue(report["principal_matches_expected"])
        self.assertEqual("success", report["protected_main_read"]["classification"])
        self.assertEqual("BCDE:12345:7ABC:CAFEBABE", report["protected_main_read"]["request_id"])
        self.assertEqual("12345", report["run_id"])

        serialized = json.dumps(report)
        self.assertNotIn("github_pat_sensitive_value", serialized)
        self.assertNotIn("must-not-log", serialized)
        self.assertNotIn("required_status_checks", serialized)

    def test_missing_token_fails_before_network_access(self):
        called = False

        def opener(*_args, **_kwargs):
            nonlocal called
            called = True
            raise AssertionError("network access is not allowed for a missing token")

        with self.assertRaisesRegex(probe.ProbeInputError, "credential is missing"):
            probe.run_probe("", opener=opener)
        self.assertFalse(called)

    def test_unexpected_principal_stops_before_admin_read(self):
        calls = []

        def opener(request, *, timeout):
            calls.append(request.full_url)
            return FakeResponse({"id": 1, "login": "someone-else"})

        report = probe.run_probe("candidate", opener=opener)

        self.assertFalse(report["principal_matches_expected"])
        self.assertEqual(1, len(calls))
        self.assertEqual("not_run", report["protected_main_read"]["classification"])

    def test_admin_read_failure_does_not_pass_probe(self):
        responses = [FakeResponse({"id": 79015263, "login": "kinoko34077"})]

        def opener(request, *, timeout):
            if request.full_url == probe.USER_ENDPOINT:
                return responses.pop(0)
            raise HTTPError(request.full_url, 403, "denied", {}, BytesIO(b"private details"))

        report = probe.run_probe("candidate", opener=opener)

        self.assertTrue(report["principal_matches_expected"])
        self.assertEqual("PROTECTED_MAIN_READ_FAILED", report["result"])
        self.assertEqual(
            "forbidden_or_rate_limited",
            report["protected_main_read"]["classification"],
        )

    def test_error_body_and_token_are_never_emitted(self):
        token = "github_pat_sensitive_value"

        def opener(request, *, timeout):
            raise HTTPError(
                request.full_url,
                403,
                "forbidden with github_pat_sensitive_value",
                {"X-GitHub-Request-Id": "safe-request"},
                BytesIO(b"raw error body github_pat_sensitive_value"),
            )

        output = []
        with patch.dict("os.environ", {"REPOSITORY_BOOTSTRAP_TOKEN": token, "GITHUB_RUN_ID": "67890"}):
            exit_code = probe.main(opener=opener, write=output.append)

        serialized = "".join(output)
        self.assertEqual(1, exit_code)
        self.assertIn('"classification": "forbidden_or_rate_limited"', serialized)
        self.assertIn('"status": 403', serialized)
        self.assertNotIn(token, serialized)
        self.assertNotIn("raw error body", serialized)
        self.assertNotIn("forbidden with", serialized)

    def test_request_id_is_allowlisted_before_reporting(self):
        def opener(request, *, timeout):
            return FakeResponse(
                {"id": 79015263, "login": "kinoko34077"},
                headers={"X-GitHub-Request-Id": "unsafe\nsecret"},
            )

        report = probe.run_probe("candidate", opener=opener)

        self.assertIsNone(report["user_read"]["request_id"])

    def test_default_transport_rejects_redirect_without_forwarding_bearer(self):
        received: dict[str, list[tuple[str, str | None]]] = {"origin": [], "target": []}
        target = ThreadingHTTPServer(("127.0.0.1", 0), None)
        target_port = target.server_address[1]

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                name = "origin" if self.server is origin else "target"
                received[name].append((self.path, self.headers.get("Authorization")))
                if name == "origin":
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{target_port}/collect")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()

            def log_message(self, *_args):
                return

        origin = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        target.RequestHandlerClass = Handler
        target_thread = Thread(target=target.serve_forever, daemon=True)
        origin_thread = Thread(target=origin.serve_forever, daemon=True)
        target_thread.start()
        origin_thread.start()
        try:
            _payload, result = probe._get_json(
                f"http://127.0.0.1:{origin.server_address[1]}/start",
                "sensitive-token",
                opener=probe._safe_urlopen,
            )

            self.assertEqual(result["status"], 302)
            self.assertEqual(result["classification"], "http_error")
            self.assertEqual(received["origin"], [("/start", "Bearer sensitive-token")])
            self.assertEqual(received["target"], [])
        finally:
            origin.shutdown()
            target.shutdown()
            origin.server_close()
            target.server_close()
            origin_thread.join(timeout=2)
            target_thread.join(timeout=2)

    def test_manual_workflow_is_main_actor_locked_and_read_only(self):
        workflow = (ROOT / ".github/workflows/repository-bootstrap-token-probe.yml").read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("github.repository == 'kinoko34077/devflow'", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("github.actor_id == '79015263'", workflow)
        self.assertIn("github.triggering_actor == github.actor", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("secrets.REPOSITORY_BOOTSTRAP_TOKEN", workflow)
        self.assertIn("python tools/bootstrap_token_probe.py", workflow)
        self.assertTrue((ROOT / "tools/bootstrap_token_probe.py").is_file())
        self.assertNotRegex(workflow, r"(?m)^\s*(?:contents|administration|issues|pull-requests):\s*(?:write|admin)\s*$")
        self.assertNotRegex(workflow, r"(?m)^\s*(?:pull_request_target|schedule|push):")
        refs = re.findall(r"uses:\s*[^@\s]+@([^\s#]+)", workflow)
        self.assertTrue(refs)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in refs))

    def test_specs_explain_secret_visibility_and_correlation_limits(self):
        spec = (ROOT / "docs/spec/REPOSITORY_BOOTSTRAP.md").read_text(encoding="utf-8")
        runbook = (ROOT / "docs/operations/REPOSITORY_BOOTSTRAP.md").read_text(encoding="utf-8")

        self.assertIn("does not prove the saved secret has the same value", spec)
        self.assertIn("relative display may be too coarse to correlate a run", spec)
        self.assertIn("does not reveal the saved value", runbook)
        self.assertIn("mathematical value comparison", runbook)
        self.assertIn("unchanged relative label provides no correlation", runbook)


if __name__ == "__main__":
    unittest.main()
