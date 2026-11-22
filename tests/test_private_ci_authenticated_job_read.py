"""Synthetic, non-effectful evidence matrix for #752 authenticated reader."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import unittest
from urllib.error import HTTPError

from tools.private_ci_authenticated_job_read import observe_github_job_launch_once

OWNER = "fixture-owner"
REPO = OWNER + "/private-fixture"
RUN_ID = 123456
JOB_ID = 987654
SHA = "a" * 40
NOW = datetime(2026, 10, 20, 5, 18, tzinfo=timezone.utc)
ROOT = "https://api.github.com"
BASE = "/repos/" + REPO
MESSAGE = (
    "The job was not started because recent account payments have failed "
    "or your spending limit needs to be increased."
)


def valid_resources():
    return {
        "/user": {"login": OWNER, "id": 11},
        BASE: {
            "full_name": REPO, "private": True, "id": 22,
            "owner": {"login": OWNER, "id": 11},
        },
        BASE + f"/actions/runs/{RUN_ID}": {
            "id": RUN_ID, "head_sha": SHA, "status": "completed",
            "conclusion": "failure", "repository": {"id": 22},
        },
        BASE + f"/actions/jobs/{JOB_ID}": {
            "id": JOB_ID, "run_id": RUN_ID, "head_sha": SHA,
            "status": "completed", "conclusion": "failure",
            "runner_id": None, "runner_name": None, "steps": [],
            "completed_at": "2026-10-20T05:15:30Z",
            "check_run_url": ROOT + BASE + f"/check-runs/{JOB_ID}",
        },
        BASE + f"/check-runs/{JOB_ID}": {
            "id": JOB_ID, "head_sha": SHA,
            "status": "completed", "conclusion": "failure",
            "app": {"slug": "github-actions"},
            "output": {"annotations_count": 2},
        },
        BASE + f"/check-runs/{JOB_ID}/annotations?per_page=100&page=1": [
            {"message": MESSAGE + " See billing settings."},
            {"message": "The job was not started."},
        ],
    }


class Response:
    status = 200
    def __init__(self, url: str, payload: object, *, redirected: bool = False):
        self.url = url if not redirected else "https://attacker.invalid/host"
        self.stream = BytesIO(json.dumps(payload).encode())

    def geturl(self):
        return self.url

    def read(self, n):
        return self.stream.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stream.close()


class FakeOpener:
    """Only synthetic bytes. Never authenticates a real GitHub principal."""
    def __init__(self, resources=None, *, failing=None, redirected=None):
        self.resources = valid_resources() if resources is None else resources
        self.failing = failing
        self.redirected = redirected
        self.calls = []

    def open(self, request, timeout):
        url = request.full_url
        self.calls.append(request)
        if self.failing == url:
            raise HTTPError(url, 403, "forbidden", {}, None)
        if not (url.startswith(ROOT + "/") and request.get_method() == "GET"
                and timeout == 10):
            raise AssertionError("UNEXPECTED_NETWORK_TARGET")
        if url not in {ROOT + key for key in self.resources}:
            raise AssertionError("UNEXPECTED_API_PATH")
        return Response(url, self.resources[url[len(ROOT):]], redirected=url == self.redirected)


def observe(opener, **change):
    values = dict(
        account=OWNER, repository=REPO, run_id=RUN_ID, job_id=JOB_ID,
        expected_head_sha=SHA, now_utc=NOW,
        token="synthetic-token-never-log", opener=opener,
    )
    values.update(change)
    return observe_github_job_launch_once(**values)


class AuthenticatedJobReadTests(unittest.TestCase):
    def test_exact_private_unstarted_billing_job_is_plan_only(self):
        fake = FakeOpener()
        result = observe(fake)
        self.assertEqual((result.status, result.action),
                         ("PLAN_ONLY", "RECORD_BILLING_BLOCK"))
        self.assertEqual(result.requests_attempted, 6)
        self.assertIs(result.verified_for_dispatch, False)
        self.assertEqual(result.receipt.job_id, JOB_ID)
        self.assertIs(result.receipt.authenticated_github_read, True)
        self.assertNotIn("synthetic-token", repr(result))
        self.assertNotIn("See billing settings", repr(result))
        self.assertTrue(all(
            x.get_method() == "GET" and x.get_header("Authorization") == "Bearer synthetic-token-never-log"
            for x in fake.calls
        ))

    def test_invalid_request_cannot_initiate_network(self):
        cases = (
            {"account": "outside"},
            {"repository": "../x"},
            {"repository": "another/private-fixture"},
            {"repository": "fixture-owner/../x"},
            {"run_id": True},
            {"run_id": 0},
            {"job_id": "1"},
            {"expected_head_sha": "invalid"},
            {"now_utc": NOW.replace(tzinfo=None)},
            {"token": ""},
            {"token": "with spaces"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                fake = FakeOpener()
                result = observe(fake, **overrides)
                self.assertEqual(result.reason, "INVALID_PINNED_READ_CONTEXT")
                self.assertEqual(len(fake.calls), 0)

    def test_all_six_sources_must_agree(self):
        cases = [
            ("/user", "login", "different", "GITHUB_OWNER_IDENTITY_NOT_VERIFIED"),
            ("/user", "id", 99, "GITHUB_PRIVATE_OWNER_NOT_VERIFIED"),
            (BASE, "private", False, "GITHUB_PRIVATE_OWNER_NOT_VERIFIED"),
            (BASE, "full_name", "other/repo", "GITHUB_PRIVATE_OWNER_NOT_VERIFIED"),
            (BASE + f"/actions/runs/{RUN_ID}", "head_sha", "b"*40, "GITHUB_WORKFLOW_RUN_NOT_VERIFIED"),
            (BASE + f"/actions/runs/{RUN_ID}", "status", "queued", "GITHUB_WORKFLOW_RUN_NOT_VERIFIED"),
            (BASE + f"/actions/jobs/{JOB_ID}", "run_id", RUN_ID + 1, "GITHUB_UNSTARTED_JOB_NOT_VERIFIED"),
            (BASE + f"/actions/jobs/{JOB_ID}", "runner_name", "runner1", "GITHUB_UNSTARTED_JOB_NOT_VERIFIED"),
            (BASE + f"/actions/jobs/{JOB_ID}", "steps", [{"name": "test"}], "GITHUB_UNSTARTED_JOB_NOT_VERIFIED"),
            (BASE + f"/actions/jobs/{JOB_ID}", "conclusion", "success", "GITHUB_UNSTARTED_JOB_NOT_VERIFIED"),
            (BASE + f"/check-runs/{JOB_ID}", "head_sha", "c"*40, "GITHUB_CHECK_RUN_NOT_VERIFIED"),
            (BASE + f"/check-runs/{JOB_ID}", "app", {"slug":"other-app"}, "GITHUB_CHECK_RUN_NOT_VERIFIED"),
        ]
        for path, key, value, expected in cases:
            with self.subTest(path=path, key=key):
                data = valid_resources()
                data[path][key] = value
                result = observe(FakeOpener(data))
                self.assertEqual((result.status, result.reason), ("HOLD", expected))
                self.assertIsNone(result.receipt)

    def test_missing_runner_fields_are_not_unassigned_runner(self):
        for missing in ("runner_name", "runner_id"):
            with self.subTest(missing=missing):
                data = valid_resources()
                del data[BASE + f"/actions/jobs/{JOB_ID}"][missing]
                result = observe(FakeOpener(data))
                self.assertEqual(result.status, "HOLD")
                self.assertEqual(result.reason, "GITHUB_UNSTARTED_JOB_NOT_VERIFIED")
                self.assertIsNone(result.receipt)

    def test_check_annotations_must_match_exact_unique_evidence(self):
        for annotation_list in (
            [],
            [{"message": "Tests failed"}, {"message": "Build failed"}],
            [{"message": MESSAGE}, {"message": MESSAGE}],
            [{"message": MESSAGE}],
        ):
            with self.subTest(ann=annotation_list):
                data = valid_resources()
                data[BASE + f"/check-runs/{JOB_ID}/annotations?per_page=100&page=1"] = annotation_list
                r = observe(FakeOpener(data))
                self.assertEqual(r.status, "HOLD")
                self.assertIsNone(r.receipt)

    def test_check_run_incomplete_pagination_is_hold(self):
        data = valid_resources()
        data[BASE + f"/check-runs/{JOB_ID}"]["output"]["annotations_count"] = 100
        self.assertEqual(observe(FakeOpener(data)).reason, "GITHUB_CHECK_RUN_NOT_VERIFIED")

    def test_historical_or_future_job_is_hold(self):
        for clock in (NOW + timedelta(hours=25), NOW - timedelta(minutes=4)):
            r = observe(FakeOpener(), now_utc=clock)
            self.assertEqual(r.status, "HOLD")
            self.assertIsNone(r.receipt)

    def test_http_403_and_redirect_are_never_proof(self):
        path = ROOT + "/user"
        for fake in (FakeOpener(failing=path), FakeOpener(redirected=path)):
            r = observe(fake)
            self.assertEqual(r.status, "HOLD")
            self.assertIsNone(r.receipt)
            self.assertIn(r.reason, {
                "GITHUB_AUTH_OR_ACCESS_UNAVAILABLE", "GITHUB_RESPONSE_ORIGIN_NOT_VERIFIED"
            })

    def test_owner_pinned_on_read_not_caller_assumed(self):
        data = valid_resources()
        data[BASE]["owner"]["id"] = 12
        r = observe(FakeOpener(data))
        self.assertEqual(r.reason, "GITHUB_PRIVATE_OWNER_NOT_VERIFIED")
        self.assertFalse(r.verified_for_dispatch)


if __name__ == "__main__":
    unittest.main()
