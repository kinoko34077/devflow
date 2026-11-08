from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from tools import project_sync_event_admission as gate


OWNER = {"id": 79015263, "login": "kinoko34077"}
BOT = {"id": 41898282, "login": "github-actions[bot]"}
OUTSIDER = {"id": 79015264, "login": "other-collaborator"}
RENAMED_OWNER = {"id": 79015263, "login": "owner-renamed"}
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
    def test_generated_marker_only_control_edit_skips_project_sync(self):
        from tools import human_portfolio_cache, repository_projection_cache

        repository = "kinoko34077/demo"
        def block(begin, end, schema, generation):
            return (
                begin + "\n" + json.dumps({
                    "schema_version": schema,
                    "repository": repository,
                    "generation_id": generation,
                }, sort_keys=True) + "\n" + end
            )

        def body(p, h, next_action="Cross-repository gate unchanged."):
            return (
                "## Repository\n\n`kinoko34077/demo`\n\n"
                "## Next Action\n\n" + next_action + "\n\n"
                + block(repository_projection_cache.CACHE_MARKER_BEGIN,
                        repository_projection_cache.CACHE_MARKER_END,
                        repository_projection_cache.CACHE_SCHEMA_VERSION, p)
                + "\n\n"
                + block(human_portfolio_cache.CACHE_MARKER_BEGIN,
                        human_portfolio_cache.CACHE_MARKER_END,
                        human_portfolio_cache.CACHE_SCHEMA_VERSION, h)
            )

        original = body("old", "old")
        changed = body("new", "new")
        event = issue_event()
        event["issue"].update({"body": changed, "state": "open"})
        event["changes"] = {"body": {"from": original}}

        self.assertEqual(
            gate.admission_decision(
                event, event_name="issues", actor_id="79015263",
                actor_login="kinoko34077", triggering_actor="kinoko34077",
                repository="kinoko34077/devflow",
            ),
            gate.CACHE_ONLY_EDIT,
        )
        self.assertFalse(invoke(event))
        # This also applies to the already-allowed verified bot actor;
        # no new author class receives admission.
        event["sender"] = BOT
        event["issue"]["user"] = BOT
        self.assertFalse(invoke(event, principal=BOT))
        event["sender"] = OWNER
        event["issue"]["user"] = OWNER

        # Any independent source field change must preserve the normal sync.
        event["issue"]["body"] = body("new", "new", "Human Gate changed.")
        self.assertTrue(invoke(event))
        event["issue"]["body"] = changed
        event["changes"]["title"] = {"from": "[REPO] old"}
        self.assertTrue(invoke(event))
        del event["changes"]["title"]

        # No old-body evidence, missing blocks, invalid or duplicated marker
        # means normal admission: unknown evidence is never a silent skip.
        for old in ("no machine blocks", original.replace(
            human_portfolio_cache.CACHE_MARKER_END, ""),
            original + "\n" + repository_projection_cache.CACHE_MARKER_BEGIN,
        ):
            with self.subTest(old=old[-60:]):
                event["changes"]["body"]["from"] = old
                self.assertTrue(invoke(event))
        event["changes"]["body"]["from"] = original
        event["issue"]["state"] = "closed"
        self.assertTrue(invoke(event))
        event["issue"]["state"] = "open"
        event["action"] = "reopened"
        self.assertTrue(invoke(event))
        event["action"] = "edited"
        self.assertFalse(invoke(event, triggering="other-collaborator"))

    def test_generated_marker_only_event_does_not_allocate_sync_job(self):
        from tools import human_portfolio_cache, repository_projection_cache

        def marker(begin, end, schema, generation):
            return begin + "\n" + json.dumps({
                "repository": "kinoko34077/demo",
                "schema_version": schema,
                "generation_id": generation,
            }) + "\n" + end

        old = "\n".join((
            "## Repository", "`kinoko34077/demo`",
            marker(repository_projection_cache.CACHE_MARKER_BEGIN,
                   repository_projection_cache.CACHE_MARKER_END,
                   repository_projection_cache.CACHE_SCHEMA_VERSION, "old"),
            marker(human_portfolio_cache.CACHE_MARKER_BEGIN,
                   human_portfolio_cache.CACHE_MARKER_END,
                   human_portfolio_cache.CACHE_SCHEMA_VERSION, "old"),
        ))
        new = old.replace('"old"', '"new"')
        event = issue_event()
        event["issue"].update({"body": new, "state": "open"})
        event["changes"] = {"body": {"from": old}}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            event_path = root / "event.json"
            output_path = root / "output.txt"
            event_path.write_text(json.dumps(event), encoding="utf-8")
            env = {
                "GITHUB_EVENT_PATH": str(event_path),
                "GITHUB_EVENT_NAME": "issues",
                "GITHUB_ACTOR_ID": "79015263",
                "GITHUB_ACTOR": "kinoko34077",
                "GITHUB_TRIGGERING_ACTOR": "kinoko34077",
                "GITHUB_REPOSITORY": "kinoko34077/devflow",
                "GITHUB_OUTPUT": str(output_path),
            }
            with patch.dict(gate.os.environ, env), redirect_stdout(StringIO()):
                self.assertEqual(gate.main(), 0)
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "admitted=false\n",
            )

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

    def test_owner_login_mismatch_is_classified_only_with_consistent_numeric_actor(self):
        def decision(event, name, actor_login):
            return gate.admission_decision(
                event,
                event_name=name,
                actor_id="79015263",
                actor_login=actor_login,
                triggering_actor=actor_login,
                repository="kinoko34077/devflow",
            )

        renamed_actor_issue = issue_event(sender=RENAMED_OWNER, author=RENAMED_OWNER)
        self.assertEqual(
            decision(renamed_actor_issue, "issues", "owner-renamed"),
            "EXPECTED_LOGIN_RECONCILIATION_REQUIRED",
        )
        self.assertFalse(invoke(renamed_actor_issue, principal=RENAMED_OWNER))

        renamed_actor_comment = issue_event(
            sender=RENAMED_OWNER, author=RENAMED_OWNER, action="created"
        )
        renamed_actor_comment["comment"] = {
            "user": RENAMED_OWNER,
            "body": "/kinotch sync verify",
        }
        self.assertEqual(
            decision(renamed_actor_comment, "issue_comment", "owner-renamed"),
            "EXPECTED_LOGIN_RECONCILIATION_REQUIRED",
        )
        self.assertFalse(invoke(renamed_actor_comment, name="issue_comment", principal=RENAMED_OWNER))

        renamed_actor_dispatch = {
            "repository": REPO,
            "sender": RENAMED_OWNER,
            "inputs": {"mode": "verify"},
        }
        self.assertEqual(
            decision(renamed_actor_dispatch, "workflow_dispatch", "owner-renamed"),
            "EXPECTED_LOGIN_RECONCILIATION_REQUIRED",
        )
        self.assertFalse(invoke(renamed_actor_dispatch, name="workflow_dispatch", principal=RENAMED_OWNER))

        renamed_author = issue_event(author=RENAMED_OWNER)
        self.assertEqual(
            gate.admission_decision(
                renamed_author,
                event_name="issues",
                actor_id="79015263",
                actor_login="kinoko34077",
                triggering_actor="kinoko34077",
                repository="kinoko34077/devflow",
            ),
            "EXPECTED_LOGIN_RECONCILIATION_REQUIRED",
        )
        self.assertFalse(invoke(renamed_author))

        incoherent_sender = issue_event(sender=OUTSIDER, author=RENAMED_OWNER)
        self.assertEqual(
            decision(incoherent_sender, "issues", "owner-renamed"),
            "UNTRUSTED",
        )
        mismatched_sender = issue_event(sender=RENAMED_OWNER, author=OWNER)
        self.assertEqual(
            decision(mismatched_sender, "issues", "kinoko34077"),
            "UNTRUSTED",
        )

        invalid_dispatch = {
            "repository": REPO,
            "sender": RENAMED_OWNER,
            "inputs": {"mode": "unknown"},
        }
        self.assertEqual(
            decision(invalid_dispatch, "workflow_dispatch", "owner-renamed"),
            "UNTRUSTED",
        )
        invalid_comment = dict(renamed_actor_comment, action="edited")
        self.assertEqual(
            decision(invalid_comment, "issue_comment", "owner-renamed"),
            "UNTRUSTED",
        )
        invalid_comment["action"] = "created"
        invalid_comment["comment"]["body"] = "ordinary comment"
        self.assertEqual(
            decision(invalid_comment, "issue_comment", "owner-renamed"),
            "UNTRUSTED",
        )
        malformed_author_event = issue_event(author=RENAMED_OWNER, action="unsupported")
        self.assertEqual(
            gate.admission_decision(
                malformed_author_event,
                event_name="issues",
                actor_id="79015263",
                actor_login="kinoko34077",
                triggering_actor="kinoko34077",
                repository="kinoko34077/devflow",
            ),
            "UNTRUSTED",
        )
        malformed_comment = issue_event(author=OWNER, action="created")
        malformed_comment["comment"] = {"user": RENAMED_OWNER, "body": "ordinary comment"}
        self.assertEqual(
            gate.admission_decision(
                malformed_comment,
                event_name="issue_comment",
                actor_id="79015263",
                actor_login="kinoko34077",
                triggering_actor="kinoko34077",
                repository="kinoko34077/devflow",
            ),
            "UNTRUSTED",
        )

    def test_no_secret_admission_reports_login_mismatch_but_keeps_admitted_false(self):
        comment = issue_event(sender=RENAMED_OWNER, author=RENAMED_OWNER, action="created")
        comment["comment"] = {"user": RENAMED_OWNER, "body": "/kinotch sync verify"}
        renamed_issue_author = issue_event(sender=OWNER, author=RENAMED_OWNER)
        renamed_comment_author = issue_event(sender=OWNER, author=RENAMED_OWNER, action="created")
        renamed_comment_author["comment"] = {"user": OWNER, "body": "/kinotch sync verify"}
        renamed_commenter = issue_event(sender=OWNER, author=OWNER, action="created")
        renamed_commenter["comment"] = {"user": RENAMED_OWNER, "body": "/kinotch sync reconcile"}
        events = (
            ("issues", issue_event(sender=RENAMED_OWNER, author=RENAMED_OWNER), "owner-renamed"),
            ("issue_comment", comment, "owner-renamed"),
            (
                "workflow_dispatch",
                {"repository": REPO, "sender": RENAMED_OWNER, "inputs": {"mode": "reconcile"}},
                "owner-renamed",
            ),
            ("issues", renamed_issue_author, "kinoko34077"),
            ("issue_comment", renamed_comment_author, "kinoko34077"),
            ("issue_comment", renamed_commenter, "kinoko34077"),
        )
        for name, event, actor_login in events:
            with self.subTest(event_name=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                event_path = root / "event.json"
                output_path = root / "output.txt"
                summary_path = root / "summary.md"
                event_path.write_text(json.dumps(event), encoding="utf-8")
                env = {
                    "GITHUB_EVENT_PATH": str(event_path),
                    "GITHUB_EVENT_NAME": name,
                    "GITHUB_ACTOR_ID": "79015263",
                    "GITHUB_ACTOR": actor_login,
                    "GITHUB_TRIGGERING_ACTOR": actor_login,
                    "GITHUB_REPOSITORY": "kinoko34077/devflow",
                    "GITHUB_OUTPUT": str(output_path),
                    "GITHUB_STEP_SUMMARY": str(summary_path),
                }
                stdout = StringIO()
                with patch.dict(gate.os.environ, env), redirect_stdout(stdout):
                    exit_code = gate.main()

                self.assertEqual(exit_code, 0)
                self.assertIn("admitted=false", output_path.read_text(encoding="utf-8"))
                self.assertIn("EXPECTED_LOGIN_RECONCILIATION_REQUIRED", stdout.getvalue())
                self.assertIn(
                    "EXPECTED_LOGIN_RECONCILIATION_REQUIRED",
                    summary_path.read_text(encoding="utf-8"),
                )
                self.assertNotIn("owner-renamed", stdout.getvalue())
                self.assertNotIn("owner-renamed", summary_path.read_text(encoding="utf-8"))

    def test_owner_commands_require_creator_commenter_and_sender(self):
        event = issue_event(action="created")
        event["comment"] = {"user": OWNER, "body": "/kinotch sync verify"}
        self.assertTrue(invoke(event, name="issue_comment"))
        event["comment"]["body"] = "/kinotch sync reconcile"
        self.assertTrue(invoke(event, name="issue_comment"))
        for creator, commenter, sender in (
            (OUTSIDER, OWNER, OWNER),
            (OWNER, OUTSIDER, OWNER),
            (OWNER, OWNER, OUTSIDER),
            (OWNER, {"id": OWNER["id"]}, OWNER),
            (OWNER, {"id": OWNER["id"], "login": None}, OWNER),
        ):
            with self.subTest(creator=creator, commenter=commenter, sender=sender):
                attempt = issue_event(sender=sender, author=creator, action="created")
                attempt["comment"] = {"user": commenter, "body": "/kinotch sync verify"}
                self.assertFalse(invoke(attempt, name="issue_comment"))
        event["comment"]["body"] = "/kinotch sync verify; echo injected"
        self.assertFalse(invoke(event, name="issue_comment"))
        event["comment"]["body"] = "/kinotch sync verify"
        event["issue"]["pull_request"] = {"url": "https://api.github.com/example"}
        self.assertFalse(invoke(event, name="issue_comment"))
        malformed_creator = issue_event(author={"id": OWNER["id"]})
        self.assertFalse(invoke(malformed_creator))
        malformed_mismatch = issue_event(author={"id": OWNER["id"], "login": []})
        self.assertEqual(
            gate.admission_decision(
                malformed_mismatch,
                event_name="issues",
                actor_id=str(OWNER["id"]),
                actor_login=OWNER["login"],
                triggering_actor=OWNER["login"],
                repository="kinoko34077/devflow",
            ),
            "UNTRUSTED",
        )
        malformed_comment_author = issue_event(
            author={"id": OWNER["id"], "login": []}, action="created"
        )
        malformed_comment_author["comment"] = {
            "user": OWNER,
            "body": "/kinotch sync verify",
        }
        self.assertEqual(
            gate.admission_decision(
                malformed_comment_author,
                event_name="issue_comment",
                actor_id=str(OWNER["id"]),
                actor_login=OWNER["login"],
                triggering_actor=OWNER["login"],
                repository="kinoko34077/devflow",
            ),
            "UNTRUSTED",
        )

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
