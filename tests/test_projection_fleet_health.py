import subprocess
import sys
import unittest
from pathlib import Path

from tools import repository_projection_cache_producer as producer
from tools import projection_fleet_health as health
from tests.test_repository_projection_cache_producer import (
    FakeService, GENERATED_AT, REPOSITORY, CONTROL_NUMBER, CONTROL_BODY,
    control_issue,
)

NOW = "2026-10-04T06:00:00Z"


class Fleet:
    def __init__(self, body, *, trusted=True, extra=False, discovery_fails=False, hidden_cached=False):
        self.reader = self
        self.body = body
        self.trusted = trusted
        self.extra = extra
        self.discovery_fails = discovery_fails
        self.hidden_cached = hidden_cached

    def list_managed_repositories(self):
        if self.discovery_fails:
            raise RuntimeError("simulated discovery outage")
        return [REPOSITORY, "kinoko34077/other"] if self.extra else [REPOSITORY]

    def list_issues(self, repository, state="open"):
        issues = [{"title": "[REPO] demo", "body": self.body}]
        if self.extra:
            issues.append({"title": "[REPO] other", "body": CONTROL_BODY})
        if self.hidden_cached:
            issues.append({"title": "[REPO] hidden", "body": self.body})
        return issues

    def get_repository_control(self, repository):
        return {"issue_number": CONTROL_NUMBER if repository == REPOSITORY else 8}

    def get_issue(self, repository, number):
        if number == CONTROL_NUMBER:
            return {**control_issue(), "body": self.body}
        return {"number": 8, "body": CONTROL_BODY}

    def is_repository_control_trusted(self, issue, repository):
        return self.trusted


class ProjectionFleetHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.valid = producer.prepare_target(
            FakeService(control_issue()),
            REPOSITORY, CONTROL_NUMBER,
            generated_at=GENERATED_AT,
        ).desired_body

    def test_current_requires_both_validated_caches(self):
        result = health.assess_fleet(Fleet(self.valid), now=NOW)
        self.assertEqual(result["status"], "CURRENT")
        self.assertEqual(result["repository_count"], 1)
        self.assertEqual(result["current_count"], 1)
        self.assertEqual(result["unknown_count"], 0)

    def test_expired_caches_cannot_report_current(self):
        result = health.assess_fleet(Fleet(self.valid), now="2026-10-06T06:00:00Z")
        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(result["degraded_count"], 1)

    def test_missing_cache_and_untrusted_control_unknown(self):
        self.assertEqual(
            health.assess_fleet(Fleet(CONTROL_BODY), now=NOW)["status"],
            "UNKNOWN",
        )
        self.assertEqual(
            health.assess_fleet(Fleet(self.valid, trusted=False), now=NOW)["status"],
            "UNKNOWN",
        )

    def test_one_current_and_one_unknown_is_not_fleet_success(self):
        result = health.assess_fleet(Fleet(self.valid, extra=True), now=NOW)
        self.assertEqual(result["repository_count"], 2)
        self.assertEqual(result["current_count"], 1)
        self.assertEqual(result["unknown_count"], 1)
        self.assertEqual(result["status"], "UNKNOWN")

    def test_previously_cached_control_filtered_out_of_roster_is_unknown(self):
        result = health.assess_fleet(Fleet(self.valid, hidden_cached=True), now=NOW)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason"], "CACHED_CONTROL_ROSTER_MISMATCH")

    def test_discovery_failure_is_unknown_not_empty_success(self):
        result = health.assess_fleet(Fleet(self.valid, discovery_fails=True), now=NOW)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason"], "MANAGED_FLEET_DISCOVERY_FAILED")

    def test_script_help_is_import_safe(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "scripts/projection_fleet_health.py", "--help"],
            cwd=root, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--read-token-env", result.stdout)


if __name__ == "__main__":
    unittest.main()
