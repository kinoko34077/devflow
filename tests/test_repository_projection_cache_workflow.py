import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "maintenance-audit.yml"


class RepositoryProjectionCacheWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def _cache_job(self):
        marker = "\n  projection-cache:\n"
        if marker not in self.text:
            self.fail("central projection-cache job is missing")
        return self.text.split(marker, 1)[1]

    def test_manual_mode_is_declared(self):
        self.assertIn("- projection-cache", self.text)

    def test_cache_job_supports_manual_target_and_central_schedule(self):
        job = self._cache_job()
        self.assertIn(
            "github.event_name == 'workflow_dispatch' && inputs.mode == 'projection-cache'",
            job,
        )
        self.assertIn("github.event_name == 'schedule'", job)
        self.assertIn("github.event.schedule == '0 14 * * *'", job)

    def test_cache_job_has_bounded_issue_write_permission(self):
        job = self._cache_job()
        self.assertIn("permissions:", job)
        self.assertIn("contents: read", job)
        self.assertIn("issues: write", job)
        self.assertNotIn("pull-requests: write", job)
        self.assertNotIn("actions: write", job)

    def test_cache_job_uses_targeted_manual_or_fleet_scheduled_central_script(self):
        job = self._cache_job()
        self.assertIn("CACHE_REPOSITORY:", job)
        self.assertIn("CACHE_CONTROL:", job)
        self.assertIn("MAINTENANCE_AUDIT_TOKEN:", job)
        self.assertIn("GITHUB_TOKEN:", job)
        self.assertIn("scripts/repository_projection_cache.py", job)
        self.assertIn("--repository", job)
        self.assertIn("--control", job)
        self.assertIn("--fleet", job)
        self.assertIn("--apply", job)

    def test_cache_job_is_non_cancelling_and_central(self):
        job = self._cache_job()
        self.assertIn("concurrency:", job)
        self.assertIn(
            "group: repository-projection-cache-${{ github.repository }}",
            job,
        )
        self.assertIn("cancel-in-progress: false", job)


if __name__ == "__main__":
    unittest.main()
