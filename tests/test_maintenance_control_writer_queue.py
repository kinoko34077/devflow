"""#487 M3: static native Actions Control-writer concurrency contract.

This checks source configuration, not a live or global GitHub Issue CAS.
Only workflows in the named GitHub Actions concurrency group are fenced.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

WORKFLOW = Path(".github/workflows/maintenance-audit.yml")
GROUP = "devflow-control-writes-${{ github.repository }}"
WRITERS = (
    "publish",
    "catalog-maintenance-publish",
    "catalog-maintenance-complete",
    "projection-cache",
)
READ_ONLY = (
    "audit",
    "projection-shadow",
    "maintenance-select",
)


def job_block(source: str, name: str) -> str:
    marker = f"  {name}:\n"
    if source.count(marker) != 1:
        raise AssertionError(f"missing or duplicate job: {name}")
    after = source.split(marker, 1)[1]
    next_job = re.search(r"(?m)^  [a-z][a-z0-9-]*:\s*$", after)
    return after[:next_job.start()] if next_job else after


class ControlWriterConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding="utf-8")

    def test_all_four_effectful_jobs_share_one_global_control_queue(self):
        for name in WRITERS:
            with self.subTest(name=name):
                source = job_block(self.source, name)
                self.assertEqual(source.count(f"group: {GROUP}"), 1)
                self.assertRegex(
                    source,
                    r"(?m)^    concurrency:\n"
                    r"      group: devflow-control-writes-\$\{\{ github.repository \}\}\n"
                    r"      queue: max\n"
                    r"      cancel-in-progress: false\n",
                )
        self.assertEqual(self.source.count(f"group: {GROUP}"), 4)

    def test_fleet_cache_cannot_be_siloed_by_input_target(self):
        # Scheduled projection-cache --fleet may mutate *all* Control Issues.
        # Therefore the group must not include inputs.repository/control.
        for name in WRITERS:
            source = job_block(self.source, name)
            self.assertNotIn("group: catalog-maintenance-publish-", source)
            self.assertNotIn("group: repository-projection-cache-", source)
            self.assertNotIn("group: devflow-control-writes-${{ inputs.", source)
        fleet = job_block(self.source, "projection-cache")
        self.assertIn("--fleet", fleet)
        self.assertIn("--apply", fleet)

    def test_all_existing_read_only_jobs_are_not_blocked_by_writer_queue(self):
        for name in READ_ONLY:
            with self.subTest(name=name):
                source = job_block(self.source, name)
                self.assertNotIn(f"group: {GROUP}", source)
                self.assertIn("cancel-in-progress: false", source)

    def test_no_permission_or_main_only_gate_removed(self):
        for name in ("publish", "catalog-maintenance-publish", "catalog-maintenance-complete"):
            source = job_block(self.source, name)
            self.assertIn("environment:", source)
            self.assertIn("name: maintenance-supply", source)
            self.assertIn("github.ref == 'refs/heads/main'", source)
            self.assertIn("issues: read", source)
        cache = job_block(self.source, "projection-cache")
        self.assertIn("issues: write", cache)
        self.assertIn("mode == 'projection-cache'", cache)

    def test_project_sync_health_queue_is_separate_accepted_owner(self):
        source = Path(".github/workflows/project-sync.yml").read_text(encoding="utf-8")
        self.assertIn("group: project-sync", source)
        self.assertNotIn(GROUP, source)


if __name__ == "__main__":
    unittest.main()
