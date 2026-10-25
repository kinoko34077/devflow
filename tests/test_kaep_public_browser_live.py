"""RT3 public-only KAEP recent Github comment candidates (read-only)."""
from __future__ import annotations

import base64
import hashlib
import re
import shutil
import subprocess
import unittest

from tools.kaep_issue_list_html import to_html, JS, LIVE_JS, CSS, LIVE_CSS
from tools import kaep_issue_search_view


def sample():
    return {
        "status": "PARTIAL_UNKNOWN",
        "observed_at": "2026-10-17T05:30:00+00:00",
        "repositories": ["kinoko34077/devflow"],
        "searched_candidates": 1,
        "validated_source_issues": 1,
        "partial_source_issues": 0,
        "rows": [],
        "errors": [],
        "has_unknown_work": True,
        "can_authorize_execution": False,
    }


class PublicBrowserLiveTests(unittest.TestCase):
    def test_local_offline_default_remains_network_denied(self):
        html = to_html(sample())
        self.assertIn("connect-src &#x27;none&#x27;", html)
        self.assertNotIn("live-update", html)
        self.assertNotIn("api.github.com", html)
        self.assertNotIn("fetch(", html)

    def test_public_opt_in_only_uses_official_github_read_api(self):
        html = to_html(sample(), public_live=True)
        self.assertIn('id="live-update"', html)
        self.assertIn('id="live-candidates"', html)
        self.assertIn('id="live-status"', html)
        self.assertIn("connect-src https://api.github.com", html)
        self.assertIn("https://api.github.com/repos/kinoko34077/devflow/issues/comments?", html)
        self.assertIn('method:"GET"', html)
        self.assertIn('credentials:"omit"', html)
        self.assertIn('cache:"no-store"', html)
        self.assertIn('redirect:"error"', html)
        self.assertIn("visible", html)
        self.assertIn("300000", html)
        self.assertIn("60000", html)
        self.assertIn("setInterval(", html)
        self.assertIn("PARTIAL / UNKNOWN", html)
        self.assertIn('data-source-status="PARTIAL_UNKNOWN"', html)
        for forbidden in ("method:\"POST\"", "Authorization:", "GH_TOKEN", "localStorage",
                          "sessionStorage", "XMLHttpRequest", "new WebSocket",
                          "navigator.serviceWorker", "github.com/projects"):
            self.assertNotIn(forbidden, html)

    def test_csp_hash_matches_emitted_script_byte_for_byte(self):
        html = to_html(sample(), public_live=True)
        m = re.search(r"<script>([\s\S]+)</script></body></html>", html)
        self.assertIsNotNone(m)
        script = m.group(1)
        self.assertTrue(script.isascii())
        expected = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")
        self.assertIn("script-src &#x27;sha256-" + expected + "&#x27;", html)
        css = re.search(r"<style>([\s\S]+)</style></head>", html).group(1)
        style_hash = base64.b64encode(hashlib.sha256(css.encode("utf-8")).digest()).decode("ascii")
        self.assertIn("style-src &#x27;sha256-" + style_hash + "&#x27;", html)
        self.assertTrue(html.isascii())

    def test_live_candidate_never_trusted_without_original_codec(self):
        src = LIVE_JS
        self.assertIn('startsWith("<!-- kaep:message:v0.2 -->")', src)
        self.assertIn('c.user.id!==79015263', src)
        self.assertIn('c.user.login!=="kinoko34077"', src)
        self.assertIn('Number.isSafeInteger(c.id)', src)
        self.assertIn('seen.has(link)', src)
        self.assertIn('known.has(link)', src)
        self.assertIn('list.replaceChildren()', src)
        self.assertIn('a.textContent=', src)
        self.assertNotIn("innerHTML", src)
        self.assertNotIn("eval(", src)
        self.assertIn("原典未検証", src)
        self.assertIn("現在の全依頼や未処理件数の証明ではありません", src)

    def test_public_live_flag_rejected_without_paired_html_json(self):
        # CLI rejects advertising live Public HTML on JSON/Markdown without
        # the required candidate cache snapshot output.
        import io
        from unittest import mock
        with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            rc = kaep_issue_search_view.main([
                "--repository", "kinoko34077/devflow",
                "--expect-source-actor", "kinoko34077",
                "--format", "markdown", "--public-live",
            ])
        self.assertEqual(rc, 2)
        self.assertIn("PUBLIC_LIVE_REQUIRES_PAIRED_HTML_INDEX", output.getvalue())

    def test_workflow_still_owner_only_and_published_html_opted_in(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/mobile-actions-pages.yml").read_text(encoding="utf-8")
        self.assertIn("--public-live", workflow)
        self.assertIn("--public-json-out", workflow)
        self.assertIn("connect-src https://api.github.com", workflow)
        self.assertNotIn("issues: write", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertEqual(workflow.count("github.actor_id == '79015263'"), 2)
        self.assertEqual(workflow.count("github.triggering_actor == 'kinoko34077'"), 2)

    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable")
    def test_public_script_syntax(self):
        script = JS + LIVE_JS.encode("ascii", "backslashreplace").decode("ascii")
        r = subprocess.run(["node", "--check"], input=script, capture_output=True,
                           text=True, timeout=10, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
