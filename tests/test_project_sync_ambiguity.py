import unittest

from scripts import project_sync


class ProjectSyncCanonicalAmbiguityTests(unittest.TestCase):
    def test_duplicate_mapped_section_is_rejected_as_ambiguous(self):
        issue = {
            "state": "open",
            "body": "## Priority\n\nP1\n\n## Priority\n\nP2",
        }
        with self.assertRaisesRegex(
            project_sync.ConfigError,
            "duplicate canonical section.*Priority",
        ):
            project_sync.desired_project_fields(issue)

    def test_duplicate_unmapped_section_does_not_block_projection(self):
        issue = {
            "state": "open",
            "body": (
                "## Priority\n\nP1\n\n"
                "## Notes\n\none\n\n"
                "## Notes\n\ntwo"
            ),
        }
        self.assertEqual(project_sync.desired_project_fields(issue), {"Priority": "P1"})


if __name__ == "__main__":
    unittest.main()
