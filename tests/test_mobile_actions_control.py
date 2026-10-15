"""Mobile Actions launchpad stays read-only and iPhone navigable.

No network calls or GitHub writes are made by these tests.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1] / "docs" / "mobile-actions"


class MobileActionsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "style.css").read_text(encoding="utf-8")
        cls.js = (ROOT / "control.js").read_text(encoding="utf-8")
        cls.manifest = json.loads((ROOT / "manifest.webmanifest").read_text(encoding="utf-8"))

    def test_mobile_browser_entrypoint(self):
        self.assertIn('<html lang="ja">', self.html)
        self.assertIn('viewport-fit=cover', self.html)
        self.assertIn('name="viewport"', self.html)
        self.assertIn('href="./style.css"', self.html)
        self.assertIn('src="./control.js" defer', self.html)
        self.assertIn('href="./manifest.webmanifest"', self.html)
        self.assertIn("env(safe-area-inset-top)", self.css)
        self.assertIn("env(safe-area-inset-bottom)", self.css)
        self.assertIn("@media(max-width:450px)", self.css)
        self.assertIn("min-height:44px", self.css)
        self.assertIn("min-height:48px", self.css)
        self.assertIn(":focus-visible", self.css)

    def test_only_exact_public_devflow_urls(self):
        self.assertIn('const API = "https://api.github.com/repos/kinoko34077/devflow"', self.js)
        self.assertIn('const ISSUE_URL = API + "/issues/554"', self.js)
        self.assertIn('gpt-liveness-f8-manual.yml/runs?per_page=5', self.js)
        self.assertIn("https://github.com/kinoko34077/devflow/actions/workflows/gpt-liveness-f8-manual.yml", self.html)
        self.assertIn("https://github.com/kinoko34077/devflow/issues/555", self.html)
        self.assertIn("kinoko34077/devflow#554", self.html)

    def test_browser_has_no_write_or_credential_surface(self):
        self.assertIn('method: "GET"', self.js)
        self.assertIn('credentials: "omit"', self.js)
        self.assertIn('redirect: "error"', self.js)
        self.assertIn('cache: "no-store"', self.js)
        self.assertIn(".textContent", self.js)
        self.assertNotIn(".innerHTML", self.js)
        self.assertNotIn("localStorage", self.js)
        self.assertNotIn("sessionStorage", self.js)
        self.assertNotIn("navigator.serviceWorker", self.js)
        self.assertNotIn('method: "POST"', self.js)
        self.assertNotIn('method: "PATCH"', self.js)
        self.assertNotIn("Authorization:", self.js)
        self.assertNotIn("<input", self.html)
        self.assertNotIn("<form", self.html)
        self.assertIn("default-src 'none'", self.html)
        self.assertIn("connect-src 'self' https://api.github.com", self.html)
        self.assertIn("form-action 'none'", self.html)
        self.assertIn('target="_blank" rel="noopener noreferrer"', self.html)

    def test_explicit_manual_refresh_no_polling(self):
        self.assertIn('addEventListener("click", refresh)', self.js)
        self.assertNotIn("setInterval(", self.js)
        self.assertNotIn("/dispatches", self.js)
        self.assertIn('run.event === "workflow_dispatch" ? "手動" : "その他"', self.js)
        self.assertNotIn("run_workflow", self.js)
        self.assertIn("未確認は停止状態を意味しません", self.js)

    def test_standalone_home_screen_manifest_not_background_service(self):
        self.assertEqual(self.manifest["start_url"], "./index.html")
        self.assertEqual(self.manifest["scope"], "./")
        self.assertEqual(self.manifest["display"], "standalone")
        self.assertEqual(self.manifest["lang"], "ja")
        self.assertNotIn("shortcuts", self.manifest)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_javascript_syntax_and_live_enrollment_parser(self):
        script = ROOT / "control.js"
        check = subprocess.run(["node", "--check", str(script)], capture_output=True,
                               text=True, timeout=10, check=False)
        self.assertEqual(check.returncode, 0, check.stderr)
        node = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const sandbox = { document: { addEventListener() {} } };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), sandbox);
const fn = vm.runInContext('enrollmentStatus', sandbox);
const mark = obj => '<!-- gpt-liveness:enrollment:v0.1 ' + JSON.stringify(obj) + ' -->';
const e = {schema:'gpt.liveness.v0.1', enabled:false,
           started_at:'2026-10-15T00:00:00Z', expires_at:'2026-10-15T02:00:00Z'};
const now = new Date('2026-10-15T01:00:00Z');
assert.equal(fn(mark(e), now), '無効');
assert.equal(fn(mark({...e, enabled:true}), now), '登録マーカー有効（要再検証）');
assert.equal(fn(mark({...e, enabled:true, expires_at:'2026-10-15T00:10:00Z'}), now), '期限切れ');
assert.equal(fn(mark({...e, enabled:true, started_at:'2026-10-15T01:30:00Z'}), now), '開始前');
assert.equal(fn('no enrollment', now), '未登録');
assert.equal(fn(mark(e) + '\n' + mark(e), now), '判定不可（複数）');
assert.equal(fn(mark({...e, schema:'fake'}), now), '判定不可');
"""
        run = subprocess.run(["node", "-e", node, str(script)], capture_output=True,
                             text=True, timeout=10, check=False)
        self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == "__main__":
    unittest.main()
