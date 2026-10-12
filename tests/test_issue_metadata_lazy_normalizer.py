import unittest

from tools import repository_projection as projection


VALID = {
    "schema_version": 1,
    "record_role": "TASK",
    "type": "BUG",
    "work_status": "IMPLEMENTING",
    "scope_ready": True,
    "requires_user_confirmation": False,
    "external_wait": False,
}


class LazyIssueMetadataNormalizerTests(unittest.TestCase):
    def test_create_v1_preserves_existing_prose_and_classifies_true_role(self):
        prose = "## Objective\n\nKeep this issue local and source-owned."
        output = projection.upsert_issue_metadata_v1(prose, VALID)
        self.assertTrue(output.startswith(prose + "\n\n"))
        self.assertEqual(output.count(projection.ISSUE_METADATA_MARKER_BEGIN), 1)
        data = projection.parse_issue_metadata(output)
        self.assertEqual(data.record_role, "TASK")
        self.assertEqual(data.work_status, "IMPLEMENTING")
        self.assertTrue(data.scope_ready)
        record = projection.classify_issue({
            "number": 1,
            "title": "[BUG] needs implementation",
            "body": output,
            "state": "open",
            "created_at": "2026-10-12T00:00:00Z",
            "updated_at": "2026-10-12T01:00:00Z",
            "author_association": "OWNER",
        })
        self.assertEqual(record.source_kind, "MACHINE")
        self.assertEqual(record.record_role, "TASK")

    def test_replace_existing_v1_preserves_suffix_and_prefix(self):
        old = "Before\n" + projection.render_issue_metadata_v1(VALID) + "\nAfter"
        changed = {**VALID, "record_role": "TRACKER", "work_status": "BLOCKED"}
        output = projection.upsert_issue_metadata_v1(old, changed)
        self.assertTrue(output.startswith("Before\n"))
        self.assertTrue(output.endswith("\nAfter"))
        self.assertEqual(output.count(projection.ISSUE_METADATA_MARKER_BEGIN), 1)
        self.assertFalse(projection.parse_issue_metadata(output).is_task)
        self.assertEqual(projection.parse_issue_metadata(output).work_status, "BLOCKED")

    def test_no_role_guess_or_defaults_for_new_issues(self):
        wrong = {k: v for k, v in VALID.items() if k != "scope_ready"}
        with self.assertRaisesRegex(projection.ProjectionContractError, "missing"):
            projection.upsert_issue_metadata_v1("[BUG] urgent", wrong)

    def test_duplicate_or_malformed_old_block_never_overwritten(self):
        block = projection.render_issue_metadata_v1(VALID)
        for bad in (
            block + "\n" + block,
            block.replace('"schema_version": 1', '"schema_version": 999'),
            projection.ISSUE_METADATA_MARKER_BEGIN + "\n{}",
        ):
            with self.subTest(body=bad[:40]):
                with self.assertRaises(projection.ProjectionContractError):
                    projection.upsert_issue_metadata_v1(bad, VALID)

    def test_future_metadata_marker_not_overwritten_by_v1(self):
        with self.assertRaisesRegex(projection.ProjectionContractError, "mixed"):
            projection.upsert_issue_metadata_v1(
                "<!-- DEVFLOW_REPOSITORY_ISSUE_METADATA_V2_BEGIN -->",
                VALID,
            )

    def test_non_task_metadata_remains_non_executable(self):
        tracker = {**VALID, "record_role": "TRACKER", "scope_ready": False}
        out = projection.upsert_issue_metadata_v1("", tracker)
        issue = {
            "number": 2, "title": "[TRACKER] roadmap", "body": out,
            "state": "open", "author_association": "OWNER",
            "created_at": "2026-10-12T00:00:00Z",
            "updated_at": "2026-10-12T00:00:00Z",
        }
        record = projection.classify_issue(issue)
        self.assertEqual(record.source_kind, "MACHINE")
        self.assertFalse(record.is_task)
        self.assertEqual(record.attention_disposition, "NEEDS_EVIDENCE")

    def test_no_git_hub_side_effects_for_repeated_render(self):
        first = projection.upsert_issue_metadata_v1("", VALID)
        self.assertEqual(projection.upsert_issue_metadata_v1(first, VALID), first)
        self.assertTrue(first.endswith("\n"))
        with self.assertRaises(projection.ProjectionContractError):
            projection.upsert_issue_metadata_v1(None, VALID)


if __name__ == "__main__":
    unittest.main()
