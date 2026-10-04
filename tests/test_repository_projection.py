import unittest

from tools import repository_projection as rp


def metadata_block(payload: str) -> str:
    return (
        f"{rp.ISSUE_METADATA_BEGIN}\n"
        f"```json\n{payload}\n```\n"
        f"{rp.ISSUE_METADATA_END}\n"
    )


class RepositoryIssueMetadataTests(unittest.TestCase):
    def test_valid_task_metadata_parses_policy_shape(self):
        body = metadata_block(
            '{"schema_version":1,"record_role":"TASK","type":"BUG",'
            '"work_status":"READY_FOR_IMPLEMENTATION","scope_ready":true,'
            '"requires_user_confirmation":false,"external_wait":false,'
            '"priority":"P1","risk":"HIGH","blocked_by":[],'
            '"work_order_ref":null,"implementation_ref":null,'
            '"next_action_tag":"IMPLEMENT"}'
        )
        value = rp.parse_issue_metadata(body)
        self.assertEqual(value["record_role"], "TASK")
        self.assertEqual(value["type"], "BUG")
        self.assertEqual(value["work_status"], "READY_FOR_IMPLEMENTATION")
        self.assertTrue(value["scope_ready"])

    def test_missing_metadata_is_legacy_not_error(self):
        self.assertIsNone(rp.parse_issue_metadata("ordinary legacy body"))

    def test_duplicate_metadata_markers_fail_closed(self):
        block = metadata_block(
            '{"schema_version":1,"record_role":"REFERENCE"}'
        )
        with self.assertRaisesRegex(rp.RepositoryProjectionError, "duplicat|marker"):
            rp.parse_issue_metadata(block + "\n" + block)

    def test_malformed_json_fails_closed(self):
        with self.assertRaisesRegex(rp.RepositoryProjectionError, "JSON|json|invalid"):
            rp.parse_issue_metadata(metadata_block("{not-json}"))

    def test_task_requires_minimum_actionability_fields(self):
        body = metadata_block(
            '{"schema_version":1,"record_role":"TASK","type":"BUG"}'
        )
        with self.assertRaisesRegex(rp.RepositoryProjectionError, "TASK|required|work_status"):
            rp.parse_issue_metadata(body)

    def test_unknown_enum_fails_closed(self):
        body = metadata_block(
            '{"schema_version":1,"record_role":"TASK","type":"MADE_UP",'
            '"work_status":"READY_FOR_IMPLEMENTATION","scope_ready":true,'
            '"requires_user_confirmation":false,"external_wait":false}'
        )
        with self.assertRaisesRegex(rp.RepositoryProjectionError, "type|MADE_UP"):
            rp.parse_issue_metadata(body)


class RepositoryIssueClassificationTests(unittest.TestCase):
    def test_open_reference_issue_is_not_actionable(self):
        issue = {
            "number": 12,
            "title": "[SPEC] projection semantics",
            "state": "open",
            "body": metadata_block(
                '{"schema_version":1,"record_role":"REFERENCE"}'
            ),
        }
        result = rp.classify_issue(issue)
        self.assertEqual(result["classification_source"], "MACHINE")
        self.assertEqual(result["record_role"], "REFERENCE")
        self.assertFalse(result["actionable"])

    def test_legacy_work_order_hint_does_not_become_action_authority(self):
        issue = {
            "number": 13,
            "title": "[WORK ORDER] legacy task",
            "state": "open",
            "body": "legacy body without machine marker",
        }
        result = rp.classify_issue(issue)
        self.assertEqual(result["classification_source"], "LEGACY_HINT")
        self.assertEqual(result["record_role"], None)
        self.assertEqual(result["record_role_hint"], "TASK")
        self.assertFalse(result["actionable"])

    def test_machine_task_can_be_actionable_only_with_explicit_fields(self):
        issue = {
            "number": 14,
            "title": "Fix parser",
            "state": "open",
            "body": metadata_block(
                '{"schema_version":1,"record_role":"TASK","type":"BUG",'
                '"work_status":"READY_FOR_IMPLEMENTATION","scope_ready":true,'
                '"requires_user_confirmation":false,"external_wait":false}'
            ),
        }
        result = rp.classify_issue(issue)
        self.assertEqual(result["classification_source"], "MACHINE")
        self.assertEqual(result["record_role"], "TASK")
        self.assertTrue(result["actionable"])


class RepositoryProjectionModelTests(unittest.TestCase):
    def _task_body(
        self,
        *,
        work_status="READY_FOR_IMPLEMENTATION",
        scope_ready=True,
        requires_user_confirmation=False,
        external_wait=False,
        issue_type="BUG",
        blocked_by=None,
    ):
        payload = {
            "schema_version": 1,
            "record_role": "TASK",
            "type": issue_type,
            "work_status": work_status,
            "scope_ready": scope_ready,
            "requires_user_confirmation": requires_user_confirmation,
            "external_wait": external_wait,
            "blocked_by": blocked_by or [],
        }
        import json

        return metadata_block(json.dumps(payload, separators=(",", ":")))

    def test_projection_separates_newest_from_recent_activity(self):
        issues = [
            {
                "number": 1,
                "title": "Older but recently edited",
                "state": "open",
                "body": self._task_body(),
                "created_at": "2026-10-01T00:00:00Z",
                "updated_at": "2026-10-04T03:00:00Z",
                "html_url": "https://github.com/kinoko34077/example/issues/1",
            },
            {
                "number": 2,
                "title": "Newest created",
                "state": "open",
                "body": "[SPEC] legacy reference",
                "created_at": "2026-10-03T00:00:00Z",
                "updated_at": "2026-10-03T01:00:00Z",
                "html_url": "https://github.com/kinoko34077/example/issues/2",
            },
        ]
        result = rp.build_repository_projection(
            "kinoko34077/example",
            issues,
            observed_at="2026-10-04T04:00:00Z",
        )
        self.assertEqual(result["newest_open_issue_ref"], "kinoko34077/example#2")
        self.assertEqual(result["most_recently_active_issue_ref"], "kinoko34077/example#1")

    def test_projection_counts_machine_legacy_and_invalid_separately(self):
        issues = [
            {
                "number": 1,
                "title": "Machine task",
                "state": "open",
                "body": self._task_body(issue_type="BUG"),
            },
            {
                "number": 2,
                "title": "[WORK ORDER] legacy",
                "state": "open",
                "body": "legacy",
            },
            {
                "number": 3,
                "title": "Unknown legacy",
                "state": "open",
                "body": "legacy",
            },
            {
                "number": 4,
                "title": "Broken machine",
                "state": "open",
                "body": metadata_block("{not-json}"),
            },
        ]
        result = rp.build_repository_projection(
            "kinoko34077/example",
            issues,
            observed_at="2026-10-04T04:00:00Z",
        )
        self.assertEqual(result["counts"]["open_issues"], 4)
        self.assertEqual(result["counts"]["machine_tasks"], 1)
        self.assertEqual(result["counts"]["legacy_or_unclassified"], 2)
        self.assertEqual(result["counts"]["invalid_machine"], 1)
        self.assertEqual(result["counts"]["by_type"], {"BUG": 1})

    def test_projection_keeps_actionable_blocked_waiting_and_human_axes_separate(self):
        issues = [
            {
                "number": 1,
                "title": "ready",
                "state": "open",
                "body": self._task_body(),
            },
            {
                "number": 2,
                "title": "blocked",
                "state": "open",
                "body": self._task_body(
                    work_status="BLOCKED",
                    blocked_by=["kinoko34077/example#99"],
                ),
            },
            {
                "number": 3,
                "title": "external",
                "state": "open",
                "body": self._task_body(
                    work_status="BLOCKED",
                    external_wait=True,
                ),
            },
            {
                "number": 4,
                "title": "human",
                "state": "open",
                "body": self._task_body(
                    requires_user_confirmation=True,
                ),
            },
        ]
        result = rp.build_repository_projection(
            "kinoko34077/example",
            issues,
            observed_at="2026-10-04T04:00:00Z",
        )
        self.assertEqual(result["actionable_refs"], ["kinoko34077/example#1"])
        self.assertEqual(result["blocked_refs"], [
            "kinoko34077/example#2",
            "kinoko34077/example#3",
        ])
        self.assertEqual(result["waiting_refs"], ["kinoko34077/example#3"])
        self.assertEqual(result["needs_human_refs"], ["kinoko34077/example#4"])

    def test_source_failure_projection_is_safe_and_explicit(self):
        result = rp.build_repository_projection(
            "kinoko34077/example",
            [],
            observed_at="2026-10-04T04:00:00Z",
            source_status="ERROR",
            source_error="GitHub unavailable",
        )
        self.assertEqual(result["source_status"], "ERROR")
        self.assertEqual(result["source_error"], "GitHub unavailable")
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["actionable_refs"], [])
        self.assertEqual(result["counts"]["open_issues"], 0)

    def test_invalid_machine_metadata_never_becomes_actionable(self):
        issues = [
            {
                "number": 7,
                "title": "[WORK ORDER] broken machine block",
                "state": "open",
                "body": metadata_block("{not-json}"),
            },
        ]
        result = rp.build_repository_projection(
            "kinoko34077/example",
            issues,
            observed_at="2026-10-04T04:00:00Z",
        )
        self.assertEqual(result["actionable_refs"], [])
        self.assertEqual(result["counts"]["invalid_machine"], 1)
        self.assertEqual(
            result["issues"][0]["classification_source"],
            "INVALID_MACHINE",
        )


if __name__ == "__main__":
    unittest.main()
