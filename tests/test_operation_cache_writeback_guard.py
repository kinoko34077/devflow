"""#487 second Public cache writer adopter, native shaped fake GET/PATCH guards.

No real GitHub mutations: injected GET and URL opener test the existing transport.
"""
from __future__ import annotations

import json
import unittest
from urllib.error import URLError

from scripts.repository_projection_cache import _IssueWriter
from tools.maintenance_sync_check import canonical_body_sha256

REPO = "kinoko34077/devflow"
TARGET = "kinoko34077/demo"
NUMBER = 7
UPDATED = "2026-10-04T05:49:00Z"
BEFORE = "## Repository\n\nkinoko34077/demo\n\n## Active Work\n\n- old\n"
AFTER = BEFORE.replace("- old", "- new")


class Response:
    def __init__(self, value):
        self.value = value
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps(self.value).encode("utf-8")


class NativeCacheWriter(_IssueWriter):
    def __init__(self):
        self.issue = {
            "number": NUMBER,
            "title": "[REPO] demo",
            "author_association": "OWNER",
            "state": "open",
            "updated_at": UPDATED,
            "body": BEFORE,
        }
        self.calls = []
        self.failure = False
        super().__init__("redact-me-secret", opener=self._fake_open)

    def get_issue(self, repo, number):
        self.calls.append(("GET", repo, number))
        return dict(self.issue)

    def _fake_open(self, request, timeout=0):
        self.calls.append(("PATCH", request.full_url, request.data))
        if self.failure:
            raise URLError("redact-me-secret transport-failed")
        return Response({"body": json.loads(request.data)["body"]})

    def update(self, *, body=AFTER, previous=BEFORE, updated_at=UPDATED,
               repo=REPO, number=NUMBER, target=TARGET, checker=None):
        return self.update_issue_body(
            repo, number, body,
            expected_body_sha256=canonical_body_sha256(previous),
            expected_updated_at=updated_at,
            expected_control_repository=target,
            trust_checker=checker or (
                lambda issue, expected:
                issue["author_association"] == "OWNER"
                and expected == TARGET
            ),
        )


class NativeWriterLastReadTests(unittest.TestCase):
    def test_one_get_one_patch_normal(self):
        writer = NativeCacheWriter()
        self.assertTrue(writer.update())
        self.assertEqual([x[0] for x in writer.calls], ["GET", "PATCH"])
        self.assertEqual(json.loads(writer.calls[1][2]), {"body": AFTER})

    def test_already_equal_skips_patch(self):
        writer = NativeCacheWriter()
        writer.issue["body"] = AFTER
        self.assertTrue(writer.update(body=AFTER, previous=AFTER))
        self.assertEqual([x[0] for x in writer.calls], ["GET"])

    def test_rejects_final_interleaving_body(self):
        writer = NativeCacheWriter()
        writer.issue["body"] = BEFORE + "interleaved\n"
        self.assertFalse(writer.update())
        self.assertEqual([x[0] for x in writer.calls], ["GET"])

    def test_rejects_same_body_new_revision(self):
        writer = NativeCacheWriter()
        writer.issue["updated_at"] = "2026-10-04T05:50:00Z"
        self.assertFalse(writer.update())
        self.assertEqual([x[0] for x in writer.calls], ["GET"])

    def test_rejects_changed_identity_and_open_state(self):
        for change in (
            {"title": "[REPO] wrong"},
            {"state": "closed"},
            {"number": 8},
            {"updated_at": "invalid"},
            {"author_association": "NONE"},
            {"body": None},
        ):
            with self.subTest(change=change):
                writer = NativeCacheWriter()
                writer.issue.update(change)
                self.assertFalse(writer.update())
                self.assertEqual([x[0] for x in writer.calls], ["GET"])

    def test_rejects_wrong_external_target(self):
        writer = NativeCacheWriter()
        self.assertFalse(writer.update(repo="kinoko34077/demo"))
        self.assertEqual(writer.calls, [])
        writer = NativeCacheWriter()
        self.assertFalse(writer.update(target="kinoko34077/other"))
        self.assertEqual([x[0] for x in writer.calls], ["GET"])

    def test_rejects_explicit_denial_by_shared_trust_verifier(self):
        writer = NativeCacheWriter()
        self.assertFalse(writer.update(checker=lambda issue, repo: False))
        self.assertEqual([x[0] for x in writer.calls], ["GET"])

    def test_failed_native_patch_is_not_success_and_token_is_redacted(self):
        writer = NativeCacheWriter()
        writer.failure = True
        with self.assertRaises(Exception) as ctx:
            writer.update()
        self.assertNotIn("redact-me-secret", str(ctx.exception))
        self.assertEqual([x[0] for x in writer.calls], ["GET", "PATCH"])


if __name__ == "__main__":
    unittest.main()
