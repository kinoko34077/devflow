import unittest

from tools import reconciliation_publication as rp


DIGEST = "sha256:" + "c" * 64
HEAD = "a" * 40
CONTROL = "## Repository\n\n`owner/repository`\n\n## Work Status\n\n`IMPLEMENTING`\n"


def publication(task_ref="owner/repository#7"):
    number = task_ref.rsplit("#", 1)[1]
    return rp.build_publication(
        {
            "contract_version": "development-reconciliation.v1",
            "task_ref": task_ref,
            "task_body_sha256": DIGEST,
            "entry_ref": f"https://github.com/{task_ref.split('#', 1)[0]}/issues/{number}",
            "observed_at": "2026-09-28T05:00:00Z",
            "reason_codes": ["DIFFERENT_REVIEWER_REQUIRED"],
            "human_gate": False,
            "evidence_complete": True,
            "disposition": "NEEDS_REVIEWER",
            "different_reviewer_required": True,
            "pr_number": 12,
            "pr_head_sha": HEAD,
            "scope": "Review exact head",
        }
    )


class ReconciliationPublicationProjectionTests(unittest.TestCase):
    def test_control_projection_round_trips_machine_readable_publications(self):
        item = publication()
        body = rp.replace_publication_projection(CONTROL, "owner/repository", [item])
        parsed = rp.parse_publication_projection(body, "owner/repository")
        self.assertEqual(parsed, [item])
        self.assertIn(rp.PROJECTION_MARKER_BEGIN, body)
        self.assertIn(rp.PROJECTION_MARKER_END, body)

    def test_replacing_same_projection_is_idempotent(self):
        item = publication()
        once = rp.replace_publication_projection(CONTROL, "owner/repository", [item])
        twice = rp.replace_publication_projection(once, "owner/repository", [item])
        self.assertEqual(twice, once)

    def test_empty_desired_projection_removes_existing_block(self):
        item = publication()
        with_block = rp.replace_publication_projection(CONTROL, "owner/repository", [item])
        cleared = rp.replace_publication_projection(with_block, "owner/repository", [])
        self.assertEqual(cleared, CONTROL.rstrip())
        self.assertEqual(rp.parse_publication_projection(cleared, "owner/repository"), [])

    def test_duplicate_or_malformed_projection_markers_fail_closed(self):
        item = publication()
        with_block = rp.replace_publication_projection(CONTROL, "owner/repository", [item])
        duplicate = with_block + "\n\n" + with_block[with_block.index(rp.PROJECTION_MARKER_BEGIN):]
        with self.assertRaises(ValueError):
            rp.parse_publication_projection(duplicate, "owner/repository")

    def test_projection_rejects_task_from_another_repository(self):
        with self.assertRaises(ValueError):
            rp.replace_publication_projection(
                CONTROL,
                "owner/repository",
                [publication("other/repository#7")],
            )

    def test_projection_rejects_duplicate_logical_publication_ids(self):
        item = publication()
        with self.assertRaises(ValueError):
            rp.replace_publication_projection(
                CONTROL,
                "owner/repository",
                [item, item],
            )


if __name__ == "__main__":
    unittest.main()
