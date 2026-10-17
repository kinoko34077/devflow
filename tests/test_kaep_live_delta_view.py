"""Live KAEP change-candidate GET: no Search, no writes, no false completeness."""
from __future__ import annotations

import io
import json
import subprocess
import unittest
from unittest import mock

from tools import kaep_live_delta_view as live
from tools.kaep_inbox_reader import InvalidMessage, MARKER

REPO = "kinoko34077/devflow"


def comment(number=576, cid=1234, body=None, actor="kinoko34077", repo=REPO):
    return {
        "id": cid, "body": body if body is not None else MARKER + " test",
        "issue_url": f"https://api.github.com/repos/{repo}/issues/{number}",
        "user": {"login": actor},
    }


def result(repositories, locators, **_kwargs):
    return {
        "schema_version": "kaep.search-list.v0.1",
        "status": "BOUNDED_SEARCH_READ",
        "observed_at": "2026-10-17T05:19:00+00:00",
        "repositories": repositories,
        "rows": [],
        "errors": [],
        "has_unknown_work": True,
        "complete_source_universe": False,
    }


class LiveDeltaTests(unittest.TestCase):
    def test_uses_request_time_updated_issue_comment_api_not_search(self):
        payload = [comment()]
        with mock.patch.object(live.subprocess, "run", return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(payload), stderr=""
        )) as run:
            got = live.read_repository_recent(REPO, since="2026-10-17T05:00:00Z")
        self.assertEqual(got, payload)
        args = run.call_args.args[0]
        self.assertEqual(args[0:3], ["gh", "api", "-H"])
        self.assertEqual(args[-1],
                         "/repos/kinoko34077/devflow/issues/comments?sort=updated&direction=desc&per_page=100&page=1&since=2026-10-17T05:00:00Z")
        self.assertNotIn("/search/issues", " ".join(args))
        for op in ("POST", "PATCH", "DELETE", "workflow_dispatch"):
            self.assertNotIn(op, " ".join(args))

    def test_selects_new_and_reply_comments_with_one_read_and_strict_original_validation(self):
        sources = [
            comment(number=576, cid=100, actor="github-actions[bot]"),
            comment(number=576, cid=99, actor="kinoko34077"),
            comment(number=610, cid=110, body="ordinary text"),
            comment(number=531, cid=111),
        ]
        with mock.patch.object(live.search, "build_search_list", side_effect=result) as validate:
            out = live.read_live_candidates(
                [REPO], recipient="claude-code", expected_actor="kinoko34077",
                recent_read=lambda repo, since=None: sources,
                issue_read=lambda *args: {}, comments_read=lambda *args: "[]")
        self.assertEqual(out["status"], "LIVE_WINDOW_READ")
        self.assertEqual(out["source_coverage"], "RECENT_COMMENT_WINDOW_NOT_COMPLETE")
        self.assertFalse(out["complete_source_universe"])
        self.assertTrue(out["has_unknown_work"])
        self.assertFalse(out["absence_of_work_proven"])
        self.assertFalse(out["can_authorize_execution"])
        self.assertTrue(out["requires_live_original_issue_revalidation"])
        kwargs = validate.call_args.kwargs
        self.assertEqual(kwargs["recipient"], "claude-code")
        self.assertEqual(kwargs["expected_actor"], "kinoko34077")
        sources_found = validate.call_args.args[1][REPO]["items"]
        self.assertEqual(
            [x["html_url"] for x in sources_found],
            ["https://github.com/kinoko34077/devflow/issues/576",
             "https://github.com/kinoko34077/devflow/issues/531"])
        self.assertEqual(len(sources_found), 2)

    def test_empty_latest_window_is_not_no_work_proof(self):
        with mock.patch.object(live.search, "build_search_list", side_effect=result):
            out = live.read_live_candidates(
                [REPO], recipient="codex", expected_actor="kinoko34077",
                recent_read=lambda *_a, **_k: [])
        self.assertEqual(out["status"], "LIVE_WINDOW_READ")
        self.assertEqual(out["searched_candidates"] if "searched_candidates" in out else 0, 0)
        self.assertTrue(out["has_unknown_work"])
        self.assertFalse(out["absence_of_work_proven"])

    def test_window_cap_is_partial_not_complete(self):
        with mock.patch.object(live.search, "build_search_list", side_effect=result):
            out = live.read_live_candidates(
                [REPO], recipient="chatgpt", expected_actor="kinoko34077",
                recent_read=lambda *_a, **_k:
                    [comment(number=576, cid=i + 1, body="ordinary")
                     for i in range(100)])
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["warnings"][0]["reason_code"], "RECENT_WINDOW_TRUNCATED")
        self.assertEqual(out["recent_comments_observed"][REPO], 100)

    def test_foreign_repo_and_invalid_json_and_invalid_since_block(self):
        with self.assertRaisesRegex(InvalidMessage, "LIVE_SOURCE_LOCATOR_MISMATCH"):
            live.read_live_candidates(
                [REPO], recipient="codex", expected_actor="kinoko34077",
                recent_read=lambda *_a, **_k: [comment(repo="notowner/devflow")])
        for bad in ("2026-10-17", "2026-99-17T05:00:00Z", "'; rm -rf", "2000-01-01T00:00:00Z"):
            with self.assertRaisesRegex(InvalidMessage, "INVALID_SINCE"):
                live.read_repository_recent(REPO, since=bad)
        with mock.patch.object(live.subprocess, "run", return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="{}", stderr="private diagnostic"
        )):
            with self.assertRaisesRegex(InvalidMessage, "LIVE_GITHUB_READ_FAILED"):
                live.read_repository_recent(REPO)

    def test_fails_closed_on_malformed_comment_and_filters(self):
        with self.assertRaisesRegex(InvalidMessage, "LIVE_INVALID_COMMENT"):
            live.read_live_candidates(
                [REPO], recipient="codex", expected_actor="kinoko34077",
                recent_read=lambda *_a, **_k: [{"body": MARKER + " x"}])
        with self.assertRaisesRegex(InvalidMessage, "INVALID_LIVE_FILTER"):
            live.read_live_candidates(
                [REPO, REPO], recipient="all", expected_actor="kinoko34077")
        with self.assertRaisesRegex(InvalidMessage, "INVALID_LIVE_FILTER"):
            live.read_live_candidates(
                [REPO], recipient="all", expected_actor="bad name")

    def test_cli_valid_read_zero_rc_and_errors_explicit_unknown(self):
        with (mock.patch.object(live, "read_live_candidates", return_value={
                "status": "LIVE_WINDOW_READ", "rows": [],
                "has_unknown_work": True, "complete_source_universe": False}),
              mock.patch("sys.stdout", new_callable=io.StringIO) as out):
            rc = live.main(["--repository", REPO, "--recipient", "codex"])
        self.assertEqual(rc, 0)
        self.assertTrue(json.loads(out.getvalue())["has_unknown_work"])

        with (mock.patch.object(live, "read_live_candidates",
                                side_effect=InvalidMessage("SOURCE_UNAVAILABLE")),
              mock.patch("sys.stdout", new_callable=io.StringIO) as out):
            rc = live.main(["--repository", REPO, "--recipient", "chatgpt"])
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(out.getvalue())["status"], "BLOCKED")
        self.assertEqual(json.loads(out.getvalue())["reason_code"], "SOURCE_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
