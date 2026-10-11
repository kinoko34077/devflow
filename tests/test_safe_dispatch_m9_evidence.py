"""Adversarial synthetic-only tests for M9 dispatch/run identity shapes."""
from dataclasses import replace
import unittest

from tools.safe_dispatch_m9_evidence import (
    M9OfflinePin, inspect_dispatch_response, inspect_run_metadata,
)

SHA = "a" * 40


def pin():
    return M9OfflinePin(
        repository_id=314, repository="kinoko34077/example",
        workflow_id=71, workflow_path=".github/workflows/approved.yml",
        ref="refs/tags/m9-protected-v1", head_sha=SHA,
    )


def response(run_id=123):
    return {
        "workflow_run_id": run_id,
        "run_url": f"https://api.github.com/repos/kinoko34077/example/actions/runs/{run_id}",
        "html_url": f"https://github.com/kinoko34077/example/actions/runs/{run_id}",
    }


def run(run_id=123):
    return {
        "id": run_id, "workflow_id": 71, "event": "workflow_dispatch",
        "repository": {"id": 314, "full_name": "kinoko34077/example"},
        "head_sha": SHA, "head_branch": "m9-protected-v1",
        "path": ".github/workflows/approved.yml",
        "run_attempt": 1,
        "url": f"https://api.github.com/repos/kinoko34077/example/actions/runs/{run_id}",
        "html_url": f"https://github.com/kinoko34077/example/actions/runs/{run_id}",
    }


class OfflineM9EvidenceTests(unittest.TestCase):
    def assert_response_denied(self, obj, *, status=200):
        result = inspect_dispatch_response(pin(), http_status=status, response=obj)
        self.assertNotEqual(result.status, "OFFLINE_RESPONSE_SHAPE_MATCHED")
        self.assertIsNone(result.run_id)
        self.assertNotIn(result.status, ("ADMITTED", "EXECUTED", "READ_VERIFIED"))

    def assert_run_denied(self, obj, *, expected_id=123):
        result = inspect_run_metadata(pin(), expected_run_id=expected_id, run=obj)
        self.assertEqual(result.status, "BLOCKED")
        self.assertIsNone(result.run_id)
        self.assertNotIn(result.status, ("ADMITTED", "EXECUTED", "READ_VERIFIED"))

    def test_response_shape_not_a_dispatch(self):
        result = inspect_dispatch_response(pin(), http_status=200, response=response())
        self.assertEqual(result.status, "OFFLINE_RESPONSE_SHAPE_MATCHED")
        self.assertEqual(result.reason, "NOT_AUTHENTICATED_NOT_DISPATCHED")
        self.assertEqual(result.run_id, 123)

    def test_run_shape_not_executed(self):
        result = inspect_run_metadata(pin(), expected_run_id=123, run=run())
        self.assertEqual(result.status, "OFFLINE_RUN_METADATA_MATCHED")
        self.assertEqual(result.reason, "NOT_AUTHENTICATED_NOT_EXECUTED")

    def test_204_timeout_5xx_and_auth_fail_are_ambiguous(self):
        for status in (204, 0, 401, 403, 500, 502, "200", True, None):
            x = inspect_dispatch_response(pin(), http_status=status, response=response())
            self.assertEqual(x.status, "DISPATCH_OUTCOME_UNKNOWN")
            self.assertIsNone(x.run_id)

    def test_invalid_response_objects(self):
        for candidate in (None, [], "x", {}, {"workflow_run_id": 123},
                          dict(response(), extra=True)):
            self.assert_response_denied(candidate)

    def test_boolean_string_negative_and_overflow_ids(self):
        for bad in (True, False, "123", 0, -1, 2**63, None, 1.0):
            obj = response()
            obj["workflow_run_id"] = bad
            self.assert_response_denied(obj)

    def test_dispatch_response_url_attack_rejected(self):
        attack_urls = (
            "http://api.github.com/repos/kinoko34077/example/actions/runs/123",
            "https://api.github.com.evil.test/repos/kinoko34077/example/actions/runs/123",
            "https://api.github.com@evil.test/repos/kinoko34077/example/actions/runs/123",
            "https://api.github.com/repos/kinoko34077/example/actions/runs/123?q=1",
            "https://api.github.com/repos/kinoko34077/example/actions/runs/%31%32%33",
            "https://api.github.com/repos/another/repo/actions/runs/123",
        )
        for target in attack_urls:
            candidate = response()
            candidate["run_url"] = target
            self.assert_response_denied(candidate)
        candidate = response()
        candidate["html_url"] = "https://github.com/kinoko34077/example/actions/runs/124"
        self.assert_response_denied(candidate)

    def test_expected_pin_validation(self):
        for patch in (
            {"repository_id": True}, {"repository_id": -1}, {"workflow_id": False},
            {"head_sha": SHA.upper()}, {"workflow_path": "../workflow.yml"},
            {"workflow_path": ".github/workflows/evil.sh"},
            {"ref": "refs/heads/a/../main"}, {"ref": "refs/tags/unsafe.lock"},
            {"repository": "other/repo"}, {"ref": "a" * 40},
        ):
            bad = replace(pin(), **patch)
            d = inspect_dispatch_response(bad, http_status=200, response=response())
            if patch == {"repository": "other/repo"}:
                self.assertEqual(d.status, "DISPATCH_OUTCOME_UNKNOWN")
            else:
                self.assertEqual(d.status, "BLOCKED")
            self.assertIsNone(d.run_id)

    def test_metadata_repository_identity(self):
        for repo in ({"id": 315, "full_name": "kinoko34077/example"},
                     {"id": True, "full_name": "kinoko34077/example"},
                     {"id": 314, "full_name": "kinoko34077/renamed"},
                     {"id": 314}, {}, None):
            item = run()
            item["repository"] = repo
            self.assert_run_denied(item)

    def test_metadata_wrong_workflow_and_run_id(self):
        for key, value in (("id", True), ("id", 124), ("workflow_id", True),
                           ("workflow_id", 72), ("workflow_id", "71")):
            item = run()
            item[key] = value
            self.assert_run_denied(item)
        self.assert_run_denied(run(124))

    def test_metadata_wrong_event_and_sha(self):
        for key, value in (("event", "pull_request"),
                           ("event", "repository_dispatch"),
                           ("event", None), ("head_sha", "b"*40),
                           ("head_sha", None)):
            item = run()
            item[key] = value
            self.assert_run_denied(item)

    def test_metadata_wrong_path_or_ref(self):
        for key, value in (("path", ".github/workflows/other.yml"),\n                           ("path", ".github/workflows/approved.yml@refs/tags/m9-protected-v1"),
                           ("path", ".github/workflows/approved.yml@refs/heads/main"),
                           ("head_branch", "main"), ("head_branch", None)):
            item = run()
            item[key] = value
            self.assert_run_denied(item)

    def test_metadata_unsafe_url_and_attempt(self):
        for key, value in (("url", "https://api.github.com/repos/other/repo/actions/runs/123"),
                           ("html_url", "https://github.com/kinoko34077/example/actions/runs/123?view=1"),
                           ("run_attempt", 0), ("run_attempt", True), ("run_attempt", "1"),\n                           ("run_attempt", 2), ("run_attempt", 3)):
            item = run()
            item[key] = value
            self.assert_run_denied(item)

    def test_real_github_workflow_dispatch_path_is_plain_file(self):
        # Live public workflow_dispatch run GET (devflow run 38118114901)
        # returns path without "@ref"; reject old incorrect shape.
        item = run()
        self.assertEqual(item["path"], ".github/workflows/approved.yml")
        result = inspect_run_metadata(pin(), expected_run_id=123, run=item)
        self.assertEqual(result.status, "OFFLINE_RUN_METADATA_MATCHED")
        item["path"] += "@refs/tags/m9-protected-v1"
        self.assert_run_denied(item)

    def test_rerun_attempt_is_not_initial_dispatch_evidence(self):
        item = run()
        item["run_attempt"] = 2
        self.assert_run_denied(item)
        item["run_attempt"] = 1
        self.assertEqual(inspect_run_metadata(pin(), expected_run_id=123, run=item).status,
                         "OFFLINE_RUN_METADATA_MATCHED")

    def test_concurrent_run_id_cross_binding(self):
        first = inspect_dispatch_response(pin(), http_status=200, response=response(123))
        second = inspect_dispatch_response(pin(), http_status=200, response=response(124))
        self.assertNotEqual(first.run_id, second.run_id)
        self.assert_run_denied(run(124), expected_id=123)
        self.assert_run_denied(run(123), expected_id=124)

    def test_no_run_object_or_wrong_expected_id(self):
        for data in (None, [], "hello", {}):
            self.assert_run_denied(data)
        for rid in (True, False, -1, 0, "123", None):
            self.assert_run_denied(run(), expected_id=rid)


if __name__ == "__main__":
    unittest.main()
