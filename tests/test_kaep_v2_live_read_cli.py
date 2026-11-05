"""Approved public KAEP v2 #789 read integration; GET-only/no agent authority."""
from __future__ import annotations
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from tools.kaep_discovery_reader import main
from tools.kaep_route_notice import DISCOVERY_REPOSITORY, DISCOVERY_ISSUE


def pages(*groups):
    return json.dumps(list(groups))


class LiveV2ReadCLITests(unittest.TestCase):
    def _run(self, *extra, page_values=None):
        args = ["--expect-notice-actor", "kinoko34077",
                "--expect-source-actor", "kinoko34077", *extra]
        values = page_values if page_values is not None else [pages([])]
        with patch("tools.kaep_discovery_reader.fetch_gh_pages",
                   side_effect=values) as gh, redirect_stdout(io.StringIO()) as out:
            result = main(args)
        return result, json.loads(out.getvalue()), gh

    def test_default_still_reads_legacy_503(self):
        status, result, gh = self._run()
        self.assertEqual(status, 0)
        self.assertEqual(result["status"], "READ_ONLY")
        gh.assert_called_once_with(DISCOVERY_REPOSITORY, DISCOVERY_ISSUE)

    def test_successor_789_get_reads_approved_locator(self):
        status, result, gh = self._run("--index-issue", "789")
        self.assertEqual(status, 0)
        self.assertEqual(result["status"], "READ_ONLY")
        self.assertEqual(result["hints"], [])
        self.assertFalse(result["peer_identity_verified"])
        gh.assert_called_once_with(DISCOVERY_REPOSITORY, 789)

    def test_successor_shadow_is_bounded_not_absence_of_work(self):
        status, result, gh = self._run("--index-issue", "789", "--shadow-all")
        self.assertEqual(status, 0)
        self.assertEqual(result["status"], "INDEX_EXHAUSTED_SOURCE_VERIFIED_ONLY")
        self.assertTrue(result["read_only"])
        gh.assert_called_once_with(DISCOVERY_REPOSITORY, 789)

    def test_dual_shadow_reports_invalid_legacy_and_empty_v2_as_unknown(self):
        fence = chr(96) * 3
        bad = {"id": 1,
               "body": "<!-- kaep:message:v0.2 -->\n" + fence + "json\n{}\n" + fence + "\n",
               "user": {"login": "kinoko34077", "id": 79015263}}
        status, result, gh = self._run(
            "--dual-shadow", page_values=[pages([bad]), pages([])])
        self.assertEqual(status, 2)
        self.assertEqual(result["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(result["index_status"]["legacy"],
                         "INDEX_EXHAUSTED_WITH_REJECTIONS")
        self.assertEqual(result["index_status"]["successor"],
                         "INDEX_EXHAUSTED_SOURCE_VERIFIED_ONLY")
        self.assertEqual(result["index_diagnostics"]["legacy"]["rejected"][0]["reason_code"],
                         "INVALID_WRAPPER")
        self.assertEqual(result["source_verified_roots"], [])
        self.assertTrue(result["has_unknown_work"])
        for key in ("complete_source_universe", "recipient_pickup_proven",
                    "can_authorize_execution", "fallback_retirement_authorized",
                    "index_migration_approved"):
            self.assertFalse(result[key])
        self.assertEqual([c.args for c in gh.call_args_list],
                         [(DISCOVERY_REPOSITORY, DISCOVERY_ISSUE),
                          (DISCOVERY_REPOSITORY, 789)])

    def test_dual_shadow_empty_both_is_still_bounded(self):
        status, result, gh = self._run(
            "--dual-shadow", page_values=[pages([]), pages([])])
        self.assertEqual(status, 0)
        self.assertEqual(result["status"], "BOUNDED_DUAL_INDEX_READ")
        self.assertEqual(result["source_verified_roots"], [])
        self.assertTrue(result["has_unknown_work"])
        self.assertFalse(result["index_migration_approved"])
        self.assertEqual(gh.call_count, 2)

    def test_unapproved_index_denied_before_get(self):
        for bad in ("9001", "0", "-1"):
            with self.subTest(bad=bad):
                status, result, gh = self._run("--index-issue", bad,
                                               page_values=[])
                self.assertEqual(status, 2)
                self.assertEqual(result["status"], "BLOCKED")
                self.assertEqual(result["reason_code"], "DISCOVERY_INDEX_NOT_APPROVED")
                gh.assert_not_called()

    def test_invalid_dual_parameter_combo_denied_before_get(self):
        for flags in (("--dual-shadow", "--index-issue", "789"),
                      ("--dual-shadow", "--after-id", "7"),
                      ("--dual-shadow", "--shadow-all")):
            with self.subTest(flags=flags):
                status, result, gh = self._run(*flags, page_values=[])
                self.assertEqual(status, 2)
                self.assertEqual(result["reason_code"], "INVALID_DUAL_INDEX_ARGUMENTS")
                gh.assert_not_called()

    def test_read_failure_does_not_claim_empty_queue(self):
        status, result, gh = self._run("--index-issue", "789",
                                       page_values=[OSError("no v2 egress")])
        self.assertEqual(status, 2)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason_code"], "DISCOVERY_IO_FAILED")
        self.assertNotIn("no v2 egress", json.dumps(result))
        gh.assert_called_once()


if __name__ == "__main__":
    unittest.main()
