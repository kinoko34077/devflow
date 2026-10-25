import unittest

from tools.projection_schedule_probe import classify_run, classify_projection_job


SLOT = "2026-10-25T02:00:00Z"


def data(*, event="schedule", created_at="2026-10-25T02:10:00Z", status="completed", conclusion="success"):
    return {"workflow_runs": [{"event": event, "created_at": created_at,
                               "status": status, "conclusion": conclusion,
                               "id": 123, "html_url": "https://github.com/example/run/123"}]}


class ProjectionScheduleProbeTests(unittest.TestCase):
    def test_success_is_workflow_only_not_cache_acceptance(self):
        self.assertEqual(classify_run(data(), expected_utc=SLOT)["status"], "WORKFLOW_SUCCESS_ONLY")

    def test_failed_run(self):
        self.assertEqual(classify_run(data(conclusion="failure"), expected_utc=SLOT)["status"], "WORKFLOW_FAILED")

    def test_pending_run(self):
        self.assertEqual(classify_run(data(status="in_progress", conclusion=None), expected_utc=SLOT)["status"], "IN_PROGRESS")

    def test_missing_and_wrong_event_do_not_claim_success(self):
        self.assertEqual(classify_run({"workflow_runs": []}, expected_utc=SLOT)["status"], "UNKNOWN")
        self.assertEqual(classify_run(data(event="workflow_dispatch"), expected_utc=SLOT)["status"], "UNKNOWN")

    def test_older_run_is_not_accepted(self):
        self.assertEqual(classify_run(data(created_at="2026-10-25T01:59:59Z"), expected_utc=SLOT)["status"], "UNKNOWN")

    def test_job_success_not_equal_to_cache_success(self):
        result = classify_projection_job({"jobs": [{"name": "projection-cache", "status": "completed", "conclusion": "success", "id": 2}]})
        self.assertEqual(result["status"], "PRODUCER_JOB_SUCCESS_ONLY")

    def test_audit_only_workflow_is_not_producer_success(self):
        result = classify_projection_job({"jobs": [{"name": "audit", "status": "completed", "conclusion": "success"}]})
        self.assertEqual(result["status"], "UNKNOWN")

    def test_skipped_producer_job_not_success(self):
        result = classify_projection_job({"jobs": [{"name": "projection-cache", "status": "completed", "conclusion": "skipped"}]})
        self.assertEqual(result["status"], "PRODUCER_JOB_FAILED")

    def test_malformed_payload_unknown(self):
        self.assertEqual(classify_run({}, expected_utc=SLOT)["status"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
