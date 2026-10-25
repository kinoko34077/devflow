from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import project_sync_event_admission as gate


OWNER = {"id": 79015263, "login": "kinoko34077"}
BOT = {"id": 41898282, "login": "github-actions[bot]"}
OUTSIDER = {"id": 79015264, "login": "other-collaborator"}
REPO = {"full_name": "kinoko34077/devflow"}


def issue_event(*, sender=OWNER, author=OWNER, action="edited", title="[REPO] demo"):
    return {
        "repository": REPO,
        "sender": sender,
        "action": action,
        "issue": {"number": 7, "title": title, "user": author},
    }


def invoke(event, *, name="issues", principal=OWNER, triggering=None, repository="kinoko34077/devflow"):
    login = principal.get("login", "")
    return gate.admitted(
        event, event_name=name, actor_id=str(principal["id"]),
        actor_login=login,
        triggering_actor=login if triggering is None else triggering,
        repository=repository,
    )


class EventActorAdmissionTests(unittest.TestCase):
    def test_owner_issue_edits_are_admitted(self):
        for action in ("opened", "edited", "reopened", "closed"):
            with self.subTest(action=action):
                self.assertTrue(invoke(issue_event(action=action)))

    def test_owner_can_edit_verified_bot_control_candidate_but_script_must_verify_provenance(self):
        self.assertTrue(invoke(issue_event(author=BOT)))
        self.assertFalse(invoke(issue_event(author=BOT, title="[WORK ORDER] spoof")))
        self.assertTrue(invoke(issue_event(sender=BOT, author=BOT), principal=BOT))
        self.assertFalse(invoke(issue_event(sender=BOT, author=OWNER), principal=BOT))
        self.assertFalse(invoke(issue_event(sender=BOT, author=BOT, title="[WORK ORDER] spoof"), principal=BOT))

    def test_unlisted_collaborator_cannot_edit_owner_authored_issue(self):
        self.assertFalse(invoke(issue_event(sender=OUTSIDER), principal=OUTSIDER))
        self.assertFalse(invoke(issue_event(sender=OUTSIDER), principal=OWNER))
        self.assertFalse(invoke(issue_event(sender=OWNER, author=OUTSIDER), principal=OWNER))

    def test_wrong_actor_and_retriggered_user_fail_closed(self):
        self.assertFalse(invoke(issue_event(), triggering="other-collaborator"))
        self.assertFalse(invoke(issue_event(), repository="other-owner/devflow"))
        self.assertFalse(invoke(issue_event(sender=BOT), principal=OWNER))
        bad = issue_event()
        bad["repository"] = {"full_name": "other-owner/devflow"}
        self.assertFalse(invoke(bad))

    def test_malformed_numeric_ids_fail_closed(self):
        valid = issue_event()
        for value in ("", "079015263", "abc", "-1", "0", "True", "79015263.0"):
            with self.subTest(actor_id=value):
                self.assertFalse(gate.admitted(
                    valid, event_name="issues", actor_id=value,
                    actor_login="kinoko34077", triggering_actor="kinoko34077",
                    repository="kinoko34077/devflow",
                ))
        for value in (True, "79015263", None, 0, 79015264):
            with self.subTest(sender_id=value):
                event = issue_event(sender={"id": value, "login": "kinoko34077"})
                self.assertFalse(invoke(event))

    def test_issue_author_and_bot_identity_fail_closed(self):
        for user in ({"id": "79015263", "login": "kinoko34077"},
                     {"id": True, "login": "kinoko34077"},
                     {"id": 79015263, "login": "other"},
                     None):
            with self.subTest(user=user):
                self.assertFalse(invoke(issue_event(author=user)))
        for user in ({"id": 41898282, "login": "other"}, {"id": "41898282", "login": "github-actions[bot]"}):
            self.assertFalse(invoke(issue_event(author=user), principal=OWNER))

    def test_owner_commands_require_creator_commenter_and_sender(self):
        event = issue_event()
        event["comment"] = {"user": OWNER, "body": "/kinotch sync verify"}
        self.assertTrue(invoke(event, name="issue_comment"))
        event["comment"]["body"] = "/kinotch sync reconcile"
        self.assertTrue(invoke(event, name="issue_comment"))
        for creator, commenter, sender in (
            (OUTSIDER, OWNER, OWNER),
            (OWNER, OUTSIDER, OWNER),
            (OWNER, OWNER, OUTSIDER),
        ):
            with self.subTest(creator=creator, commenter=commenter, sender=sender):
                attempt = issue_event(sender=sender, author=creator)
                attempt["comment"] = {"user": commenter, "body": "/kinotch sync verify"}
                self.assertFalse(invoke(attempt, name="issue_comment"))
        event["comment"]["body"] = "/kinotch sync verify; echo injected"
        self.assertFalse(invoke(event, name="issue_comment"))
        event["comment"]["body"] = "/kinotch sync verify"
        event["issue"]["pull_request"] = {"url": "https://api.github.com/example"}
        self.assertFalse(invoke(event, name="issue_comment"))

    def test_dispatch_is_owner_only_and_explicit_mode(self):
        for mode in ("verify", "reconcile"):
            event = {"repository": REPO, "sender": OWNER, "inputs": {"mode": mode}}
            self.assertTrue(invoke(event, name="workflow_dispatch"))
            self.assertFalse(invoke(event, name="workflow_dispatch", principal=BOT))
            self.assertFalse(invoke(event, name="workflow_dispatch", triggering="other-collaborator"))
        self.assertFalse(invoke({"repository": REPO, "sender": OWNER}, name="workflow_dispatch"))
        self.assertFalse(invoke({"repository": REPO, "sender": OWNER, "inputs": {"mode": "publish"}}, name="workflow_dispatch"))
        self.assertFalse(invoke({"repository": REPO, "sender": OUTSIDER, "inputs": {"mode": "verify"}}, name="workflow_dispatch"))

    def test_read_only_preauthorization_payload_and_workflow_contract(self):
        event = issue_event()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "event.json"
            path.write_text(json.dumps(event), encoding="utf-8")
            env = {
                "GITHUB_EVENT_PATH": str(path),
                "GITHUB_EVENT_NAME": "issues",
                "GITHUB_ACTOR_ID": "79015263",
                "GITHUB_ACTOR": "kinoko34077",
                "GITHUB_TRIGGERING_ACTOR": "kinoko34077",
                "GITHUB_REPOSITORY": "kinoko34077/devflow",
            }
            self.assertTrue(gate.admitted_from_env(env))
            env["GITHUB_ACTOR_ID"] = "79015264"
            self.assertFalse(gate.admitted_from_env(env))
            env["GITHUB_ACTOR_ID"] = "79015263"
            path.write_text("{invalid", encoding="utf-8")
            self.assertFalse(gate.admitted_from_env(env))
        workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "project-sync.yml").read_text(encoding="utf-8")
        self.assertIn("  actor-admission:", workflow)
        self.assertIn("needs: actor-admission", workflow)
        self.assertIn("needs.actor-admission.outputs.admitted == 'true'", workflow)
        self.assertNotIn("PROJECTS_TOKEN", workflow.split("  sync:", 1)[0])
        self.assertNotIn("MAINTENANCE_AUDIT_TOKEN", workflow.split("  sync:", 1)[0])


if __name__ == "__main__":
    unittest.main()
