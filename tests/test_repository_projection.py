import json
import unittest

from tools import repository_projection as rp


def metadata_body(**overrides):
    payload = {
        "schema_version": 1,
        "record_role": "TASK",
        "type": "BUG",
        "work_status": "READY_FOR_IMPLEMENTATION",
        "scope_ready": True,
        "requires_user_confirmation": False,
        "external_wait": False,
        "priority": "P1",
        "risk": "HIGH",
        "blocked_by": ["kinoko34077/demo#4"],
        "work_order_ref": "kinoko34077/devflow#330",
        "implementation_ref": None,
        "next_action_tag": "IMPLEMENT",
    }
    payload.update(overrides)
    return (
        rp.METADATA_BEGIN
        + "\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n"
        + rp.METADATA_END
    )


class IssueMetadataContractTests(unittest.TestCase):
    def test_valid_task_metadata_parses_canonical_fields(self):
        metadata = rp.parse_issue_metadata(metadata_body())
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.schema_version, 1)
        self.assertEqual(metadata.record_role, "TASK")
        self.assertTrue(metadata.is_task)
        self.assertEqual(metadata.type, "BUG")
        self.assertEqual(metadata.work_status, "READY_FOR_IMPLEMENTATION")
        self.assertTrue(metadata.scope_ready)
        self.assertFalse(metadata.requires_user_confirmation)
        self.assertFalse(metadata.external_wait)
        self.assertEqual(metadata.priority, "P1")
        self.assertEqual(metadata.risk, "HIGH")
        self.assertEqual(metadata.blocked_by, ("kinoko34077/demo#4",))
        self.assertEqual(metadata.work_order_ref, "kinoko34077/devflow#330")
        self.assertIsNone(metadata.implementation_ref)
        self.assertEqual(metadata.next_action_tag, "IMPLEMENT")

    def test_non_task_roles_never_classify_as_task(self):
        for role in ("TRACKER", "REFERENCE", "SYSTEM"):
            with self.subTest(role=role):
                metadata = rp.parse_issue_metadata(metadata_body(record_role=role))
                self.assertEqual(metadata.record_role, role)
                self.assertFalse(metadata.is_task)

    def test_duplicate_metadata_marker_fails_closed(self):
        body = metadata_body() + "\n" + metadata_body()
        with self.assertRaises(rp.ProjectionMetadataError):
            rp.parse_issue_metadata(body)

    def test_malformed_or_noncanonical_metadata_fails_closed(self):
        malformed = [
            rp.METADATA_BEGIN + "\n{not-json}\n" + rp.METADATA_END,
            metadata_body(schema_version=2),
            metadata_body(record_role="OWNER"),
            metadata_body(type="NOT_A_TYPE"),
            metadata_body(work_status="WAIT"),
            metadata_body(scope_ready="yes"),
            metadata_body(priority="P9"),
            metadata_body(risk="UNKNOWN"),
            metadata_body(next_action_tag="RUN"),
        ]
        for body in malformed:
            with self.subTest(body=body[:80]):
                with self.assertRaises(rp.ProjectionMetadataError):
                    rp.parse_issue_metadata(body)

    def test_missing_metadata_remains_visible_as_unclassified(self):
        issue = {
            "number": 12,
            "html_url": "https://github.com/kinoko34077/demo/issues/12",
            "title": "[BUG] legacy issue",
            "state": "open",
            "body": "No machine metadata here.",
            "user": {"login": "kinoko34077"},
            "assignees": [{"login": "kinoko34077"}],
            "created_at": "2026-10-01T00:00:00Z",
            "updated_at": "2026-10-02T00:00:00Z",
        }
        observed = rp.observe_issue(issue)
        self.assertEqual(observed.metadata_status, "UNCLASSIFIED")
        self.assertIsNone(observed.metadata)
        self.assertIsNone(observed.metadata_error)
        self.assertEqual(observed.number, 12)
        self.assertEqual(observed.title, "[BUG] legacy issue")

    def test_invalid_metadata_remains_observable_as_evidence_problem(self):
        issue = {
            "number": 13,
            "title": "broken",
            "state": "open",
            "body": rp.METADATA_BEGIN + "\n{}\n" + rp.METADATA_END,
        }
        observed = rp.observe_issue(issue)
        self.assertEqual(observed.metadata_status, "INVALID")
        self.assertIsNone(observed.metadata)
        self.assertTrue(observed.metadata_error)

    def test_github_native_fields_must_not_be_duplicated_in_metadata(self):
        for key, value in (
            ("state", "open"),
            ("number", 99),
            ("url", "https://example.invalid"),
            ("title", "spoof"),
            ("author", "spoof"),
            ("assignee", "spoof"),
            ("created_at", "2020-01-01T00:00:00Z"),
            ("updated_at", "2020-01-01T00:00:00Z"),
        ):
            with self.subTest(key=key):
                with self.assertRaises(rp.ProjectionMetadataError):
                    rp.parse_issue_metadata(metadata_body(**{key: value}))

    def test_observation_sources_native_facts_from_issue_object(self):
        issue = {
            "number": 21,
            "html_url": "https://github.com/kinoko34077/demo/issues/21",
            "title": "native title",
            "state": "closed",
            "body": "legacy",
            "user": {"login": "owner"},
            "assignees": [{"login": "a"}, {"login": "b"}],
            "created_at": "2026-10-01T01:02:03Z",
            "updated_at": "2026-10-03T04:05:06Z",
        }
        observed = rp.observe_issue(issue)
        self.assertEqual(
            (
                observed.number,
                observed.url,
                observed.title,
                observed.state,
                observed.author,
                observed.assignees,
                observed.created_at,
                observed.updated_at,
            ),
            (
                21,
                "https://github.com/kinoko34077/demo/issues/21",
                "native title",
                "closed",
                "owner",
                ("a", "b"),
                "2026-10-01T01:02:03Z",
                "2026-10-03T04:05:06Z",
            ),
        )


if __name__ == "__main__":
    unittest.main()
