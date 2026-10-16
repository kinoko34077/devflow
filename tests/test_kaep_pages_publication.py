"""Pages KAEP publication: owned build/deploy gate, redacted output and no writes."""
from __future__ import annotations

from pathlib import Path
import unittest

from tools.kaep_issue_list_html import to_html

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows" / "mobile-actions-pages.yml"
LANDING = ROOT / "docs" / "mobile-actions" / "index.html"


class KaepPagesPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WF.read_text(encoding="utf-8")
        cls.landing = LANDING.read_text(encoding="utf-8")

    def test_existing_f8_artifact_remains_and_one_kaep_file_added(self):
        w = self.workflow
        for filename in ("index.html", "control.js", "style.css",
                         "manifest.webmanifest"):
            self.assertIn(filename, w)
        self.assertIn('mobile-actions-public/status.json', w)
        self.assertIn('kaep/index.html', w)
        self.assertIn('test "$(find "$out" -type f | wc -l)" -eq 6', w)
        self.assertIn("upload-pages-artifact@", w)
        self.assertIn("deploy-pages@", w)
        self.assertNotIn("gh-pages", w)
        self.assertIn('<a href="./kaep/">KAEP', self.landing)

    def test_pages_build_and_deploy_require_both_owner_actors(self):
        w = self.workflow
        self.assertEqual(w.count("github.actor == 'kinoko34077'"), 2)
        self.assertEqual(w.count("github.triggering_actor == 'kinoko34077'"), 2)
        self.assertGreaterEqual(w.count("github.repository == 'kinoko34077/devflow'"), 2)
        self.assertGreaterEqual(w.count("github.ref == 'refs/heads/main'"), 2)
        self.assertIn("  workflow_dispatch:", w)
        self.assertNotIn("  schedule:", w)
        self.assertNotIn("  repository_dispatch:", w)
        self.assertNotIn("  issue_comment:", w)

    def test_build_get_only_token_and_status_fail_closed(self):
        w = self.workflow
        self.assertIn("issues: read", w)
        self.assertNotIn("issues: write", w)
        self.assertNotIn("actions: write", w)
        self.assertIn("GH_TOKEN: ${{ github.token }}", w)
        self.assertIn("--format html", w)
        self.assertIn("--repository kinoko34077/devflow", w)
        self.assertIn("BOUNDED_SEARCH_READ", w)
        self.assertIn("PARTIAL_UNKNOWN", w)
        self.assertIn('status in ("BOUNDED_SEARCH_READ", "PARTIAL_UNKNOWN")', w)
        self.assertIn('if [[ "$rc" != "0" && "$rc" != "2" ]]', w)
        self.assertIn('test "$(find "$out" -type l | wc -l)" -eq 0', w)
        self.assertNotIn("persist-credentials: true", w)
        self.assertNotIn("upload-artifact@", w)

    def test_blocked_document_has_explicit_status_and_unknown(self):
        html = to_html({
            "status":"BLOCKED", "reason_code":"SOURCE_READ_UNAVAILABLE",
            "rows":[], "errors":[],
            "repositories":["kinoko34077/devflow"],
            "searched_candidates":0, "validated_source_issues":0,
            "partial_source_issues":0,
        })
        self.assertIn('data-source-status="BLOCKED"', html)
        self.assertIn("PARTIAL / UNKNOWN", html)
        self.assertIn("SOURCE_READ_UNAVAILABLE", html)
        self.assertIn("connect-src &#x27;none&#x27;", html)
        self.assertTrue(html.isascii())
        self.assertNotIn("api.github.com", html)

    def test_partial_document_never_proves_current_active_or_owner_auth(self):
        html = to_html({
            "status":"PARTIAL_UNKNOWN",
            "rows":[], "errors":[{"reason_code":"UNKNOWN_PARENT"}],
            "repositories":["kinoko34077/devflow"],
            "searched_candidates":1, "validated_source_issues":0,
            "partial_source_issues":1,
        })
        self.assertIn('data-source-status="PARTIAL_UNKNOWN"', html)
        self.assertIn("UNKNOWN_PARENT", html)
        self.assertIn("not a complete issue universe", html.lower())
        self.assertIn("no credentials", html.lower())
        self.assertNotIn("/dispatches", html)


if __name__ == "__main__":
    unittest.main()
