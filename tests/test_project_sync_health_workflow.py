import unittest
from pathlib import Path


class HealthWorkflowGuardTests(unittest.TestCase):
    def test_health_issue_is_reclosed_and_not_synced(self):
        text = (Path(__file__).parents[1] / '.github' / 'workflows' / 'project-sync.yml').read_text(encoding='utf-8')
        self.assertIn('Keep Sync Health issue closed', text)
        self.assertIn("github.event.issue.title == '[SYSTEM] GitHub Project Sync Health'", text)
        self.assertIn('gh issue close', text)
        self.assertIn("github.event.issue.title != '[SYSTEM] GitHub Project Sync Health'", text)


if __name__ == '__main__':
    unittest.main()
