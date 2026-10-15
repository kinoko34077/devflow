"""#487 M2: devflow Control write transport preflight, read-first/fail-closed.

All tests use injected GET/PATCH transport. Never a live GitHub write.
"""
from __future__ import annotations
import json
import unittest
from urllib.error import URLError
from scripts import maintenance_audit as cli
from tools.maintenance_sync_check import canonical_body_sha256

REPOSITORY = "kinoko34077/sample"
CONTROL_REPOSITORY = "kinoko34077/devflow"
REF = CONTROL_REPOSITORY + "#7"
BEFORE = (
    "## Repository\n\n" + chr(96) + REPOSITORY + chr(96) +
    "\n\n## Repository State\n\n" + chr(96) + "ACTIVE" + chr(96) + "\n\n"
    "## Active Work\n\n- old candidate\n\n"
)
AFTER = BEFORE.replace("- old candidate", "- reviewed candidate")


class Response:
    headers = {}
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class Transport(cli._SyncCheckGitHubTransport):
    def __init__(self):
        self.issue = {
            "number": 7,
            "title": "[REPO] sample",
            "author_association": "OWNER",
            "state": "open",
            "updated_at": "2026-10-16T00:00:00Z",
            "body": BEFORE,
        }
        self.patches = []
        self.failed = False
        super().__init__("test-github-token", opener=self._respond)

    def get_issue(self, repository, number):
        self.asserted_get = (repository, number)
        return dict(self.issue)

    def _respond(self, request, timeout=0):
        self.patches.append(request)
        if self.failed:
            raise URLError("test-github-token unavailable")
        payload = json.loads(request.data.decode("utf-8"))
        return Response({"body": payload["body"]})

    def run_update(self, after=AFTER, expected_body=None, repo=REPOSITORY,
                   ref=REF):
        if expected_body is None:
            expected_body = self.issue["body"]
        return self.update_control_body(
            repo, ref, canonical_body_sha256(expected_body), after
        )


class ExistingControlWriterIntegrationTests(unittest.TestCase):
    def test_trusted_last_get_calls_exactly_one_native_patch(self):
        t = Transport()
        self.assertTrue(t.run_update())
        self.assertEqual(t.asserted_get, (CONTROL_REPOSITORY, 7))
        self.assertEqual(len(t.patches), 1)
        req = t.patches[0]
        self.assertEqual(req.method, "PATCH")
        self.assertTrue(req.full_url.endswith("/repos/kinoko34077/devflow/issues/7"))
        self.assertEqual(json.loads(req.data.decode()), {"body": AFTER})

    def test_exact_noop_skips_patch(self):
        t = Transport()
        self.assertTrue(t.run_update(after=BEFORE))
        self.assertEqual(len(t.patches), 0)

    def test_old_digest_denies_without_effect(self):
        t = Transport()
        self.assertFalse(t.run_update(expected_body=BEFORE + "different"))
        self.assertEqual(len(t.patches), 0)

    def test_live_identity_and_permission_changes_fail_closed(self):
        variants = (
            {"number": 8}, {"number": True}, {"state": "closed"},
            {"title": "[REPO] other"}, {"author_association": "NONE"},
            {"author_association": "CONTRIBUTOR"},
            {"updated_at": "bad date"}, {"updated_at": None},
            {"body": BEFORE.replace(REPOSITORY, "kinoko34077/other")},
            {"body": None},
        )
        for fields in variants:
            with self.subTest(fields=fields):
                t = Transport()
                t.issue.update(fields)
                self.assertFalse(t.run_update(expected_body=BEFORE))
                self.assertEqual(len(t.patches), 0)

    def test_wrong_control_repository_and_requested_owner_ref_fail_closed(self):
        for repo, ref in (
            ("kinoko34077/other", REF),
            (REPOSITORY, "kinoko34077/other#7"),
        ):
            with self.subTest(repo=repo, ref=ref):
                t = Transport()
                self.assertFalse(t.run_update(repo=repo, ref=ref))
                self.assertEqual(len(t.patches), 0)

    def test_proposed_body_must_retain_canonical_repository(self):
        t = Transport()
        changed = AFTER.replace(REPOSITORY, "kinoko34077/other")
        self.assertFalse(t.run_update(after=changed))
        self.assertEqual(len(t.patches), 0)

    def test_failed_native_transport_does_not_claim_success_or_leak_token(self):
        t = Transport()
        t.failed = True
        with self.assertRaises(cli.GitHubReadError) as ctx:
            t.run_update()
        self.assertNotIn("test-github-token", str(ctx.exception))
        self.assertEqual(len(t.patches), 1)

    def test_shared_ledger_update_remains_separate(self):
        t = Transport()
        self.assertTrue(t.update_issue_body(
            CONTROL_REPOSITORY, 7, canonical_body_sha256(BEFORE), AFTER
        ))
        self.assertEqual(len(t.patches), 1)


if __name__ == "__main__":
    unittest.main()
