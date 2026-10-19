"""Fake-only contracts for native GET-only SMC coverage observation."""
import unittest
from pathlib import Path

from tools.maintenance_coverage_github import (
    CoverageCollectionError, collect_repository_coverage,
)
from tools.maintenance_ledger import RunRecord, render_run_comment

REPO = "kinoko34077/devflow"
LEDGER = 367
FP = "sha256:" + "a" * 64
LEDGER_URL = f"https://github.com/{REPO}/issues/{LEDGER}"
API_ISSUE = f"https://api.github.com/repos/{REPO}/issues/{LEDGER}"
BASELINE = Path("docs/spec/maintenance/common-baseline.v1.yaml").read_text(encoding="utf-8")
CATALOG = Path(".devflow/maintenance.yaml").read_text(encoding="utf-8")


def record(result="CLEAN", **changes):
    fields = dict(
        repository=REPO,
        run_id=f"audit:{REPO}:common.correctness:1",
        slot_id="common.correctness",
        generation=1,
        lens="correctness",
        depth="STANDARD",
        fingerprint=FP,
        result=result,
        findings_summary="bounded audit",
        completed_at="2026-10-07T00:00:00Z",
        next_eligibility_reason=None,
        evidence_refs=(LEDGER_URL,),
    )
    fields.update(changes)
    return RunRecord(**fields)


def comment(result="CLEAN", author="OWNER", **record_changes):
    return {
        "id": 123,
        "html_url": LEDGER_URL + "#issuecomment-123",
        "issue_url": API_ISSUE,
        "author_association": author,
        "body": render_run_comment(record(result, **record_changes)),
    }


class FakeGET:
    def __init__(self, comments=None):
        self.calls = []
        self.baseline = BASELINE
        self.catalog = CATALOG
        self.issue = {
            "number": LEDGER,
            "title": "[MAINTENANCE] Audit Ledger",
            "state": "open",
            "html_url": LEDGER_URL,
            "body": f"## Repository\n\n`{REPO}`\n\n## Work Status\n\n`AUDITED`\n",
        }
        self.comments = [] if comments is None else comments

    def get_file(self, repository, path, ref=None):
        self.calls.append(("file", repository, path, ref))
        if repository == REPO and path == ".devflow/maintenance.yaml":
            return {"content": self.catalog, "sha": "a" * 40}
        if repository == REPO and path == "docs/spec/maintenance/common-baseline.v1.yaml":
            return {"content": self.baseline, "sha": "b" * 40}
        raise AssertionError("Unexpected file source")

    def get_issue(self, repository, number):
        self.calls.append(("issue", repository, number))
        return self.issue

    def list_issue_comments(self, repository, number):
        self.calls.append(("comments", repository, number))
        return self.comments


def observe(fake, fingerprints=None):
    return collect_repository_coverage(
        fake, REPO, LEDGER,
        {REPO + "::common.correctness": FP} if fingerprints is None else fingerprints,
    )


def correct_row(value):
    return next(row for row in value.rows if row.slot_id == "common.correctness" and row.depth == "STANDARD")


class NativeCoverageCollectorTests(unittest.TestCase):
    def test_real_shared_schema_fake_comment_from_exact_owner(self):
        fake = FakeGET([comment()])
        observed = observe(fake)
        self.assertEqual(1, observed.comments_scanned)
        self.assertEqual(1, observed.machine_records)
        self.assertEqual(1, observed.substantive_legacy_records)
        self.assertEqual(0, observed.noncredit_records)
        self.assertEqual("a" * 40, observed.catalog_blob_sha)
        self.assertEqual("LEGACY_SCOPE_UNBOUND", correct_row(observed).status)
        self.assertTrue(all(name in ("file", "issue", "comments") for name, *_ in fake.calls))

    def test_empty_history_is_not_run(self):
        value = observe(FakeGET())
        self.assertEqual(0, value.machine_records)
        self.assertEqual("NOT_RUN", correct_row(value).status)

    def test_blocked_and_superseded_are_zero_credit(self):
        for result in ("BLOCKED", "SUPERSEDED", "NEEDS_REAUDIT"):
            with self.subTest(result=result):
                value = observe(FakeGET([comment(result=result)]))
                self.assertEqual(1, value.noncredit_records)
                self.assertEqual(0, value.substantive_legacy_records)
                self.assertEqual("NO_COVERAGE", correct_row(value).status)

    def test_unknown_source_fingerprint_never_credits_current_scope(self):
        value = observe(FakeGET([comment()]), fingerprints={})
        self.assertEqual("UNKNOWN_FINGERPRINT", correct_row(value).status)

    def test_untrusted_author_is_preserved_as_untrusted_not_accepted(self):
        value = observe(FakeGET([comment(author="CONTRIBUTOR")]))
        self.assertEqual("UNTRUSTED", correct_row(value).status)
        self.assertEqual(1, value.machine_records)
        self.assertEqual(1, value.untrusted_records)
        self.assertEqual(0, value.substantive_legacy_records)
        self.assertEqual(0, value.noncredit_records)

    def test_source_issue_not_same_ledger_fails_closed(self):
        item = comment()
        item["html_url"] = f"https://github.com/{REPO}/issues/1#issuecomment-123"
        with self.assertRaisesRegex(CoverageCollectionError, "does not belong"):
            observe(FakeGET([item]))

    def test_same_html_but_other_api_issue_is_rejected(self):
        item = comment()
        item["issue_url"] = f"https://api.github.com/repos/{REPO}/issues/88"
        with self.assertRaisesRegex(CoverageCollectionError, "does not belong"):
            observe(FakeGET([item]))

    def test_missing_author_association_fails_closed(self):
        item = comment()
        item.pop("author_association")
        with self.assertRaisesRegex(CoverageCollectionError, "association"):
            observe(FakeGET([item]))

    def test_malformed_machine_comment_fails_entire_snapshot(self):
        item = comment()
        item["body"] = "<!-- devflow-maintenance-run:v1 -->\ninvalid-json"
        with self.assertRaisesRegex(CoverageCollectionError, "malformed"):
            observe(FakeGET([item]))

    def test_duplicate_favorable_v1_result_fails_entire_ledger_projection(self):
        item = comment(result="CLEAN")
        item["body"] = item["body"].replace(
            '"result":"CLEAN"',
            '"result":"BLOCKED","result":"CLEAN"',
            1,
        )
        with self.assertRaisesRegex(CoverageCollectionError, "malformed machine"):
            observe(FakeGET([item]))

    def test_nonmachine_comment_is_ignored_not_counted(self):
        value = observe(FakeGET([{"body": "normal maintenance note"}]))
        self.assertEqual(0, value.machine_records)
        self.assertEqual(1, value.comments_scanned)

    def test_wrong_or_closed_issue_fails_closed(self):
        for key, changed in (("title", "Other"), ("state", "closed"), ("number", 999)):
            with self.subTest(key=key):
                fake = FakeGET()
                fake.issue[key] = changed
                with self.assertRaises(CoverageCollectionError):
                    observe(fake)

    def test_mismatched_repo_identity_in_body_fails(self):
        fake = FakeGET()
        fake.issue["body"] = "## Repository\n\n`kinoko34077/other`\n"
        with self.assertRaisesRegex(CoverageCollectionError, "heading"):
            observe(fake)

    def test_missing_catalog_fails_closed_instead_of_guessing_defaults(self):
        fake = FakeGET()
        fake.catalog = None
        with self.assertRaises(CoverageCollectionError):
            observe(fake)

    def test_repo_catalog_identity_mismatch_fails(self):
        fake = FakeGET()
        fake.catalog = CATALOG.replace(REPO, "kinoko34077/other", 1)
        with self.assertRaisesRegex(CoverageCollectionError, "catalog identity"):
            observe(fake)

    def test_comment_pagination_failure_propagates(self):
        class FailPages(FakeGET):
            def list_issue_comments(self, repository, number):
                raise RuntimeError("page 2 HTTP 403")
        with self.assertRaisesRegex(RuntimeError, "403"):
            observe(FailPages())

    def test_invalid_ledger_active_state_never_returns_partial_rows(self):
        fake = FakeGET()
        fake.issue["body"] = fake.issue["body"].replace("`AUDITED`", "`READY_FOR_IMPLEMENTATION`")
        with self.assertRaisesRegex(CoverageCollectionError, "active-run"):
            observe(fake)

    def test_foreign_record_repo_rejected(self):
        item = comment(repository="kinoko34077/other", run_id="audit:kinoko34077/other:common.correctness:1")
        with self.assertRaisesRegex(CoverageCollectionError, "identity invalid"):
            observe(FakeGET([item]))

    def test_duplicate_invalid_deep_data_does_not_fabricate_deep(self):
        observed = observe(FakeGET([comment()]))
        deep = next(row for row in observed.rows if row.slot_id == "common.correctness" and row.depth == "DEEP")
        self.assertEqual("NOT_RUN", deep.status)


def v2_comment(*, result="CLEAN", author="OWNER", digest_override=None, scope=None):
    from tools.maintenance_catalog import (
        Scope, canonical_catalog_digest, parse_common_baseline_text,
        parse_repository_catalog_text,
    )
    from tools.maintenance_run_attestation import (
        AttestedRun, render_attested_run_comment,
    )
    baseline = parse_common_baseline_text(BASELINE)
    catalog = parse_repository_catalog_text(CATALOG, baseline)
    digest = canonical_catalog_digest(baseline, catalog)
    obj = AttestedRun(
        record=record(result=result),
        scope=scope if scope is not None else Scope("repository", "."),
        coverage_key="common.correctness",
        catalog_digest=digest_override or digest,
    )
    entry = comment(result=result, author=author)
    entry["body"] = render_attested_run_comment(obj)
    return entry


class DualVersionGitHubCollectorTests(unittest.TestCase):
    def test_legacy_and_v2_readers_run_without_writing_issues(self):
        fake = FakeGET([v2_comment()])
        obs = observe(fake)
        self.assertEqual(1, obs.attested_records)
        self.assertEqual(1, obs.substantive_legacy_records)
        self.assertEqual("ATTESTED_SCOPE_MATCH", correct_row(obs).status)
        self.assertFalse(any(call[0] in ("write", "post", "patch") for call in fake.calls))

    def test_signed_looking_but_untrusted_v2_is_not_a_completed_audit(self):
        obs = observe(FakeGET([v2_comment(author="CONTRIBUTOR")]))
        self.assertEqual("UNTRUSTED", correct_row(obs).status)
        self.assertEqual(0, obs.substantive_legacy_records)
        self.assertEqual(1, obs.untrusted_records)

    def test_v2_observed_catalog_digest_mismatch_is_not_scope_coverage(self):
        obs = observe(FakeGET([v2_comment(digest_override="sha256:" + "f" * 64)]))
        self.assertEqual("CATALOG_DRIFT", correct_row(obs).status)

    def test_v2_wrong_scope_is_rejected_as_current_scope_proof(self):
        from tools.maintenance_catalog import Scope
        obs = observe(FakeGET([v2_comment(scope=Scope("component", "moved"))]))
        self.assertEqual("SCOPE_DRIFT", correct_row(obs).status)

    def test_mixed_duplicate_run_id_is_ambiguous_not_complete(self):
        obs = observe(FakeGET([comment(), v2_comment()]))
        self.assertEqual("AMBIGUOUS_HISTORY", correct_row(obs).status)

    def test_malformed_v2_or_both_sentinels_fail_closed(self):
        for body in ("<!-- devflow-maintenance-run:v2 --> not-json",
                     v2_comment()["body"] + "\n<!-- devflow-maintenance-run:v1 -->"):
            with self.subTest(length=len(body)):
                item = v2_comment()
                item["body"] = body
                with self.assertRaises(CoverageCollectionError):
                    observe(FakeGET([item]))


if __name__ == "__main__":
    unittest.main()
