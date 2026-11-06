"""Offline SMC coverage table: escaping, integrity and mobile filter regressions."""
import re
import unittest
from unittest.mock import patch

from tests.test_maintenance_coverage_report import observed, REPO
from scripts import maintenance_coverage_report as cli
from tools.maintenance_coverage_report import build_coverage_report
from tools.maintenance_coverage_html import render_coverage_html


def page(*items):
    return render_coverage_html(build_coverage_report(list(items)))


class SMCOfflineHtmlTests(unittest.TestCase):
    def test_observed_three_pilots_can_render_as_local_html_without_fetch(self):
        sources = (
            observed(),
            observed(repository="kinoko34077/execution-coordinator", status="SOURCE_DRIFT"),
            observed(repository="kinoko34077/kinotch-repository-base", status="LEGACY_SCOPE_UNBOUND"),
        )
        html = page(*sources)
        for repo in (REPO, "kinoko34077/execution-coordinator",
                     "kinoko34077/kinotch-repository-base"):
            self.assertIn(repo, html)
        self.assertIn('data-repo="' + REPO + '"', html)
        self.assertIn('data-status="NOT_RUN"', html)
        self.assertIn('id="repository-filter"', html)
        self.assertIn('id="status-filter"', html)
        self.assertIn('role="status" aria-live="polite"', html)
        self.assertIn("max-width: 640px", html)
        self.assertIn('name="viewport"', html)

    def test_unknown_no_coverage_and_metadata_attestation_remain_explicit(self):
        result = page(
            observed(status="ATTESTED_SCOPE_MATCH"),
            observed(repository="kinoko34077/execution-coordinator",
                     status="NO_COVERAGE"),
        )
        self.assertIn("ATTESTED_SCOPE_MATCH", result)
        self.assertIn("NO_COVERAGE", result)
        self.assertIn("完了証明ではありません", result)
        self.assertNotIn("CURRENT_VERIFIED", result)

    def test_untrusted_scope_and_reason_never_become_html_or_script(self):
        obj = observed()
        item = obj.rows[0]
        row = type(item)(**{
            **item.__dict__,
            "scope_selector": '"><script>alert(1)</script>',
            "reason": "</style><img src=x onerror=alert(1)>",
        })
        changed = type(obj)(**{**obj.__dict__, "rows": (row,)})
        html = page(changed)
        self.assertNotIn('<script>alert(1)', html)
        self.assertNotIn('<img src=x', html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)
        self.assertNotIn('data-status=""', html)

    def test_arbitrary_source_url_is_text_not_a_link(self):
        url = 'javascript:alert(1)" onclick="alert(1)'
        html = page(observed(evidence=url))
        self.assertNotIn('href="javascript:', html)
        self.assertIn("javascript:alert(1)", html)
        self.assertIn("&quot;", html)

    def test_canonical_ledger_evidence_is_allowed_with_safe_rel(self):
        url = "https://github.com/kinoko34077/devflow/issues/367#issuecomment-567"
        html = page(observed(evidence=url))
        self.assertIn('href="' + url + '" rel="noopener noreferrer"', html)

    def test_forged_cross_repo_issue_link_not_navigable(self):
        url = "https://github.com/kinoko34077/other/issues/1#issuecomment-567"
        html = page(observed(evidence=url))
        self.assertNotIn('href="' + url, html)

    def test_offline_policy_uses_hashed_scripts_and_no_network(self):
        html = page(observed())
        match = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html)
        self.assertIsNotNone(match)
        value = match.group(1)
        self.assertIn("default-src &#x27;none&#x27;", value)
        self.assertIn("connect-src &#x27;none&#x27;", value)
        self.assertIn("script-src &#x27;sha256-", value)
        self.assertIn("style-src &#x27;sha256-", value)
        self.assertNotIn("unsafe-inline", value)
        self.assertNotIn('src="http', html)

    def test_empty_list_is_explicit_not_made_complete(self):
        html = page()
        self.assertIn("0 / 0 rows", html)
        self.assertIn("完了証明ではありません", html)

    def test_reject_invalid_schema_and_bad_count(self):
        value = build_coverage_report([observed()])
        with self.assertRaisesRegex(ValueError, "schema"):
            render_coverage_html({**value, "schema_version": "other"})
        with self.assertRaisesRegex(ValueError, "count"):
            render_coverage_html({**value, "row_count": 2})

    def test_foreign_and_duplicate_repository_fail_closed(self):
        value = build_coverage_report([observed()])
        row = {**value["rows"][0], "repository": "kinoko34077/foreign"}
        with self.assertRaisesRegex(ValueError, "foreign"):
            render_coverage_html({**value, "rows": [row]})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            render_coverage_html({**value, "repositories": value["repositories"] * 2,
                                 "repository_count": 2})

    def test_malicious_status_or_reponame_is_rejected(self):
        value = build_coverage_report([observed()])
        row = {**value["rows"][0], "status": 'CLEAN" onclick="unsafe'}
        with self.assertRaisesRegex(ValueError, "status"):
            render_coverage_html({**value, "rows": [row]})
        summary = {**value["repositories"][0], "repository": "<h1>fake</h1>"}
        with self.assertRaisesRegex(ValueError, "repository"):
            render_coverage_html({**value, "repositories": [summary]})

    def test_bad_limits_fail_closed(self):
        value = build_coverage_report([observed()])
        with self.assertRaisesRegex(ValueError, "limitations"):
            render_coverage_html({**value, "limits": [None]})

    def test_cli_html_format_uses_existing_report_no_writeback(self):
        value = build_coverage_report([observed()])
        with (patch.dict("os.environ", {"GITHUB_TOKEN": "dummy"}, clear=True),
              patch.object(cli, "GitHubReadTransport", return_value=object()),
              patch.object(cli, "build_live_report", return_value=value),
              patch("builtins.print") as printed):
            code = cli.main(["--repo-ledger", REPO + "#367", "--format", "html"])
        self.assertEqual(0, code)
        self.assertEqual(1, printed.call_count)
        html = printed.call_args.args[0]
        self.assertIn("<!doctype html>", html)
        self.assertIn('id="coverage-rows"', html)


if __name__ == "__main__":
    unittest.main()
