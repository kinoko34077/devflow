import json
import unittest

from tools import human_portfolio, repository_projection as projection


def v2(payload):
    return (
        projection.ISSUE_METADATA_V2_MARKER_BEGIN + "\n"
        + json.dumps(payload, ensure_ascii=False)
        + "\n" + projection.ISSUE_METADATA_V2_MARKER_END
    )


def issue(number, body, author="OWNER"):
    return {
        "number": number,
        "title": "Non-task record",
        "body": body,
        "state": "open",
        "created_at": "2026-10-12T00:00:00Z",
        "updated_at": "2026-10-12T01:00:00Z",
        "author_association": author,
        "user": ({"id": 79015263, "login": "kinoko34077"}
                 if author == "OWNER" else {"id": 123456789, "login": "untrusted"}),
        "html_url": f"https://github.com/kinoko34077/demo/issues/{number}",
    }


class LightweightNonTaskV2Tests(unittest.TestCase):
    def test_attested_no_attention_is_classified_without_a_task(self):
        body = v2({"schema_version": 2, "record_role": "REFERENCE", "attention": "NONE"})
        meta = projection.parse_issue_metadata(body)
        self.assertEqual(meta.schema_version, 2)
        self.assertIsNone(meta.work_status)
        self.assertIsNone(meta.scope_ready)
        self.assertEqual(meta.declared_attention, "NONE")
        record = projection.classify_issue(issue(7, body))
        self.assertEqual(record.source_kind, "MACHINE")
        self.assertEqual(record.record_role, "REFERENCE")
        self.assertFalse(record.is_task)
        self.assertIsNone(record.attention_disposition)

        data = projection.build_repository_projection(
            "kinoko34077/demo", [issue(7, body)],
            observed_at="2026-10-12T01:00:00Z",
        )
        self.assertEqual(data.open_issue_count, 1)
        self.assertEqual(data.machine_task_count, 0)
        self.assertEqual(data.unclassified_count, 0)
        self.assertEqual(data.invalid_metadata_count, 0)
        self.assertEqual(human_portfolio.build_repository_human_portfolio(data).entries, ())

    def test_explicit_attention_survives_through_human_portfolio(self):
        for attention in ("NEEDS_HUMAN", "WAIT_EXTERNAL", "NEEDS_EVIDENCE"):
            with self.subTest(attention=attention):
                body = v2({"schema_version": 2, "record_role": "TRACKER", "attention": attention})
                data = projection.build_repository_projection(
                    "kinoko34077/demo", [issue(10, body)],
                    observed_at="2026-10-12T01:00:00Z",
                )
                self.assertEqual(data.records[0].attention_disposition, attention)
                queue = human_portfolio.build_repository_human_portfolio(data)
                self.assertEqual(len(queue.entries), 1)
                self.assertEqual(queue.entries[0].disposition, attention)
                self.assertEqual(queue.entries[0].role, "TRACKER")

    def test_role_only_and_task_v2_never_silently_clear_a_gate(self):
        for payload in (
            {"schema_version": 2, "record_role": "REFERENCE"},
            {"schema_version": 2, "record_role": "TASK", "attention": "NONE"},
            {"schema_version": 2, "record_role": "REFERENCE", "attention": "UNKNOWN"},
            {"schema_version": 2, "record_role": "REFERENCE", "attention": None},
            {"schema_version": 2, "record_role": "REFERENCE", "attention": "NONE", "scope_ready": True},
            {"schema_version": 2, "record_role": "REFERENCE", "attention": "NONE", "requires_user_confirmation": False},
            {"schema_version": True, "record_role": "REFERENCE", "attention": "NONE"},
        ):
            with self.subTest(payload=payload):
                record = projection.classify_issue(issue(2, v2(payload)))
                self.assertEqual(record.source_kind, "INVALID_METADATA")
                self.assertEqual(record.attention_disposition, "NEEDS_EVIDENCE")
                self.assertFalse(record.is_task)

    def test_v1_and_v2_mixed_or_duplicate_rejected(self):
        body = v2({"schema_version": 2, "record_role": "SYSTEM", "attention": "NONE"})
        valid_v1 = projection.render_issue_metadata_v1({
            "schema_version": 1, "record_role": "TASK", "type": "BUG",
            "work_status": "READY_FOR_IMPLEMENTATION", "scope_ready": True,
            "requires_user_confirmation": False, "external_wait": False,
        })
        for bad in (body + body, body + valid_v1, body.replace("V2_END", "V2_BROKEN")):
            with self.subTest(bad=bad[-60:]):
                with self.assertRaises(projection.ProjectionContractError):
                    projection.parse_issue_metadata(bad)

    def test_untrusted_v2_remains_untrusted_not_valid_or_hint(self):
        body = v2({"schema_version": 2, "record_role": "REFERENCE", "attention": "NONE"})
        record = projection.classify_issue(issue(3, body, author="NONE"))
        self.assertEqual(record.source_kind, "UNTRUSTED_METADATA")
        self.assertEqual(record.attention_disposition, "NEEDS_EVIDENCE")
        self.assertIsNone(record.metadata)

    def test_v1_task_parser_and_upsert_remain_strict(self):
        payload = {
            "schema_version": 1, "record_role": "TASK", "type": "BUG",
            "work_status": "IMPLEMENTING", "scope_ready": True,
            "requires_user_confirmation": False, "external_wait": False,
        }
        body = projection.upsert_issue_metadata_v1("Real task", payload)
        parsed = projection.parse_issue_metadata(body)
        self.assertEqual(parsed.schema_version, 1)
        self.assertTrue(parsed.is_task)
        with self.assertRaises(projection.ProjectionContractError):
            projection.upsert_issue_metadata_v1(v2({
                "schema_version": 2, "record_role": "REFERENCE", "attention": "NONE",
            }), payload)


if __name__ == "__main__":
    unittest.main()
