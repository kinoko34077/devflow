"""B6 candidate ledger: untrusted locator visibility distinct from root authority."""
from __future__ import annotations

import unittest

from tools.kaep_live_union_cli import _build_source_candidate_ledger

REPO = "kinoko34077/devflow"


class CandidateLedgerResponsibilitiesTests(unittest.TestCase):
    def _ledger(self, sources, rows=(), errors=(), *, indexed=(), recent=(), markers=()):
        return _build_source_candidate_ledger(
            [(REPO, n) for n in sources],
            verified_rows=[{"repository": REPO, "issue_number": n} for n in rows],
            source_errors=list(errors),
            indexed_sources={(REPO, n) for n in indexed},
            recent_sources={(REPO, n) for n in recent},
            marker_in_scope={(REPO, n) for n in markers},
        )

    def test_empty_recipient_still_reports_all_candidates_with_origin_and_error(self):
        failed = {"owning_issue": f"https://github.com/{REPO}/issues/12",
                  "reason_code": "SOURCE_READ_UNAVAILABLE"}
        found = self._ledger(
            [11, 12, 13], rows=[11, 11], errors=[failed],
            indexed=[11], recent=[11, 12], markers=[13],
        )
        self.assertEqual([row["issue_number"] for row in found], [11, 12, 13])
        self.assertEqual([row["origin"] for row in found],
                         ["BOTH", "LATEST_COMMENT_SOURCE",
                          "INCREMENTAL_MARKER_SOURCE"])
        self.assertEqual([row["matching_recipient_roots"] for row in found],
                         [2, 0, 0])
        self.assertEqual([row["source_observation"] for row in found], [
            "ACCEPTED_RECIPIENT_ROOTS",
            "SOURCE_VALIDATION_UNKNOWN",
            "NO_ACCEPTED_RECIPIENT_ROOT_OBSERVED",
        ])
        self.assertEqual(found[2]["incremental_marker_observed"], True)
        for row in found:
            self.assertEqual(set(row), {
                "repository", "issue_number", "issue_url",
                "incremental_marker_observed", "origin",
                "matching_recipient_roots", "source_observation",
                "grants_work_authority",
            })
            self.assertIs(row["grants_work_authority"], False)

    def test_global_unknown_blocks_clean_candidate_claims(self):
        found = self._ledger(
            [11, 12], rows=[11],
            errors=[{"reason_code": "CANDIDATE_LIMIT"}],
            indexed=[11],
        )
        self.assertEqual([x["source_observation"] for x in found],
                         ["SOURCE_VALIDATION_UNKNOWN"] * 2)
        self.assertFalse(any(x["grants_work_authority"] for x in found))

    def test_previous_report_and_invalid_error_object_remain_unknown(self):
        found = self._ledger([33], errors=[None])
        self.assertEqual(found[0]["origin"], "PREVIOUS_REPORT_SOURCE")
        self.assertEqual(found[0]["matching_recipient_roots"], 0)
        self.assertEqual(found[0]["source_observation"], "SOURCE_VALIDATION_UNKNOWN")
        self.assertFalse(found[0]["grants_work_authority"])


if __name__ == "__main__":
    unittest.main()
