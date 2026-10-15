"""Read-only GitHub provenance bridge contracts for SMC coverage (M3)."""
from dataclasses import replace
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch

from tools import maintenance_github as gh
from tools.maintenance_catalog import ResolvedSlot, Scope
from tools.maintenance_coverage_github import collect_maintenance_coverage
from tools.maintenance_ledger import RunRecord, render_run_comment

REPO = "kinoko34077/example"
LEDGER_NO = 50
LEDGER_URL = f"https://github.com/{REPO}/issues/{LEDGER_NO}"
HEAD = "a" * 40
DIGEST = "sha256:" + "c" * 64
FINGERPRINT = gh.build_maintenance_fingerprint(HEAD, DIGEST, None)


def slot(**changes):
    data = dict(
        repository=REPO, slot_id="common.correctness", title="Correctness",
        lifecycle="ACTIVE", scope=Scope("repository", "."), lens="correctness",
        coverage_key="common.correctness", risk="MEDIUM",
        cadence_class="GENERAL", minimum_depth="STANDARD",
        external_freshness_class="NORMAL", description="test", source="common",
    )
    data.update(changes)
    return ResolvedSlot(**data)


def run(result="CLEAN"):
    return RunRecord(
        repository=REPO, run_id=f"audit:{REPO}:common.correctness:1",
        slot_id="common.correctness", generation=1, lens="correctness",
        depth="STANDARD", fingerprint=FINGERPRINT, result=result,
        findings_summary="none", completed_at="2026-10-15T08:00:00Z",
        next_eligibility_reason=None, evidence_refs=(LEDGER_URL,),
    )


def comment(record=None, association="OWNER", cid=123):
    return {
        "id": cid,
        "body": render_run_comment(record or run()),
        "author_association": association,
        "html_url": f"{LEDGER_URL}#issuecomment-{cid}",
    }


class StubGitHub:
    def __init__(self, comments=()):
        self.comments = list(comments)

    def get_issue(self, repository, number):
        if repository != REPO or number != LEDGER_NO:
            raise RuntimeError("not expected Ledger identity")
        return {
            "number": LEDGER_NO, "html_url": LEDGER_URL, "title": gh.MAINTENANCE_LEDGER_TITLE,
            "state": "open", "author_association": "OWNER",
            "body": "## Work Status\n\n`AUDITED`\n\n## Active Run\n\nNone.\n",
        }

    def list_issue_comments(self, repository, number):
        assert repository == REPO and number == LEDGER_NO
        return self.comments


class CoverageGitHubReadTests(TestCase):
    def collect(self, comments=(), local_slot=None, *, external_state=None):
        sl = slot() if local_slot is None else local_slot
        with patch.object(gh, "collect_maintenance_control", return_value={"status": "OK"}), \
             patch.object(gh, "_catalog_bundle", return_value=(
                 None, SimpleNamespace(rollout="PILOT"), (sl,),
                 DIGEST, HEAD, {"sha": "baseline-sha"}, {"sha": "catalog-sha"},
             )), \
             patch.object(gh, "find_maintenance_ledger", return_value=(
                 {"number": LEDGER_NO}, None,
             )):
            return collect_maintenance_coverage(
                StubGitHub(comments), REPO, "kinoko34077/devflow#123",
                external_state=external_state,
            )

    def test_live_exact_source_is_still_legacy_scope_unbound(self):
        value = self.collect([comment()])
        self.assertEqual("OK", value["status"])
        self.assertEqual(1, value["trusted_run_comments"])
        self.assertEqual("LEGACY_SCOPE_UNBOUND", value["rows"][0]["status"])
        self.assertEqual("NOT_RUN", value["rows"][1]["status"])
        self.assertEqual(1, value["coverage_status_counts"]["LEGACY_SCOPE_UNBOUND"])

    def test_aborted_live_provider_has_zero_coverage(self):
        value = self.collect([comment(run("BLOCKED"))])
        self.assertEqual("NO_COVERAGE", value["rows"][0]["status"])

    def test_untrusted_comment_never_promoted(self):
        value = self.collect([comment(association="CONTRIBUTOR")])
        self.assertEqual(0, value["trusted_run_comments"])
        self.assertEqual(1, value["ignored_untrusted_comments"])
        self.assertEqual("NOT_RUN", value["rows"][0]["status"])

    def test_malformed_trusted_comment_fails_closed(self):
        record = comment()
        record["body"] = "<!-- devflow-maintenance-run:v1 --> garbage"
        value = self.collect([record])
        self.assertEqual("NEEDS_EVIDENCE", value["status"])
        self.assertEqual("LEDGER_COMMENT_INVALID", value["reason_code"])
        self.assertEqual([], value["rows"])

    def test_comment_from_unrelated_issue_is_rejected(self):
        obj = comment()
        obj["html_url"] = f"https://github.com/{REPO}/issues/123#issuecomment-123"
        value = self.collect([obj])
        self.assertEqual("LEDGER_COMMENT_IDENTITY_INVALID", value["reason_code"])

    def test_fast_external_scope_requires_explicit_freshness_evidence(self):
        fast = slot(external_freshness_class="FAST")
        val = self.collect([comment()], fast)
        self.assertEqual("UNKNOWN_FINGERPRINT", val["rows"][0]["status"])
        val2 = self.collect([comment()], fast, external_state={})
        self.assertEqual("LEGACY_SCOPE_UNBOUND", val2["rows"][0]["status"])

    def test_unavailable_canonical_control_does_not_return_partial_rows(self):
        with patch.object(gh, "collect_maintenance_control",
                          return_value={"status": "NEEDS_EVIDENCE", "reason_code": "CONTROL_INVALID"}):
            value = collect_maintenance_coverage(StubGitHub(), REPO, "kinoko34077/devflow#123")
        self.assertEqual("CONTROL_NOT_TRUSTED", value["reason_code"])
        self.assertEqual([], value["rows"])

    def test_retired_slot_never_appears_in_live_view(self):
        obj = self.collect([comment()], slot(lifecycle="RETIRED"))
        self.assertEqual([], obj["rows"])


if __name__ == "__main__":
    main()
