import unittest

from tools import repository_projection


BEGIN = "<!-- DEVFLOW_REPOSITORY_ISSUE_METADATA_V1_BEGIN -->"
END = "<!-- DEVFLOW_REPOSITORY_ISSUE_METADATA_V1_END -->"


def block(payload: str) -> str:
    return f"prefix\n{BEGIN}\n{payload}\n{END}\nsuffix\n"


VALID_TASK = """{
  "schema_version": 1,
  "record_role": "TASK",
  "type": "BUG",
  "work_status": "READY_FOR_IMPLEMENTATION",
  "scope_ready": true,
  "requires_user_confirmation": false,
  "external_wait": false
}"""


class RepositoryIssueMetadataContractTests(unittest.TestCase):
    def test_valid_task_metadata_is_parsed(self):
        metadata = repository_projection.parse_issue_metadata(block(VALID_TASK))
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.schema_version, 1)
        self.assertEqual(metadata.record_role, "TASK")
        self.assertEqual(metadata.type, "BUG")
        self.assertEqual(metadata.work_status, "READY_FOR_IMPLEMENTATION")
        self.assertTrue(metadata.scope_ready)
        self.assertFalse(metadata.requires_user_confirmation)
        self.assertFalse(metadata.external_wait)
        self.assertTrue(metadata.is_task)

    def test_non_task_roles_never_report_is_task(self):
        for role in ("TRACKER", "REFERENCE", "SYSTEM"):
            with self.subTest(role=role):
                payload = VALID_TASK.replace('"TASK"', f'"{role}"')
                metadata = repository_projection.parse_issue_metadata(block(payload))
                self.assertEqual(metadata.record_role, role)
                self.assertFalse(metadata.is_task)

    def test_duplicate_marker_pair_fails_closed(self):
        body = block(VALID_TASK) + "\n" + block(VALID_TASK)
        with self.assertRaisesRegex(
            repository_projection.ProjectionContractError,
            "exactly one marker pair",
        ):
            repository_projection.parse_issue_metadata(body)

    def test_duplicate_json_key_fails_closed(self):
        payload = """{
  "schema_version": 1,
  "record_role": "TASK",
  "record_role": "TRACKER",
  "type": "BUG",
  "work_status": "READY_FOR_IMPLEMENTATION",
  "scope_ready": true,
  "requires_user_confirmation": false,
  "external_wait": false
}"""
        with self.assertRaisesRegex(
            repository_projection.ProjectionContractError,
            "duplicate JSON key",
        ):
            repository_projection.parse_issue_metadata(block(payload))

    def test_malformed_json_fails_closed(self):
        with self.assertRaisesRegex(
            repository_projection.ProjectionContractError,
            "malformed",
        ):
            repository_projection.parse_issue_metadata(
                f"{BEGIN}\n{{not json}}\n{END}"
            )

    def test_unsupported_schema_version_fails_closed(self):
        payload = VALID_TASK.replace('"schema_version": 1', '"schema_version": 2')
        with self.assertRaisesRegex(
            repository_projection.ProjectionContractError,
            "schema_version",
        ):
            repository_projection.parse_issue_metadata(block(payload))

    def test_invalid_enum_fails_closed(self):
        payload = VALID_TASK.replace('"record_role": "TASK"', '"record_role": "WORK"')
        with self.assertRaisesRegex(
            repository_projection.ProjectionContractError,
            "record_role",
        ):
            repository_projection.parse_issue_metadata(block(payload))

    def test_invalid_type_fails_closed_against_workflow_contract(self):
        payload = VALID_TASK.replace('"type": "BUG"', '"type": "UNKNOWN_TYPE"')
        with self.assertRaisesRegex(
            repository_projection.ProjectionContractError,
            "type",
        ):
            repository_projection.parse_issue_metadata(block(payload))

    def test_invalid_work_status_fails_closed_against_workflow_contract(self):
        payload = VALID_TASK.replace(
            '"work_status": "READY_FOR_IMPLEMENTATION"',
            '"work_status": "IN_PROGRESS"',
        )
        with self.assertRaisesRegex(
            repository_projection.ProjectionContractError,
            "work_status",
        ):
            repository_projection.parse_issue_metadata(block(payload))

    def test_required_boolean_fields_are_strict_booleans(self):
        for field in ("scope_ready", "requires_user_confirmation", "external_wait"):
            with self.subTest(field=field):
                payload = VALID_TASK.replace(
                    f'"{field}": false',
                    f'"{field}": 0',
                ).replace(
                    f'"{field}": true',
                    f'"{field}": 1',
                )
                with self.assertRaisesRegex(
                    repository_projection.ProjectionContractError,
                    field,
                ):
                    repository_projection.parse_issue_metadata(block(payload))

    def test_optional_priority_and_risk_use_shared_workflow_vocabulary(self):
        payload = VALID_TASK.replace(
            '  "external_wait": false',
            '  "external_wait": false,\n  "priority": "P1",\n  "risk": "HIGH"',
        )
        metadata = repository_projection.parse_issue_metadata(block(payload))
        self.assertEqual(metadata.priority, "P1")
        self.assertEqual(metadata.risk, "HIGH")

        invalid = payload.replace('"priority": "P1"', '"priority": "P9"')
        with self.assertRaisesRegex(
            repository_projection.ProjectionContractError,
            "priority",
        ):
            repository_projection.parse_issue_metadata(block(invalid))

    def test_missing_required_field_fails_closed(self):
        payload = VALID_TASK.replace('  "external_wait": false\n', "")
        with self.assertRaisesRegex(
            repository_projection.ProjectionContractError,
            "missing",
        ):
            repository_projection.parse_issue_metadata(block(payload))

    def test_unknown_field_fails_closed(self):
        payload = VALID_TASK.replace(
            '  "external_wait": false',
            '  "external_wait": false,\n  "surprise": "value"',
        )
        with self.assertRaisesRegex(
            repository_projection.ProjectionContractError,
            "unknown",
        ):
            repository_projection.parse_issue_metadata(block(payload))

    def test_github_native_fields_are_not_owned_by_metadata(self):
        for key, value in (
            ("number", "7"),
            ("title", '"[BUG] x"'),
            ("state", '"open"'),
            ("created_at", '"2026-10-04T00:00:00Z"'),
            ("updated_at", '"2026-10-04T00:00:00Z"'),
            ("author", '"kinoko34077"'),
            ("assignee", '"kinoko34077"'),
        ):
            with self.subTest(key=key):
                payload = VALID_TASK.replace(
                    '  "external_wait": false',
                    f'  "external_wait": false,\n  "{key}": {value}',
                )
                with self.assertRaisesRegex(
                    repository_projection.ProjectionContractError,
                    "unknown",
                ):
                    repository_projection.parse_issue_metadata(block(payload))

    def test_missing_metadata_block_is_visible_as_absent_not_error(self):
        self.assertIsNone(
            repository_projection.parse_issue_metadata(
                "## Work\n\nordinary legacy Issue body\n"
            )
        )


if __name__ == "__main__":
    unittest.main()
