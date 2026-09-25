import unittest

from scripts import project_sync


class TargetSelectionTests(unittest.TestCase):
    def test_target_selector_excludes_sync_health(self):
        health = {
            "number": 41,
            "node_id": "HEALTH",
            "title": project_sync.HEALTH_TITLE,
            "state": "closed",
            "body": "",
        }

        class FakeREST:
            def get_issue(self, number):
                self.requested = number
                return health

        rest = FakeREST()
        self.assertEqual(project_sync.select_target_issue(rest, 41), [])
        self.assertEqual(rest.requested, 41)

    def test_target_selector_keeps_normal_issue(self):
        issue = {
            "number": 57,
            "node_id": "ISSUE57",
            "title": "Bug: example",
            "state": "open",
            "body": "## Priority\n\nP2",
        }

        class FakeREST:
            def get_issue(self, number):
                self.requested = number
                return issue

        rest = FakeREST()
        self.assertEqual(project_sync.select_target_issue(rest, 57), [issue])
        self.assertEqual(rest.requested, 57)


if __name__ == "__main__":
    unittest.main()
