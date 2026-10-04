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


if __name__ == "__main__":
    unittest.main()
