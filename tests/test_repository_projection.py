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
        payload = VALID_TASK.replace(',\n  "external_wait": false', "")
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


class RepositoryIssueClassificationTests(unittest.TestCase):
    def test_legacy_canonical_type_prefix_is_hint_not_task(self):
        for title, expected_type in (
            ("[BUG] broken", "BUG"),
            ("[P1][BUG] urgent broken", "BUG"),
            ("[SPEC] define contract", "SPEC"),
            ("[DOCS] update docs", "DOCS"),
        ):
            with self.subTest(title=title):
                record = repository_projection.classify_issue(
                    {
                        "number": 7,
                        "title": title,
                        "state": "open",
                        "body": "",
                        "created_at": "2026-10-04T00:00:00Z",
                        "updated_at": "2026-10-04T01:00:00Z",
                    }
                )
                self.assertEqual(record.source_kind, "LEGACY_HINT")
                self.assertEqual(record.type, expected_type)
                self.assertFalse(record.is_task)
                self.assertIsNone(record.metadata_error)

    def test_noncanonical_legacy_prefix_remains_unclassified(self):
        for title in (
            "[REMEDIATION/P1] repair",
            "[HUMAN GATE] device check",
            "[WORK ORDER] task",
            "ordinary issue",
        ):
            with self.subTest(title=title):
                record = repository_projection.classify_issue(
                    {
                        "number": 8,
                        "title": title,
                        "state": "open",
                        "body": "",
                        "created_at": "2026-10-04T00:00:00Z",
                        "updated_at": "2026-10-04T01:00:00Z",
                    }
                )
                self.assertEqual(record.source_kind, "UNCLASSIFIED")
                self.assertIsNone(record.type)
                self.assertFalse(record.is_task)

    def test_malformed_metadata_does_not_fall_back_to_title_hint(self):
        record = repository_projection.classify_issue(
            {
                "number": 9,
                "title": "[BUG] malformed explicit metadata",
                "state": "open",
                "body": f"{BEGIN}\n{{not json}}\n{END}",
                "created_at": "2026-10-04T00:00:00Z",
                "updated_at": "2026-10-04T01:00:00Z",
            }
        )
        self.assertEqual(record.source_kind, "INVALID_METADATA")
        self.assertIsNone(record.type)
        self.assertFalse(record.is_task)
        self.assertIn("malformed", record.metadata_error)

    def test_machine_metadata_is_only_task_authority(self):
        record = repository_projection.classify_issue(
            {
                "number": 10,
                "title": "[BUG] explicit metadata",
                "state": "open",
                "body": block(VALID_TASK),
                "created_at": "2026-10-04T00:00:00Z",
                "updated_at": "2026-10-04T01:00:00Z",
            }
        )
        self.assertEqual(record.source_kind, "MACHINE")
        self.assertEqual(record.type, "BUG")
        self.assertTrue(record.is_task)

    def test_github_native_identity_and_times_come_from_issue_object(self):
        record = repository_projection.classify_issue(
            {
                "number": 11,
                "title": "[BUG] native fields",
                "state": "open",
                "body": block(VALID_TASK),
                "created_at": "2026-10-04T02:00:00Z",
                "updated_at": "2026-10-04T03:00:00Z",
                "html_url": "https://github.com/o/r/issues/11",
            }
        )
        self.assertEqual(record.number, 11)
        self.assertEqual(record.title, "[BUG] native fields")
        self.assertEqual(record.state, "open")
        self.assertEqual(record.created_at, "2026-10-04T02:00:00Z")
        self.assertEqual(record.updated_at, "2026-10-04T03:00:00Z")
        self.assertEqual(record.html_url, "https://github.com/o/r/issues/11")



class RepositoryProjectionCoreTests(unittest.TestCase):
    def _issue(
        self,
        number,
        *,
        title="[BUG] issue",
        body="",
        created_at="2026-10-04T00:00:00Z",
        updated_at="2026-10-04T00:00:00Z",
        state="open",
    ):
        return {
            "number": number,
            "title": title,
            "state": state,
            "body": body,
            "created_at": created_at,
            "updated_at": updated_at,
            "html_url": f"https://github.com/o/r/issues/{number}",
        }

    def _machine(self, **replacements):
        payload = VALID_TASK
        for old, new in replacements.items():
            payload = payload.replace(old, new)
        return block(payload)

    def test_projection_supports_zero_to_many_machine_tasks(self):
        empty = repository_projection.build_repository_projection(
            "o/r",
            [],
            observed_at="2026-10-04T04:00:00Z",
        )
        self.assertEqual(empty.open_issue_count, 0)
        self.assertEqual(empty.machine_task_count, 0)
        self.assertEqual(empty.task_records, ())

        issues = [
            self._issue(1, body=block(VALID_TASK)),
            self._issue(
                2,
                body=block(
                    VALID_TASK.replace(
                        '"work_status": "READY_FOR_IMPLEMENTATION"',
                        '"work_status": "IMPLEMENTING"',
                    )
                ),
            ),
            self._issue(
                3,
                title="[SPEC] tracker",
                body=block(VALID_TASK.replace('"TASK"', '"TRACKER"')),
            ),
            self._issue(4, title="[BUG] legacy", body=""),
        ]
        projection = repository_projection.build_repository_projection(
            "o/r",
            issues,
            observed_at="2026-10-04T04:00:00Z",
        )
        self.assertEqual(projection.open_issue_count, 4)
        self.assertEqual(projection.machine_task_count, 2)
        self.assertEqual([item.number for item in projection.task_records], [1, 2])
        self.assertEqual([item.number for item in projection.ready_tasks], [1])
        self.assertEqual([item.number for item in projection.implementing_tasks], [2])

    def test_newest_open_and_recently_active_are_distinct(self):
        issues = [
            self._issue(
                10,
                created_at="2026-10-04T03:00:00Z",
                updated_at="2026-10-04T03:10:00Z",
            ),
            self._issue(
                11,
                created_at="2026-10-04T02:00:00Z",
                updated_at="2026-10-04T03:30:00Z",
            ),
        ]
        projection = repository_projection.build_repository_projection(
            "o/r",
            issues,
            observed_at="2026-10-04T04:00:00Z",
        )
        self.assertEqual(projection.newest_open_issue.number, 10)
        self.assertEqual(projection.recently_active_issue.number, 11)

    def test_projection_separates_machine_type_counts_from_legacy_hints(self):
        issues = [
            self._issue(20, body=block(VALID_TASK)),
            self._issue(
                21,
                title="[SPEC] machine tracker",
                body=block(
                    VALID_TASK.replace('"TASK"', '"TRACKER"').replace(
                        '"type": "BUG"',
                        '"type": "SPEC"',
                    )
                ),
            ),
            self._issue(22, title="[BUG] legacy", body=""),
            self._issue(23, title="ordinary issue", body=""),
            self._issue(24, title="[BUG] bad explicit", body=f"{BEGIN}\n{{bad}}\n{END}"),
            self._issue(25, title="[BUG] closed", body="", state="closed"),
        ]
        projection = repository_projection.build_repository_projection(
            "o/r",
            issues,
            observed_at="2026-10-04T04:00:00Z",
        )
        self.assertEqual(projection.open_issue_count, 5)
        self.assertEqual(projection.machine_type_counts, {"BUG": 1, "SPEC": 1})
        self.assertEqual(projection.legacy_hint_type_counts, {"BUG": 1})
        self.assertEqual(projection.legacy_hint_count, 1)
        self.assertEqual(projection.unclassified_count, 1)
        self.assertEqual(projection.invalid_metadata_count, 1)

    def test_projection_source_failure_is_explicit_and_not_fresh(self):
        projection = repository_projection.build_repository_projection(
            "o/r",
            [],
            observed_at="2026-10-04T04:00:00Z",
            source_status="UNAVAILABLE",
            source_error="GitHub read failed",
        )
        self.assertEqual(projection.source_status, "UNAVAILABLE")
        self.assertEqual(projection.source_freshness, "UNKNOWN")
        self.assertEqual(projection.source_error, "GitHub read failed")
        self.assertEqual(projection.open_issue_count, 0)
        self.assertEqual(projection.task_records, ())


if __name__ == "__main__":
    unittest.main()
