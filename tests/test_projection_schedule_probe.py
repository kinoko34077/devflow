import contextlib
import io
import json
import unittest
from unittest.mock import patch

from tools.projection_schedule_probe import classify_run, classify_projection_job, main


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

    def test_failed_producer_job_is_not_hidden_by_other_workflow_jobs(self):
        result = classify_projection_job({"jobs": [
            {"name": "audit", "status": "completed", "conclusion": "success"},
            {"name": "projection-cache", "status": "completed", "conclusion": "failure", "id": 7},
        ]})
        self.assertEqual(result["status"], "PRODUCER_JOB_FAILED")

    def test_audit_only_workflow_is_not_producer_success(self):
        result = classify_projection_job({"jobs": [{"name": "audit", "status": "completed", "conclusion": "success"}]})
        self.assertEqual(result["status"], "UNKNOWN")

    def test_skipped_producer_job_not_success(self):
        result = classify_projection_job({"jobs": [{"name": "projection-cache", "status": "completed", "conclusion": "skipped"}]})
        self.assertEqual(result["status"], "UNKNOWN")

    def test_audit_delay_overlaps_renewal_returns_unknown(self):
        payload = data()
        payload["workflow_runs"].append({**payload["workflow_runs"][0], "id": 124, "created_at": "2026-10-25T02:20:00Z"})
        result = classify_run(payload, expected_utc=SLOT)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason"], "AMBIGUOUS_SCHEDULE_RUNS")

    def test_main_requires_both_workflow_and_job_success(self):
        jobs = {"jobs": [{"name": "projection-cache", "status": "completed",
                           "conclusion": "success", "id": 77}]}
        for run_conclusion, expected_code, expected_status in (
            ("success", 0, "PRODUCER_JOB_SUCCESS_ONLY"),
            ("failure", 1, "UNKNOWN"),
        ):
            with self.subTest(run_conclusion=run_conclusion):
                runs = data(conclusion=run_conclusion)
                source = [io.BytesIO(json.dumps(payload).encode("utf-8"))
                          for payload in (runs, jobs)]
                output = io.StringIO()
                with patch("tools.projection_schedule_probe.urllib.request.urlopen",
                           side_effect=source) as get, contextlib.redirect_stdout(output):
                    code = main(["--expected-utc", SLOT])
                response = json.loads(output.getvalue())
                self.assertEqual(code, expected_code)
                self.assertEqual(response["status"], expected_status)
                self.assertEqual(get.call_count, 2)
                if run_conclusion == "failure":
                    self.assertEqual(response["run_status"], "WORKFLOW_FAILED")
                    self.assertEqual(response["reason"], "WORKFLOW_NOT_SUCCESSFUL")

    def test_main_missing_scheduled_run_is_unknown_without_job_request(self):
        output = io.StringIO()
        source = io.BytesIO(json.dumps({"workflow_runs": []}).encode("utf-8"))
        with patch("tools.projection_schedule_probe.urllib.request.urlopen",
                   return_value=source) as get, contextlib.redirect_stdout(output):
            code = main(["--expected-utc", SLOT])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "UNKNOWN")
        get.assert_called_once()

    def test_four_hour_late_run_is_not_a_success(self):
        late = data(created_at="2026-10-25T06:36:35Z")
        result = classify_run(late, expected_utc=SLOT)
        self.assertEqual(result["status"], "LATE_SCHEDULE_RUN")
        self.assertEqual(result["lateness_seconds"], 4 * 3600 + 36 * 60 + 35)

    def test_main_late_job_success_still_exits_nonzero(self):
        late = data(created_at="2026-10-25T06:36:35Z")
        jobs = {"jobs": [{"name": "projection-cache", "status": "completed",
                           "conclusion": "success", "id": 77}]}
        output = io.StringIO()
        source = [io.BytesIO(json.dumps(payload).encode("utf-8"))
                  for payload in (late, jobs)]
        with patch("tools.projection_schedule_probe.urllib.request.urlopen",
                   side_effect=source), contextlib.redirect_stdout(output):
            code = main(["--expected-utc", SLOT])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "LATE_SCHEDULE_RUN")
        self.assertEqual(result["reason"], "SCHEDULE_TOO_LATE")
        self.assertEqual(result["job_id"], 77)

    def test_malformed_payload_unknown(self):
        self.assertEqual(classify_run({}, expected_utc=SLOT)["status"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
