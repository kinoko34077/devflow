"""Fail-closed operator coverage table: no inferred all-repo audit credit."""
import unittest
from unittest.mock import patch

from scripts import maintenance_coverage_report as cli
from tools.maintenance_coverage import CoverageRow
from tools.maintenance_coverage_github import CoverageObservation
from tools.maintenance_coverage_report import (
    build_coverage_report, render_coverage_markdown,
)

REPO = "kinoko34077/devflow"
FP = "sha256:" + "a"*64


def observed(repository=REPO, *, status="NOT_RUN", evidence=None):
    row = CoverageRow(
        repository=repository, slot_id="common.correctness",
        scope_kind="repository", scope_selector=".", coverage_key="common.correctness",
        lens="correctness", depth="STANDARD", current_fingerprint=FP,
        status=status, reason="derived, not trusted as execution",
        run_id=None, completed_at=None, evidence_url=evidence,
    )
    return CoverageObservation(
        repository=repository, ledger_issue_number=367, catalog_blob_sha="a"*40,
        comments_scanned=1, machine_records=1, attested_records=0,
        substantive_legacy_records=0, noncredit_records=1,
        untrusted_records=0, active_run_id=None, rows=(row,),
    )


class ReportRenderingTests(unittest.TestCase):
    def test_actual_missing_credit_stays_not_run(self):
        report = build_coverage_report([observed()])
        self.assertEqual(1, report["repository_count"])
        self.assertEqual({"NOT_RUN": 1}, report["coverage_state_counts"])
        self.assertIn("NOT_RUN", render_coverage_markdown(report))
        self.assertNotIn("CURRENT_VERIFIED", render_coverage_markdown(report))

    def test_attested_metadata_is_not_called_real_execution(self):
        report = build_coverage_report([observed(status="ATTESTED_SCOPE_MATCH")])
        text = render_coverage_markdown(report)
        self.assertIn("ATTESTED_SCOPE_MATCH", text)
        self.assertIn("監査内容そのものの完了証明ではありません", text)

    def test_stale_and_blocked_are_explicitly_counted(self):
        a = observed(status="NO_COVERAGE")
        b = observed(repository="kinoko34077/execution-coordinator", status="SOURCE_DRIFT")
        report = build_coverage_report([b, a])
        self.assertEqual({"NO_COVERAGE":1,"SOURCE_DRIFT":1}, report["coverage_state_counts"])
        self.assertEqual([REPO, "kinoko34077/execution-coordinator"],
                         [x["repository"] for x in report["repositories"]])

    def test_duplicate_repository_observations_fail(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_coverage_report([observed(), observed()])

    def test_cross_repo_coverage_row_is_never_attributed(self):
        obj = observed(repository="kinoko34077/execution-coordinator")
        wrong = CoverageObservation(**{
            **obj.__dict__, "repository": REPO
        })
        with self.assertRaisesRegex(ValueError, "source"):
            build_coverage_report([wrong])

    def test_markdown_escaping_of_untrusted_scope_is_not_a_table_break(self):
        obj = observed(evidence="https://github.com/example|other\ntext")
        report = build_coverage_report([obj])
        rendered = render_coverage_markdown(report)
        self.assertIn("example\\|other text", rendered)

    def test_empty_explicit_repo_set_is_observational_only(self):
        result = build_coverage_report([])
        self.assertEqual(0, result["row_count"])
        self.assertEqual([], result["rows"])

    def test_unknown_report_schema_rejected(self):
        with self.assertRaisesRegex(ValueError, "version"):
            render_coverage_markdown({"schema_version":"malicious"})


class NativeReadOnlyCliTests(unittest.TestCase):
    def test_only_three_existing_pilots_are_allowed(self):
        for text in ("kinoko34077/other#12", REPO+"#0", "invalid", REPO+"#oops"):
            with self.subTest(value=text), self.assertRaises(ValueError):
                cli._target(text)

    def test_no_silent_autodiscovery_or_double_count(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            cli.build_live_report(object(), [])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            cli.build_live_report(object(), [REPO+"#367", REPO+"#367"])

    def test_real_readonly_collector_uses_stable_exact_source_refs(self):
        slot = type("Slot", (), {
            "slot_id":"common.correctness",
            "external_freshness_class":"NORMAL",
            "scope":type("Scope", (), {"kind":"repository"})(),
        })()
        expected = (
            object(), object(), (slot,), "sha256:"+"b"*64, "c"*40,
            {"sha":"d"*40}, {"sha":"a"*40},
        )
        with (
            patch.object(cli, "_catalog_bundle", return_value=expected) as bundle,
            patch.object(cli, "collect_repository_coverage",
                         return_value=observed()) as collector,
        ):
            report = cli.build_live_report(object(), [REPO+"#367"])
        self.assertEqual(2, bundle.call_count)
        self.assertEqual(1, collector.call_count)
        self.assertEqual("NOT_RUN", report["rows"][0]["status"])

    def test_source_head_drift_aborts_whole_report(self):
        slot = type("Slot", (), {
            "slot_id":"common.correctness",
            "external_freshness_class":"NORMAL",
            "scope":type("Scope", (), {"kind":"repository"})(),
        })()
        first = (object(), object(), (slot,), "sha256:"+"b"*64,
                 "c"*40, {"sha":"d"*40}, {"sha":"a"*40})
        later = (object(), object(), (slot,), "sha256:"+"b"*64,
                 "f"*40, {"sha":"d"*40}, {"sha":"a"*40})
        with (
            patch.object(cli, "_catalog_bundle", side_effect=[first,later]),
            patch.object(cli, "collect_repository_coverage", return_value=observed()),
            self.assertRaisesRegex(ValueError, "source changed"),
        ):
            cli.build_live_report(object(), [REPO+"#367"])

    def test_missing_token_fails_without_source_report(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("sys.stderr"),
        ):
            self.assertEqual(2, cli.main(["--repo-ledger", REPO+"#367"]))


if __name__ == "__main__":
    unittest.main()
