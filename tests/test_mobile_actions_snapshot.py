"""Offline, no-token contract for the Pages-published status snapshot."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from tools import mobile_actions_snapshot as snap

NOW = datetime(2026, 10, 16, 2, 0, tzinfo=timezone.utc)


def marker(*, enabled=False, start="2026-10-16T00:00:00Z", end="2026-10-16T03:00:00Z"):
    obj = {
        "schema": "gpt.liveness.v0.1",
        "enabled": enabled,
        "started_at": start,
        "expires_at": end,
        "session_id": "PRIVATE_EXAMPLE_SESSION_NOT_FOR_PUBLICATION",
        "turn_id": "PRIVATE_EXAMPLE_TURN_NOT_FOR_PUBLICATION",
    }
    return "<!-- gpt-liveness:enrollment:v0.1 " + json.dumps(obj) + " -->"


class MobileSnapshotTests(unittest.TestCase):
    def test_pinned_repository_and_get_paths(self):
        self.assertEqual(snap.API_ROOT, "https://api.github.com/repos/kinoko34077/devflow")
        self.assertEqual(snap.ISSUE_PATH, "/issues/554")
        self.assertEqual(snap.RUNS_PATH, "/actions/workflows/gpt-liveness-f8-manual.yml/runs?per_page=5")

    def test_disabled_enrollment_is_not_live(self):
        self.assertEqual(snap.enrollment_status(marker(enabled=False), NOW), "無効")

    def test_active_enrollment_remains_provisional(self):
        self.assertEqual(snap.enrollment_status(marker(enabled=True), NOW), "登録マーカー有効（要再検証）")

    def test_expired_future_and_malformed(self):
        self.assertEqual(snap.enrollment_status(marker(enabled=True, end="2026-10-16T01:00:00Z"), NOW), "期限切れ")
        self.assertEqual(snap.enrollment_status(marker(enabled=True, start="2026-10-16T02:30:00Z"), NOW), "開始前")
        self.assertEqual(snap.enrollment_status(marker() + "\n" + marker(), NOW), "判定不可（複数）")
        self.assertEqual(snap.enrollment_status("No registration", NOW), "未登録")
        self.assertEqual(snap.enrollment_status("<!-- gpt-liveness:enrollment:v0.1 {not-json} -->", NOW), "判定不可")

    def test_issue_scrubs_body_and_marker_details(self):
        source = {"number": 554, "state": "open", "comments": 0, "body": marker(enabled=False)}
        result = snap.build_snapshot(source, {"workflow_runs":[]}, NOW)
        blob = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["schema"], snap.SCHEMA)
        self.assertEqual(result["issue"], {"number":554,"state":"open","comments":0})
        self.assertEqual(result["enrollment_status"], "無効")
        self.assertNotIn("body", blob)
        self.assertNotIn("PRIVATE_EXAMPLE_SESSION", blob)
        self.assertNotIn("PRIVATE_EXAMPLE_TURN", blob)
        self.assertNotIn("session_id", blob)
        self.assertNotIn("turn_id", blob)
        self.assertNotIn("access_token", blob)
        self.assertNotIn("Authorization", blob)

    def test_runs_only_allowlisted_fields_and_limit(self):
        runs = [{"run_number": i, "status": "completed", "conclusion": "success",
                 "event": "workflow_dispatch", "created_at": "2026-10-16T01:00:00Z",
                 "actor": {"login":"SENSITIVE"}, "token":"SECRET"} for i in range(12)]
        report = snap.build_snapshot(None, {"workflow_runs": runs}, NOW)
        self.assertEqual(len(report["runs"]["workflow_runs"]), 5)
        self.assertNotIn("SENSITIVE", json.dumps(report))
        self.assertNotIn("SECRET", json.dumps(report))
        self.assertIsNone(report["issue"])
        self.assertIsNone(report["enrollment_status"])

    def test_unknown_issue_remains_unknown(self):
        result = snap.build_snapshot({"number": 999, "state": "open", "body": "marker"},
                                     {"workflow_runs": []}, NOW)
        self.assertIsNone(result["issue"])
        self.assertIsNone(result["enrollment_status"])

    def test_api_failure_never_infers_stopped(self):
        report = snap.build_snapshot(None, None, NOW)
        self.assertIsNone(report["issue"])
        self.assertIsNone(report["runs"])
        self.assertIsNone(report["enrollment_status"])
        self.assertEqual(report["source"], "github-actions-build")

    def test_pages_workflow_scope(self):
        repo = Path(__file__).resolve().parents[1]
        workflow = (repo / ".github/workflows/mobile-actions-pages.yml").read_text(encoding="utf-8")
        self.assertIn("issues: read", workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn("GH_TOKEN: $" + "{{ github.token }}", workflow)
        self.assertIn("python -m tools.mobile_actions_snapshot", workflow)
        self.assertIn('mobile-actions-public/status.json', workflow)
        self.assertIn('eq 5', workflow)
        self.assertNotIn("schedule:", workflow)
        # Owner-only Pages refresh is independent of the F8 PING sender.
        self.assertIn("  workflow_dispatch:", workflow)
        self.assertEqual(workflow.count("github.actor == 'kinoko34077'"), 2)
        self.assertEqual(workflow.count("github.triggering_actor == 'kinoko34077'"), 2)
        self.assertIn('eq 6', workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("issues: write", workflow)
        self.assertNotIn("actions: write", workflow)

    def test_browser_same_origin_fallback_and_safety(self):
        repo = Path(__file__).resolve().parents[1]
        script = (repo / "docs/mobile-actions/control.js").read_text(encoding="utf-8")
        html = (repo / "docs/mobile-actions/index.html").read_text(encoding="utf-8")
        self.assertIn('const SNAPSHOT_URL = "./status.json"', script)
        self.assertIn('snapshot.generated_at', script)
        self.assertIn("readSnapshot()", script)
        self.assertIn("errorLabel(", script)
        self.assertIn("保存情報", script)
        self.assertIn("connect-src 'self' https://api.github.com", html)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("/dispatches", script)
        self.assertNotIn('method: "POST"', script)


if __name__ == "__main__":
    unittest.main()
