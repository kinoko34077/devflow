"""KAEP Agent Inbox read-only projection regressions (no GitHub network)."""
import json
import unittest

from tools import agent_inbox, devflow_mcp_core, repository_projection
from tools.kaep_mailbox_codec import encode_comment
from tools.kaep_request_sender import make_request
from tests.test_devflow_mcp_core import FakeReader

REPO = "kinoko34077/demo"
OWNER = "kinoko34077"


def task(number=21, status="AWAITING_REVIEW", author="OWNER"):
    payload = {
        "schema_version": 1, "record_role": "TASK", "type": "AUDIT",
        "work_status": status, "priority": "P2", "risk": "LOW",
        "scope_ready": True, "requires_user_confirmation": False,
        "external_wait": True, "work_order_ref": "kinoko34077/devflow#531",
    }
    return {
        "number": number, "state": "open", "author_association": author,
        "title": f"[TASK] audited {number}",
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "created_at": "2026-10-14T00:00:00Z",
        "updated_at": "2026-10-14T00:00:00Z",
        "body": repository_projection.render_issue_metadata_v1(payload),
    }


def control():
    return {
        "number": 90, "state": "open", "author_association": "OWNER",
        "title": "[REPO] demo", "html_url":
        "https://github.com/kinoko34077/devflow/issues/90",
        "body": (
            "## Repository\n\n`kinoko34077/demo`\n\n"
            "## Work Status\n\n`AUDITED`\n\n"
            "## Repository State\n\n`ACTIVE`\n\n"
            "## Priority\n\n`P2`\n\n"
            "## Risk\n\n`LOW`\n\n"
            "## Type\n\n`INFRA`\n\n"
            "## Audit SHA\n\n`abcdef0`\n\n"
            "## Active Work\n\nmanual pointer\n\n"
            "## Next Action\n\nverify source\n\n"
            "## Canonical Entry Points\n\nREADME.md\n\n"
        ),
    }


def message(issue=21):
    root, _ = make_request(
        "[[]]", repository=REPO, issue=issue, recipient="claude-code",
        intent="ANALYZE", request_key=f"kaep.agentinbox.tests.{issue}",
        request_text="review this real work", expected_head="a" * 40,
        expect_existing_actor=OWNER)
    return root


def issue_comment(cid, msg, login=OWNER):
    return {"id": cid, "body": encode_comment(msg),
            "user": {"login": login}}


def fixture_reader(issues, comments=None):
    return FakeReader([], issues_by_repository={
        "kinoko34077/devflow": [control()],
        REPO: issues,
    }, comments=comments)


class AgentInboxProjectionTests(unittest.TestCase):
    def test_real_source_task_and_correlated_answer(self):
        root = message()
        answer = dict(root)
        answer.update({
            "message_id": "msg_agentinbox_test_answer21",
            "in_reply_to": root["message_id"],
            "kind": "ANSWER", "recipient": "chatgpt",
            "idempotency_key": "kaep.agentinbox.answer21",
            "payload": {"text": "audit complete"},
        })
        reader = fixture_reader([task()], {
            (REPO, 21): [issue_comment(11, root), issue_comment(12, answer)]})
        res = devflow_mcp_core.DevflowService(reader).get_agent_inbox("demo")
        self.assertEqual(res["schema_version"], "kaep.agent-inbox.read.v0.1")
        self.assertEqual(len(res["issues"]), 1)
        req = res["issues"][0]["requests"][0]
        self.assertEqual(req["source_message_id"], root["message_id"])
        self.assertEqual(req["reply_kinds_observed"], ["ANSWER"])
        self.assertEqual(req["status"], "ANSWER_OBSERVED")
        self.assertEqual(req["expected_head"], "a" * 40)
        self.assertFalse(res["is_authoritative_assignment"])
        self.assertFalse(res["can_replace_manual_active_work"])
        self.assertFalse(res["can_authorize_execution"])
        self.assertFalse(res["is_live_agent_delivery"])
        self.assertNotIn("review this real work", json.dumps(res))
        self.assertNotIn("audit complete", json.dumps(res))
        self.assertIn((REPO, "comments", 21), reader.calls)

    def test_explicit_recipient_not_inferred_from_task_status(self):
        reader = fixture_reader([task()], {(REPO, 21): [issue_comment(11, message())]})
        res = devflow_mcp_core.DevflowService(reader).get_agent_inbox(
            "demo", recipient="codex")
        self.assertEqual(len(res["issues"]), 1)
        self.assertEqual(res["issues"][0]["requests"], [])
        self.assertFalse(res["issues"][0]["recipient_assignment_inferred"])

    def test_unclassified_issue_is_not_made_a_task(self):
        unknown = task(22)
        unknown["body"] = "No machine metadata"
        reader = fixture_reader([task(21), unknown], {
            (REPO, 21): [issue_comment(11, message())]})
        res = devflow_mcp_core.DevflowService(reader).get_agent_inbox("demo")
        self.assertTrue(res["has_unknown_work"])
        self.assertEqual(res["unresolved_open_issue_count"], 1)
        self.assertEqual([e["issue_number"] for e in res["issues"]], [21])
        self.assertEqual(res["coverage_status"], "INCOMPLETE")
        self.assertEqual(res["manual_control"]["active_work"], "manual pointer")

    def test_unknown_source_not_presented_as_empty_work(self):
        reader = fixture_reader([])
        def fail(repo, state="open"):
            if repo == REPO:
                raise devflow_mcp_core.DevflowMCPError("API_DOWN")
            return [control()]
        reader.list_issues = fail
        result = devflow_mcp_core.DevflowService(reader).get_agent_inbox("demo")
        self.assertEqual(result["issues"], [])
        self.assertIsNone(result["known_task_count"])
        self.assertIsNone(result["task_count_filtered"])
        self.assertTrue(result["has_unknown_work"])
        self.assertEqual(result["source_status"], "UNAVAILABLE")

    def test_failed_comments_is_not_misclassified_as_no_pending_message(self):
        result = agent_inbox.build_agent_inbox(
            fake_work_view([task()]), recipient="claude-code",
            comments_by_issue={}, errors_by_issue={21:"GITHUB_COMMENT_READ_FAILED"})
        self.assertEqual(result["issues"][0]["source_state"], "UNAVAILABLE")
        self.assertIsNone(result["issues"][0]["requests"])
        self.assertTrue(result["has_unknown_work"])

    def test_invalid_kaep_envelope_does_not_promote_work(self):
        invalid = {"id": 12, "body": "<!-- kaep:message:v0.2 -->bad",
                   "user": {"login": OWNER}}
        result = agent_inbox.build_agent_inbox(
            fake_work_view([task()]), recipient="claude-code",
            comments_by_issue={21:[invalid]})
        self.assertIsNone(result["issues"][0]["requests"])
        self.assertTrue(result["errors"])
        self.assertTrue(result["has_unknown_work"])

    def test_untrusted_root_not_actionable(self):
        result = agent_inbox.build_agent_inbox(
            fake_work_view([task()]), recipient="claude-code",
            comments_by_issue={21:[issue_comment(12, message(), "unknown-writer")]})
        self.assertEqual(result["issues"][0]["requests"], [])
        self.assertEqual(result["errors"][0]["reason_code"], "UNTRUSTED_ROOT_ACTOR")
        self.assertTrue(result["has_unknown_work"])

    def test_limit_and_offset_never_claim_complete_inventory(self):
        tasks = [task(i) for i in range(1, 26)]
        view = fake_work_view(tasks)
        first = agent_inbox.select_task_records(view, recipient="claude-code", limit=20)
        self.assertEqual(len(first["selected"]), 20)
        self.assertTrue(first["truncated"])
        self.assertEqual(first["next_offset"], 20)
        second = agent_inbox.select_task_records(
            view, recipient="claude-code", limit=20, offset=20)
        self.assertEqual(len(second["selected"]), 5)
        self.assertIsNone(second["next_offset"])
        self.assertEqual(second["selected"][-1]["issue_number"], 25)

    def test_complete_source_with_limited_page_never_claims_no_more_work(self):
        tasks = [task(i) for i in range(1, 26)]
        # All 25 machine TASKs exist; only 20 selected Issues were fetched.
        comments = {i: [] for i in range(1, 21)}
        result = agent_inbox.build_agent_inbox(
            fake_work_view(tasks), recipient="claude-code",
            comments_by_issue=comments, limit=20)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["next_offset"], 20)
        self.assertEqual(len(result["issues"]), 20)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["has_unknown_work"])

    def test_invalid_options_rejected_before_comment_reads(self):
        view = fake_work_view([task()])
        for options in [
            dict(recipient="attacker"), dict(recipient="claude-code", limit=21),
            dict(recipient="claude-code", limit=True),
            dict(recipient="claude-code", offset=-1),
        ]:
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    agent_inbox.select_task_records(view, **options)

    def test_excessive_comment_history_is_unknown(self):
        rows = [{"id":i+1,"body":"prose","user":{"login":OWNER}} for i in range(501)]
        result = agent_inbox.build_agent_inbox(
            fake_work_view([task()]), recipient="claude-code",
            comments_by_issue={21: rows})
        self.assertTrue(result["has_unknown_work"])
        self.assertEqual(result["errors"][0]["reason_code"], "ISSUE_COMMENTS_LIMIT")


def fake_work_view(issues):
    records = [
        {"issue_number":i["number"],"url":i["html_url"],
         "title":i["title"],"record_role":"TASK",
         "work_status":"AWAITING_REVIEW"} for i in issues]
    return {
        "repository": REPO, "source_status":"AVAILABLE",
        "source_freshness":"CURRENT", "coverage_status":"COMPLETE",
        "source_error":None, "task_records":records,
        "observed_task_view":{
            "status":"COMPLETE_READ", "known_task_count":len(records),
            "unresolved_open_issue_count":0,"is_complete_read":True},
        "manual_control":{"active_work":"manual pointer","next_action":"review"},
    }


if __name__ == "__main__":
    unittest.main()
