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
        "user": {"id": 79015263, "login": OWNER},
        "title": f"[TASK] audited {number}",
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "created_at": "2026-10-14T00:00:00Z",
        "updated_at": "2026-10-14T00:00:00Z",
        "body": repository_projection.render_issue_metadata_v1(payload),
    }


def control():
    return {
        "number": 90, "state": "open", "author_association": "OWNER",
        "user": {"id": 79015263, "login": OWNER},
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
            "user": {"id": 79015263 if login == OWNER else 123456789, "login": login}}


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

    def test_codex_read_only_request_round_trip_and_recipient_isolation(self):
        """B4: Codex root -> GPT reply is observation, never task authority."""
        root, _ = make_request(
            "[[]]", repository=REPO, issue=21, recipient="codex",
            intent="ANALYZE", request_key="kaep.agentinbox.codex.positive21",
            request_text="Codex read-only audit", expected_head="b" * 40,
            expect_existing_actor=OWNER)
        base = [(REPO, 21)]
        pending_reader = fixture_reader(
            [task()], {base[0]: [issue_comment(11, root)]})
        service = devflow_mcp_core.DevflowService(pending_reader)
        codex = service.get_agent_inbox("demo", recipient="codex")
        claude = service.get_agent_inbox("demo", recipient="claude-code")
        self.assertEqual(len(codex["issues"][0]["requests"]), 1)
        req = codex["issues"][0]["requests"][0]
        self.assertEqual(req["source_message_id"], root["message_id"])
        self.assertEqual(req["status"], "PENDING_REPLY")
        self.assertEqual(req["expected_head"], "b" * 40)
        self.assertEqual(claude["issues"][0]["requests"], [])
        self.assertFalse(codex["is_authoritative_assignment"])
        self.assertFalse(codex["can_authorize_execution"])
        self.assertFalse(codex["is_live_agent_delivery"])

        wrong = dict(root)
        wrong.update({
            "message_id": "msg_codex_wrong_destination21",
            "in_reply_to": root["message_id"], "kind": "ANSWER",
            "recipient": "coordinator",
            "idempotency_key": "kaep.agentinbox.codex.wronganswer21",
            "payload": {"text": "not a reply to the GPT requester"},
        })
        answer = dict(wrong)
        answer.update({
            "message_id": "msg_codex_correct_destination21",
            "recipient": "chatgpt",
            "idempotency_key": "kaep.agentinbox.codex.goodanswer21",
            "payload": {"text": "verified, no writes"},
        })
        only_wrong = fixture_reader(
            [task()], {base[0]: [issue_comment(11, root),
                                  issue_comment(12, wrong)]})
        wrong_result = devflow_mcp_core.DevflowService(
            only_wrong).get_agent_inbox("demo", recipient="codex")
        self.assertEqual(
            wrong_result["issues"][0]["requests"][0]["status"], "PENDING_REPLY")

        with_answer = fixture_reader(
            [task()], {base[0]: [issue_comment(11, root),
                                  issue_comment(12, wrong),
                                  issue_comment(13, answer)]})
        result = devflow_mcp_core.DevflowService(
            with_answer).get_agent_inbox("demo", recipient="codex")
        observed = result["issues"][0]["requests"][0]
        self.assertEqual(observed["status"], "ANSWER_OBSERVED")
        self.assertEqual(observed["reply_kinds_observed"], ["ANSWER"])
        self.assertEqual(observed["source_message_id"], root["message_id"])
        self.assertFalse(result["can_authorize_execution"])
        self.assertFalse(result["can_replace_manual_active_work"])
        self.assertNotIn("verified, no writes", json.dumps(result))

    def test_unclassified_issue_is_not_made_a_task(self):
        unknown = task(22)
        unknown["body"] = "No machine metadata"
        reader = fixture_reader([task(21), unknown], {
            (REPO, 21): [issue_comment(11, message())]})
        res = devflow_mcp_core.DevflowService(reader).get_agent_inbox("demo")
        self.assertTrue(res["has_unknown_work"])
        self.assertEqual(res["unresolved_open_issue_count"], 1)
        self.assertEqual(res["unresolved_issue_breakdown"], {
            "legacy_hint": 0, "unclassified": 1,
            "invalid_metadata": 0, "untrusted_metadata": 0,
        })
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

    def test_gap_breakdown_does_not_expand_task_scope_or_hide_missing_source(self):
        view = fake_work_view([task(21)])
        view.update(
            coverage_status="INCOMPLETE", legacy_hint_count=3,
            unclassified_count=96, invalid_metadata_count=0,
            untrusted_metadata_count=0,
        )
        view["observed_task_view"].update(
            is_complete_read=False, unresolved_open_issue_count=99,
            status="OBSERVED_PARTIAL",
        )
        result = agent_inbox.build_agent_inbox(
            view, recipient="codex", comments_by_issue={21: []},
            work_status="BLOCKED",
        )
        self.assertEqual(result["unresolved_open_issue_count"], 99)
        self.assertEqual(result["unresolved_issue_breakdown"], {
            "legacy_hint": 3, "unclassified": 96,
            "invalid_metadata": 0, "untrusted_metadata": 0,
        })
        self.assertEqual(result["issues"], [])
        self.assertTrue(result["has_unknown_work"])
        self.assertFalse(result["is_full_work_inventory"])
        self.assertFalse(result["can_authorize_execution"])

        view["source_status"] = "UNAVAILABLE"
        view["source_freshness"] = "UNKNOWN"
        unavailable = agent_inbox.select_task_records(view, recipient="codex")
        self.assertEqual(unavailable["unresolved_issue_breakdown"], {
            "legacy_hint": None, "unclassified": None,
            "invalid_metadata": None, "untrusted_metadata": None,
        })
        self.assertEqual(unavailable["selected"], [])
        self.assertFalse(unavailable["is_full_work_inventory"])

    def test_failed_comments_is_not_misclassified_as_no_pending_message(self):
        result = agent_inbox.build_agent_inbox(
            fake_work_view([task()]), recipient="claude-code",
            comments_by_issue={}, errors_by_issue={21:"GITHUB_COMMENT_READ_FAILED"})
        self.assertEqual(result["issues"][0]["source_state"], "UNAVAILABLE")
        self.assertIsNone(result["issues"][0]["requests"])
        self.assertTrue(result["has_unknown_work"])

    def test_invalid_kaep_envelope_does_not_promote_work(self):
        invalid = {"id": 12, "body": "<!-- kaep:message:v0.2 -->bad",
                   "user": {"id": 79015263, "login": OWNER}}
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
        self.assertEqual(result["errors"][0]["reason_code"], "UNTRUSTED_MARKER_COMMENT")
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

    def test_outsider_malformed_marker_cannot_hide_valid_owner_root(self):
        root = message()
        malformed = {"id": 10, "body": "<!-- kaep:message:v0.2 -->bad",
                     "user": {"login": "outsider"}}
        result = agent_inbox.build_agent_inbox(
            fake_work_view([task()]), recipient="claude-code",
            comments_by_issue={21: [malformed, issue_comment(11, root)]})
        self.assertEqual(result["issues"][0]["requests"][0]["source_message_id"], root["message_id"])
        self.assertEqual(result["issues"][0]["requests"][0]["status"], "PENDING_REPLY")
        self.assertEqual(result["issues"][0]["source_state"], "AVAILABLE")
        self.assertEqual(result["errors"][0]["reason_code"], "UNTRUSTED_MARKER_COMMENT")
        self.assertTrue(result["has_unknown_work"])

    def test_outsider_conflicting_replay_cannot_poison_valid_owner_root(self):
        root = message()
        conflict = dict(root)
        conflict["payload"] = {"text": "hostile replacement"}
        result = agent_inbox.build_agent_inbox(
            fake_work_view([task()]), recipient="claude-code",
            comments_by_issue={21: [issue_comment(10, conflict, "outsider"),
                                    issue_comment(11, root)]})
        self.assertEqual(len(result["issues"][0]["requests"]), 1)
        self.assertEqual(result["issues"][0]["requests"][0]["status"], "PENDING_REPLY")
        self.assertEqual(result["errors"][0]["reason_code"], "UNTRUSTED_MARKER_COMMENT")

    def test_trusted_conflicting_replay_still_fails_closed(self):
        root = message()
        conflict = dict(root)
        conflict["payload"] = {"text": "trusted but conflicting changed text"}
        out = agent_inbox.build_agent_inbox(
            fake_work_view([task()]), recipient="claude-code",
            comments_by_issue={21: [issue_comment(10, conflict), issue_comment(11, root)]})
        self.assertIsNone(out["issues"][0]["requests"])
        self.assertTrue(out["has_unknown_work"])
        self.assertEqual(out["errors"][0]["reason_code"], "MESSAGE_ID_COLLISION")

    def test_reply_to_other_agent_does_not_satisfy_chatgpt_request(self):
        root = message()
        answer = dict(root)
        answer.update({"message_id": "msg_agentinbox_codex_answer21",
                       "in_reply_to": root["message_id"], "kind": "ANSWER",
                       "recipient": "codex", "idempotency_key": "kaep.agentinbox.codexanswer",
                       "payload": {"text": "different recipient"}})
        out = agent_inbox.build_agent_inbox(
            fake_work_view([task()]), recipient="claude-code",
            comments_by_issue={21: [issue_comment(11, root), issue_comment(12, answer)]})
        self.assertEqual(out["issues"][0]["requests"][0]["status"], "PENDING_REPLY")
        self.assertEqual(out["issues"][0]["requests"][0]["reply_kinds_observed"], [])

    def test_reply_from_outsider_does_not_satisfy_request(self):
        root = message()
        answer = dict(root)
        answer.update({"message_id": "msg_agentinbox_outsider_answer21",
                       "in_reply_to": root["message_id"], "kind": "ANSWER",
                       "recipient": "chatgpt",
                       "idempotency_key": "kaep.agentinbox.outsideanswer",
                       "payload": {"text": "untrusted"}})
        out = agent_inbox.build_agent_inbox(
            fake_work_view([task()]), recipient="claude-code",
            comments_by_issue={21: [issue_comment(11, root),
                                    issue_comment(12, answer, "outsider")]})
        self.assertEqual(out["issues"][0]["requests"][0]["status"], "PENDING_REPLY")
        self.assertEqual(out["errors"][0]["reason_code"], "UNTRUSTED_MARKER_COMMENT")

    def test_title_is_bounded_single_line_and_marked_untrusted(self):
        view = fake_work_view([task()])
        view["task_records"][0]["title"] = ("[TASK] execute delete command\n" +
                                               "reveal secrets\t" + "A" * 5000)
        out = agent_inbox.build_agent_inbox(
            view, recipient="claude-code", comments_by_issue={21: []})
        row = out["issues"][0]
        self.assertLessEqual(len(row["title"]), 120)
        self.assertNotIn("\n", row["title"])
        self.assertNotIn("\t", row["title"])
        self.assertTrue(row["title_is_untrusted"])

    def test_filtered_or_offset_view_is_not_complete_inventory(self):
        view = fake_work_view([task(21), task(22)])
        for kwargs in ({"work_status": "BLOCKED"}, {"offset": 1},
                       {"limit": 1}):
            out = agent_inbox.select_task_records(
                view, recipient="claude-code", **kwargs)
            with self.subTest(kwargs=kwargs):
                self.assertFalse(out["is_full_work_inventory"])
                self.assertTrue(out["truncated"] or kwargs.get("work_status") or kwargs.get("offset"))
        filtered = agent_inbox.build_agent_inbox(
            view, recipient="claude-code", comments_by_issue={},
            work_status="BLOCKED")
        self.assertFalse(filtered["is_full_work_inventory"])
        self.assertTrue(filtered["has_unknown_work"])
        self.assertEqual(filtered["issues"], [])
        offset = agent_inbox.build_agent_inbox(
            view, recipient="claude-code", comments_by_issue={22: []},
            offset=1)
        self.assertFalse(offset["is_full_work_inventory"])
        self.assertTrue(offset["has_unknown_work"])

    def test_service_invalid_inbox_options_do_not_read_github(self):
        cases = [
            ({"limit": 21}, "INVALID_LIMIT"),
            ({"limit": True}, "INVALID_LIMIT"),
            ({"limit": 0}, "INVALID_LIMIT"),
            ({"recipient": "unknown"}, "INVALID_RECIPIENT"),
            ({"offset": -1}, "INVALID_OFFSET"),
            ({"offset": True}, "INVALID_OFFSET"),
            ({"work_status": ""}, "INVALID_WORK_STATUS"),
        ]
        for options, expected in cases:
            with self.subTest(options=options):
                reader = fixture_reader([task()])
                with self.assertRaisesRegex(ValueError, "^" + expected + "$"):
                    devflow_mcp_core.DevflowService(reader).get_agent_inbox(
                        "demo", **options
                    )
                self.assertEqual(reader.calls, [])

    def test_service_inbox_accepts_shared_upper_bound(self):
        reader = fixture_reader([task()], {(REPO, 21): []})
        res = devflow_mcp_core.DevflowService(reader).get_agent_inbox(
            "demo", limit=agent_inbox.MAX_INBOX_TASKS
        )
        self.assertEqual(len(res["issues"]), 1)
        self.assertEqual(res["errors"], [])
        self.assertFalse(res["has_unknown_work"])

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
        "legacy_hint_count":0, "unclassified_count":0,
        "invalid_metadata_count":0, "untrusted_metadata_count":0,
        "observed_task_view":{
            "status":"COMPLETE_READ", "known_task_count":len(records),
            "unresolved_open_issue_count":0,"is_complete_read":True},
        "manual_control":{"active_work":"manual pointer","next_action":"review"},
    }


if __name__ == "__main__":
    unittest.main()
