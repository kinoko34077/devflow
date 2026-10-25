"""Keep the production renewal schedule aligned with the producer job gate."""
import re
import unittest
from pathlib import Path


class ProjectionRenewalScheduleTests(unittest.TestCase):
    def test_off_peak_schedule_matches_projection_job_gate(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/maintenance-audit.yml"
        ).read_text(encoding="utf-8")
        renewal = "17 2,14 * * *"
        self.assertIn("cron: '" + renewal + "'", workflow)
        self.assertIn("github.event.schedule == '" + renewal + "'", workflow)
        self.assertEqual(workflow.count(renewal), 2)
        self.assertIn("cron: '30 13 * * *'", workflow)
        self.assertNotIn("0 2,14 * * *", workflow)


if __name__ == "__main__":
    unittest.main()
