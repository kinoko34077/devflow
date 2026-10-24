import unittest
from pathlib import Path

from tools import github_issue_trust
from scripts import project_sync


class GitHubIssueTrustTests(unittest.TestCase):
    def test_only_allowlisted_numeric_id_is_trusted(self):
        self.assertTrue(
            github_issue_trust.is_trusted_issue_author(
                {"user": {"id": 79015263, "login": "kinoko34077"}, "author_association": "OWNER"}
            )
        )

    def test_collaborator_association_does_not_grant_trust_to_other_id(self):
        self.assertFalse(
            github_issue_trust.is_trusted_issue_author(
                {"user": {"id": 123456789, "login": "collaborator"}, "author_association": "COLLABORATOR"}
            )
        )

    def test_missing_or_login_only_identity_fails_closed(self):
        self.assertFalse(
            github_issue_trust.is_trusted_issue_author(
                {"author_association": "OWNER", "user": {"login": "kinoko34077"}}
            )
        )
        self.assertFalse(
            github_issue_trust.is_trusted_issue_author(
                {"author_association": "OWNER", "user": {"id": "79015263", "login": "kinoko34077"}}
            )
        )

    def test_login_mismatch_does_not_turn_numeric_id_into_silent_trust(self):
        self.assertFalse(
            github_issue_trust.is_trusted_issue_author(
                {"user": {"id": 79015263, "login": "renamed-or-spoofed"}, "author_association": "OWNER"}
            )
        )

    def test_project_sync_rejects_unallowlisted_collaborator_before_project_access(self):
        class NoAccess:
            def __getattr__(self, name):
                raise AssertionError(f"untrusted event must not access Project/REST: {name}")

        cfg = project_sync.RuntimeConfig(
            repository="kinoko34077/devflow",
            project_token="token",
            github_token="token",
        )
        issue = {
            "number": 7,
            "node_id": "G",
            "title": "[REPO] spoof",
            "state": "open",
            "body": "",
            "author_association": "COLLABORATOR",
            "user": {"id": 123456789, "login": "collaborator"},
        }
        self.assertEqual(
            project_sync.run_sync(
                "event-sync",
                cfg,
                rest=NoAccess(),
                gql=NoAccess(),
                event_issue=issue,
            ),
            0,
        )

    def test_project_sync_workflow_uses_numeric_principal_gate(self):
        workflow = Path(__file__).parents[1] / ".github" / "workflows" / "project-sync.yml"
        text = workflow.read_text(encoding="utf-8")
        self.assertIn("github.event.issue.user.id == 79015263", text)
        self.assertIn("github.event.comment.user.id == 79015263", text)
        self.assertIn("github.event.sender.id == 79015263", text)


if __name__ == "__main__":
    unittest.main()
