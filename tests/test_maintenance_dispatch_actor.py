"""Job-level actor and rerun guards for privileged Maintenance workflows."""
from pathlib import Path
import re
import unittest

WORKFLOW = (Path(__file__).resolve().parents[1] / ".github/workflows/maintenance-audit.yml").read_text(encoding="utf-8")


def job_condition(job):
    match = re.search(r"^  " + re.escape(job) + r":\n    if: (.+)$", WORKFLOW, re.MULTILINE)
    if not match:
        raise AssertionError("Missing job condition: " + job)
    return match.group(1)


class MaintenanceDispatchActorTests(unittest.TestCase):
    def test_manual_modes_require_both_original_and_rerun_owner(self):
        jobs = (
            "audit", "projection-shadow", "maintenance-select",
            "publish", "catalog-maintenance-publish",
            "catalog-maintenance-complete", "projection-cache",
            "supply-credential-check",
        )
        for job in jobs:
            with self.subTest(job=job):
                value = job_condition(job)
                self.assertIn("github.actor_id == '79015263'", value)
                self.assertIn("github.triggering_actor == 'kinoko34077'", value)

    def test_periodic_producer_and_audit_remain_independent_of_human_actor(self):
        for job, cron in (("audit", "30 13 * * *"), ("projection-cache", "10 5,17 * * *")):
            value = job_condition(job)
            scheduled = value.split(" || ", 1)[0]
            self.assertIn("github.event_name == 'schedule'", scheduled)
            self.assertIn(cron, scheduled)
            self.assertNotIn("github.actor_id", scheduled)
            self.assertNotIn("github.triggering_actor", scheduled)

    def test_gates_do_not_weaken_protected_manual_modes(self):
        for job in ("publish", "catalog-maintenance-publish", "catalog-maintenance-complete", "supply-credential-check"):
            self.assertIn("github.ref == 'refs/heads/main'", job_condition(job))


if __name__ == "__main__":
    unittest.main()
