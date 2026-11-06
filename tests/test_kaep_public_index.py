"""Public KAEP JSON is one safe candidate GET, never work authority."""
from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import kaep_issue_search_view as cli
from tools.kaep_public_index import to_public_index


def sample():
    return {
        "schema_version": "kaep.search-list.v0.1",
        "status": "PARTIAL_UNKNOWN",
        "observed_at": "2026-10-17T00:00:00+00:00",
        "repositories": ["kinoko34077/devflow"],
        "rows": [{
            "repository": "kinoko34077/devflow",
            "issue_number": 576,
            "issue_url": "https://github.com/kinoko34077/devflow/issues/576",
            "source_url": "https://github.com/kinoko34077/devflow/issues/576#issuecomment-6193914061",
            "source_comment_id": 6193914061,
            "issue_state": "open",
            "issue_role": "UNCLASSIFIED",
            "issue_type": None,
            "role_source": "UNCLASSIFIED",
            "recipient": "claude-code",
            "intent": "ANALYZE",
            "reply_observation": "UNVERIFIED_DUE_TO_SOURCE_QUARANTINE",
            "source_validation": "PARTIAL_UNKNOWN",
            "message_id": "kaep-abc",
            "head_freshness": "NOT_REVALIDATED",
            "title_hint": "unsafe title <script>hello</script>",
            "body": "NEVER EXPORT BODY",
            "GH_TOKEN": "NEVER EXPORT TOKEN",
        }],
        "errors": [{"reason_code": "QUARANTINED_INVALID_REF",
                    "owning_issue": "https://github.com/kinoko34077/devflow/issues/576",
                    "body": "SECRET MESSAGE"}],
        "has_unknown_work": True,
        "complete_source_universe": False,
        "can_authorize_execution": False,
        "fallback_retirement_authorized": False,
    }


class PublicIndexTests(unittest.TestCase):
    def test_allowlist_and_no_authority(self):
        d = to_public_index(sample())
        output = json.dumps(d, ensure_ascii=True)
        self.assertEqual(d["schema_version"], "kaep.public-source-index.v1")
        self.assertEqual(d["kind"], "NON_AUTHORITATIVE_CANDIDATE_SNAPSHOT")
        self.assertEqual(d["status"], "PARTIAL_UNKNOWN")
        self.assertTrue(d["has_unknown_work"])
        self.assertTrue(d["requires_live_original_issue_revalidation"])
        self.assertFalse(d["can_authorize_execution"])
        self.assertFalse(d["fallback_retirement_authorized"])
        self.assertFalse(d["complete_source_universe"])
        self.assertEqual(d["rows"][0]["issue_type"], "")
        self.assertEqual(len(d["rows"]), 1)
        for forbidden in ("NEVER EXPORT", "unsafe title", "SECRET MESSAGE", "GH_TOKEN"):
            self.assertNotIn(forbidden, output)

    def test_blocked_or_malformed_cannot_publish(self):
        x = sample()
        x["status"] = "BLOCKED"
        with self.assertRaisesRegex(ValueError, "BLOCKED"):
            to_public_index(x)
        x = sample()
        x["rows"][0]["source_url"] = "javascript:alert(1)"
        with self.assertRaisesRegex(ValueError, "INVALID_LOCATOR"):
            to_public_index(x)
        x = sample()
        x["errors"][0]["reason_code"] = "<html>"
        with self.assertRaisesRegex(ValueError, "INVALID_DIAGNOSTIC"):
            to_public_index(x)

    def test_cli_generates_html_and_json_from_one_read(self):
        data = sample()
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "index.json"
            with (mock.patch.object(cli, "search_repository", return_value={
                      "items": [], "total_count": 0, "incomplete_results": False}) as search,
                  mock.patch.object(cli, "build_search_list", return_value=data) as build,
                  mock.patch("sys.stdout", new_callable=io.StringIO) as stdout):
                rc = cli.main(["--repository", "kinoko34077/devflow",
                               "--expect-source-actor", "kinoko34077",
                               "--format", "html", "--public-json-out", str(dest)])
            self.assertEqual(rc, 2)
            self.assertEqual(search.call_count, 1)
            self.assertEqual(build.call_count, 1)
            self.assertIn("<!doctype html>", stdout.getvalue())
            d = json.loads(dest.read_text(encoding="ascii"))
            self.assertEqual(d["rows"][0]["source_comment_id"], 6193914061)
            self.assertEqual(d["status"], "PARTIAL_UNKNOWN")

    def test_cli_blocked_fails_closed_without_index(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "index.json"
            with (mock.patch.object(cli, "search_repository",
                                    side_effect=cli.InvalidMessage("SEARCH_FAILED")),
                  mock.patch("sys.stdout", new_callable=io.StringIO)):
                rc = cli.main(["--repository", "kinoko34077/devflow",
                               "--expect-source-actor", "kinoko34077",
                               "--format", "html", "--public-json-out", str(dest)])
            self.assertEqual(rc, 2)
            self.assertFalse(dest.exists())


if __name__ == "__main__":
    unittest.main()
