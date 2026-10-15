"""#487 R1: the existing closed Project Sync Health writer must not blind-PATCH.

Injected GitHub-shaped observations and effects only. No network writes.
"""
import unittest

from scripts import project_sync


HEALTH = project_sync.HEALTH_TITLE
T0 = "2026-10-16T00:00:00Z"
T1 = "2026-10-16T00:00:01Z"


class HealthRest:
    def __init__(self, *, found=True):
        self.issue = {
            "number": 41, "title": HEALTH, "state": "closed",
            "updated_at": T0, "body": "old health"
        }
        self.discovered = dict(self.issue) if found else None
        self.calls = []
        self.after_patch = None
        self.fail_patch = False

    def find_issue_by_title(self, title):
        self.calls.append("FIND")
        return None if self.discovered is None else dict(self.discovered)

    def get_issue(self, number):
        self.calls.append("GET")
        if number != 41:
            raise AssertionError("GET sent to wrong requested Issue URL")
        return dict(self.issue)

    def create_issue(self, title, body):
        self.calls.append("CREATE")
        self.issue = {
            "number": 41, "title": title, "state": "open",
            "body": body, "updated_at": T0
        }
        return dict(self.issue)

    def update_issue(self, number, body=None, state=None):
        self.calls.append("PATCH")
        if self.fail_patch:
            raise project_sync.APIError("native PATCH uncertain")
        if state is not None:
            self.issue["state"] = state
        if body is not None:
            self.issue["body"] = body
        self.issue["updated_at"] = T1
        if self.after_patch is not None:
            self.after_patch(self.issue)
        return dict(self.issue)


class ClosedHealthWriterTests(unittest.TestCase):
    def test_normal_update_one_patch_and_independent_postread(self):
        rest = HealthRest()
        result = project_sync.upsert_health_issue(rest, "new health")
        self.assertEqual(result["body"], "new health")
        self.assertEqual(rest.calls, ["FIND", "GET", "PATCH", "GET"])

    def test_exact_noop_is_zero_patch(self):
        rest = HealthRest()
        result = project_sync.upsert_health_issue(rest, "old health")
        self.assertEqual(result["body"], "old health")
        self.assertEqual(rest.calls, ["FIND", "GET"])

    def test_discovery_to_last_get_metadata_only_drift_refused(self):
        for difference in ({"updated_at": T1}, {"body": "newer"},
                           {"title": "wrong"}, {"state": "open"},
                           {"number": True}, {"body": None}):
            with self.subTest(difference=difference):
                rest = HealthRest()
                rest.issue.update(difference)
                with self.assertRaises(project_sync.APIError):
                    project_sync.upsert_health_issue(rest, "desired")
                self.assertNotIn("PATCH", rest.calls)

    def test_bad_discovery_and_untrusted_closed_issue_are_rejected(self):
        for difference in ({"number": True}, {"title": "wrong"},
                           {"state": "open"}, {"updated_at": "not-timestamp"},
                           {"body": None}):
            with self.subTest(difference=difference):
                rest = HealthRest()
                rest.discovered.update(difference)
                with self.assertRaises(project_sync.APIError):
                    project_sync.upsert_health_issue(rest, "desired")
                self.assertNotIn("PATCH", rest.calls)

    def test_unverified_success_response_does_not_prove_write(self):
        rest = HealthRest()
        rest.after_patch = lambda issue: issue.update(body="other actor")
        with self.assertRaisesRegex(project_sync.APIError, "postwrite"):
            project_sync.upsert_health_issue(rest, "desired")
        self.assertEqual(rest.calls, ["FIND", "GET", "PATCH", "GET"])

    def test_transport_error_is_not_implicitly_retried(self):
        rest = HealthRest()
        rest.fail_patch = True
        with self.assertRaises(project_sync.APIError):
            project_sync.upsert_health_issue(rest, "desired")
        self.assertEqual(rest.calls, ["FIND", "GET", "PATCH"])

    def test_initial_creation_closes_and_confirms_without_extra_patch(self):
        rest = HealthRest(found=False)
        result = project_sync.upsert_health_issue(rest, "initial")
        self.assertEqual(rest.calls, ["FIND", "CREATE", "PATCH", "GET"])
        self.assertEqual(result["state"], "closed")
        self.assertEqual(result["body"], "initial")

    def test_creation_close_must_be_verified_before_any_body_patch(self):
        rest = HealthRest(found=False)
        rest.after_patch = lambda issue: issue.update(state="open")
        with self.assertRaises(project_sync.APIError):
            project_sync.upsert_health_issue(rest, "initial")
        self.assertEqual(rest.calls, ["FIND", "CREATE", "PATCH", "GET"])


if __name__ == "__main__":
    unittest.main()
