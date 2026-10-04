import subprocess
import sys
import unittest
from pathlib import Path

from tools import maintenance_sync_check
from tools import repository_projection_cache as cache
from tools import repository_projection_cache_producer as producer


REPOSITORY = "kinoko34077/demo"
CONTROL_REPOSITORY = "kinoko34077/devflow"
CONTROL_NUMBER = 7
CONTROL_BODY = "## Repository\n\n`kinoko34077/demo`\n\n## Active Work\n\nHuman text.\n"
GENERATED_AT = "2026-10-04T05:56:00Z"
OBSERVED_AT = "2026-10-04T05:55:00Z"


def projection():
    return {
        "repository": REPOSITORY,
        "observed_at": OBSERVED_AT,
        "source_status": "AVAILABLE",
        "source_freshness": "CURRENT",
        "source_error": None,
        "open_issue_count": 2,
        "machine_task_count": 0,
        "legacy_hint_count": 1,
        "unclassified_count": 1,
        "invalid_metadata_count": 0,
        "untrusted_metadata_count": 0,
        "machine_type_counts": {},
        "legacy_hint_type_counts": {"BUG": 1},
        "task_records": [],
        "ready_tasks": [],
        "implementing_tasks": [],
        "newest_open_issue": None,
        "recently_active_issue": None,
        "records": [],
    }


class FakeReader:
    def __init__(self, issue):
        self.issue = dict(issue)

    def get_issue(self, repository, number):
        if repository != CONTROL_REPOSITORY or number != CONTROL_NUMBER:
            raise AssertionError("unexpected Control read")
        return dict(self.issue)


class FakeService:
    devflow_repository = CONTROL_REPOSITORY

    def __init__(
        self,
        issue,
        *,
        trusted=True,
        control_number=CONTROL_NUMBER,
        projection_override=None,
    ):
        self.reader = FakeReader(issue)
        self.trusted = trusted
        self.control_number = control_number
        self.projection_override = projection_override

    def get_repository_control(self, repository):
        self.last_control_repository = repository
        return {
            "repository": repository,
            "issue_number": self.control_number,
        }

    def is_repository_control_trusted(self, issue, repository):
        self.last_trust = (issue["number"], repository)
        return self.trusted

    def get_repository_projection(self, repository):
        self.last_projection_repository = repository
        return (
            self.projection_override
            if self.projection_override is not None
            else projection()
        )


class FakeWriter:
    def __init__(self, body=CONTROL_BODY, *, persist=True):
        self.body = body
        self.persist = persist
        self.update_calls = []

    def get_issue(self, repository, number):
        return {
            "number": number,
            "title": "[REPO] demo",
            "state": "open",
            "body": self.body,
        }

    def update_issue_body(self, repository, number, body):
        self.update_calls.append((repository, number, body))
        if self.persist:
            self.body = body
        return True


def control_issue(*, association="OWNER"):
    return {
        "number": CONTROL_NUMBER,
        "title": "[REPO] demo",
        "state": "open",
        "body": CONTROL_BODY,
        "author_association": association,
    }


class ProjectionCacheProducerPlanTests(unittest.TestCase):
    def test_direct_control_uses_shared_verifier_and_builds_fenced_plan(self):
        service = FakeService(control_issue(association="OWNER"), trusted=True)
        plan = producer.prepare_target(
            service,
            REPOSITORY,
            CONTROL_NUMBER,
            generated_at=GENERATED_AT,
        )
        self.assertEqual(plan.repository, REPOSITORY)
        self.assertEqual(plan.control_issue_number, CONTROL_NUMBER)
        self.assertEqual(
            plan.expected_body_sha256,
            maintenance_sync_check.canonical_body_sha256(CONTROL_BODY),
        )
        self.assertTrue(plan.changed)
        self.assertIn(cache.CACHE_MARKER_BEGIN, plan.desired_body)
        self.assertEqual(service.last_trust, (CONTROL_NUMBER, REPOSITORY))

    def test_bootstrap_derived_control_is_accepted_only_via_shared_verifier(self):
        service = FakeService(control_issue(association="NONE"), trusted=True)
        plan = producer.prepare_target(
            service,
            REPOSITORY,
            CONTROL_NUMBER,
            generated_at=GENERATED_AT,
        )
        self.assertTrue(plan.changed)
        self.assertEqual(plan.source_status, "AVAILABLE")

    def test_untrusted_control_fails_closed(self):
        service = FakeService(control_issue(association="NONE"), trusted=False)
        with self.assertRaisesRegex(
            producer.RepositoryProjectionCacheProducerError,
            "trusted",
        ):
            producer.prepare_target(
                service,
                REPOSITORY,
                CONTROL_NUMBER,
                generated_at=GENERATED_AT,
            )

    def test_control_number_mismatch_fails_closed(self):
        service = FakeService(
            control_issue(),
            trusted=True,
            control_number=99,
        )
        with self.assertRaisesRegex(
            producer.RepositoryProjectionCacheProducerError,
            "Control issue number",
        ):
            producer.prepare_target(
                service,
                REPOSITORY,
                CONTROL_NUMBER,
                generated_at=GENERATED_AT,
            )

    def test_source_unavailable_cache_remains_fail_closed(self):
        unavailable = projection()
        unavailable.update(
            {
                "source_status": "UNAVAILABLE",
                "source_freshness": "UNKNOWN",
                "source_error": "GitHub read failed",
                "open_issue_count": 0,
                "machine_task_count": 0,
                "legacy_hint_count": 0,
                "unclassified_count": 0,
                "invalid_metadata_count": 0,
                "untrusted_metadata_count": 0,
                "legacy_hint_type_counts": {},
            }
        )
        service = FakeService(
            control_issue(),
            trusted=True,
            projection_override=unavailable,
        )
        plan = producer.prepare_target(
            service,
            REPOSITORY,
            CONTROL_NUMBER,
            generated_at=GENERATED_AT,
        )
        parsed = cache.parse_cached_projection(plan.desired_body, REPOSITORY)
        self.assertIsNotNone(parsed)
        self.assertEqual(plan.source_status, "UNAVAILABLE")
        self.assertEqual(plan.coverage_status, "UNAVAILABLE")
        self.assertTrue(parsed.payload["coverage"]["ambiguous"])
        self.assertEqual(
            parsed.payload["coverage"]["active_work_evidence"],
            "SOURCE_UNAVAILABLE",
        )
        self.assertFalse(
            parsed.payload["coverage"]["can_replace_manual_active_work"]
        )


class ProjectionCacheProducerApplyTests(unittest.TestCase):
    def _plan(self):
        return producer.prepare_target(
            FakeService(control_issue(), trusted=True),
            REPOSITORY,
            CONTROL_NUMBER,
            generated_at=GENERATED_AT,
        )

    def test_prewrite_drift_blocks_update(self):
        plan = self._plan()
        writer = FakeWriter(CONTROL_BODY + "\nHuman edit after plan.\n")
        with self.assertRaisesRegex(
            producer.RepositoryProjectionCacheProducerError,
            "pre-write",
        ):
            producer.apply_plan(writer, plan)
        self.assertEqual(writer.update_calls, [])

    def test_apply_updates_marker_only_and_confirms_readback(self):
        plan = self._plan()
        writer = FakeWriter()
        result = producer.apply_plan(writer, plan)
        self.assertEqual(result["status"], "UPDATED")
        self.assertEqual(result["generation_id"], plan.generation_id)
        self.assertEqual(len(writer.update_calls), 1)
        self.assertIn("Human text.", writer.body)
        parsed = cache.parse_cached_projection(writer.body, REPOSITORY)
        self.assertEqual(parsed.payload["generation_id"], plan.generation_id)

    def test_postwrite_mismatch_fails_closed(self):
        plan = self._plan()
        writer = FakeWriter(persist=False)
        with self.assertRaisesRegex(
            producer.RepositoryProjectionCacheProducerError,
            "post-write",
        ):
            producer.apply_plan(writer, plan)


class ProjectionCacheScriptTests(unittest.TestCase):
    def test_direct_script_help_is_import_safe(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "scripts/repository_projection_cache.py", "--help"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--repository", result.stdout)
        self.assertIn("--control", result.stdout)
        self.assertIn("--apply", result.stdout)


if __name__ == "__main__":
    unittest.main()
