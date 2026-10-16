"""Search-first KAEP list: bounded read-only contract and spare-repo negative fixture."""
from __future__ import annotations

import json
import unittest

from tools.kaep_mailbox_codec import MARKER, encode_comment
from tools.kaep_request_sender import make_request
from tools.kaep_issue_search_view import build_search_list, to_markdown, machine_json, console_text

OWNER = "kinoko34077"
DEV = "kinoko34077/devflow"
TEST = "kinoko34077/testapp"


def issue(repo=DEV, n=576, title="[SPEC] Fixture", *, state="open"):
    return {
        "number": n,
        "title": title,
        "body": "No machine metadata",
        "state": state,
        "html_url": f"https://github.com/{repo}/issues/{n}",
        "created_at": "2026-10-16T00:00:00Z",
        "updated_at": "2026-10-16T00:00:00Z",
        "author_association": "OWNER",
        "user": {"login": OWNER},
    }


def searched(repo, numbers, *, incomplete=False, reported=None):
    return {
        "total_count": len(numbers) if reported is None else reported,
        "incomplete_results": incomplete,
        "items": [{"html_url": f"https://github.com/{repo}/issues/{n}",
                   "number": n} for n in numbers],
    }


def pages(comments):
    return json.dumps([comments], ensure_ascii=False)


def root(repo=DEV, n=576, number=1):
    msg, _ = make_request(
        pages([]), repository=repo, issue=n, recipient="claude-code",
        intent="ANALYZE", expected_head="a" * 40,
        request_key=f"search.fixture.{number}.{n}.positive",
        request_text="test-only inert source; no external actor should execute",
        expect_existing_actor=OWNER,
    )
    return msg


def comment(cid, msg, actor=OWNER):
    return {"id": cid, "body": encode_comment(msg), "user": {"login": actor}}


class SearchListTests(unittest.TestCase):
    def run_view(self, repositories, source_issues, source_comments, search=None,
                 *, max_candidates=40, recipient="claude-code"):
        queries = search if search is not None else {
            repo: searched(repo, [n for r, n in source_issues if r == repo])
            for repo in repositories
        }
        seen = []
        def read_issue(repo, n):
            seen.append(("issue", repo, n))
            return source_issues[(repo, n)]
        def read_comments(repo, n):
            seen.append(("comments", repo, n))
            return pages(source_comments[(repo, n)])
        result = build_search_list(
            repositories, queries, fetch_original_issue=read_issue,
            fetch_comments=read_comments, expected_actor=OWNER,
            recipient=recipient, max_candidates=max_candidates,
        )
        return result, seen

    def test_windows_cp932_json_and_markdown_emit_no_unicode_error(self):
        report = {"title": "read-only — 試験", "status": "PARTIAL_UNKNOWN"}
        wire = machine_json(report)
        wire.encode("cp932")  # Machine JSON must stay ASCII-safe.
        self.assertEqual(json.loads(wire), report)
        display = console_text("KAEP — 日本語", "cp932")
        display.encode("cp932")  # Unrepresentable punctuation is escaped.
        self.assertIn("KAEP", display)
        self.assertIn("日本語", display)
        self.assertIn(r"\u2014", display)

    def test_spare_testapp_zero_search_is_not_empty_work_authority(self):
        # Real testapp is a useful zero-match *negative* control; its separate
        # writeback R2 active Issue must not be edited or fabricated as KAEP.
        out, calls = self.run_view(
            [TEST], {}, {}, search={TEST: searched(TEST, [])},
        )
        self.assertEqual(out["status"], "BOUNDED_SEARCH_READ")
        self.assertEqual(out["searched_candidates"], 0)
        self.assertEqual(out["rows"], [])
        self.assertEqual(calls, [])
        self.assertTrue(out["has_unknown_work"])
        self.assertFalse(out["complete_source_universe"])
        self.assertFalse(out["can_authorize_execution"])
        self.assertFalse(out["fallback_retirement_authorized"])
        self.assertIn("No verified rows", to_markdown(out))

    def test_real_576_unindexed_original_shape_is_found_from_search(self):
        r = root()
        r["message_id"] = "msg_cursor576_readonly_audit_20261015a"
        r["exchange_id"] = "ex_cursor576_readonly_audit_20261015a"
        r["scope"]["expected_head"] = "60cf73abd166e14d34d73e8821589fc6cb412c57"
        out, calls = self.run_view(
            [DEV], {(DEV, 576): issue()}, {(DEV, 576): [comment(6193914061, r)]},
        )
        self.assertEqual(out["status"], "BOUNDED_SEARCH_READ")
        self.assertEqual(len(out["rows"]), 1)
        row = out["rows"][0]
        self.assertEqual(row["source_comment_id"], 6193914061)
        self.assertEqual(row["issue_role"], "UNCLASSIFIED")
        self.assertEqual(row["issue_type"], "SPEC")  # Legacy tag, NOT role.
        self.assertEqual(row["reply_observation"], "PENDING_REPLY")
        self.assertEqual(row["head_freshness"], "NOT_REVALIDATED")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("test-only inert source", json.dumps(out))
        self.assertIn("6193914061", to_markdown(out))
        rendered = to_markdown(out)
        self.assertIn("| State | Role / type (source) |", rendered)
        self.assertIn("claude-code / ANALYZE", rendered)
        self.assertIn("Observed at (UTC)", rendered)
        self.assertNotIn("test-only inert source", rendered)
        self.assertIn("No verified rows", to_markdown(out, issue_type="BUG"))



    def test_real_576_later_noncanonical_wrapper_is_quarantined_not_pending(self):
        earlier = root()
        earlier["message_id"] = "msg_cursor576_readonly_audit_20261015a"
        earlier["exchange_id"] = "ex_cursor576_readonly_audit_20261015a"
        earlier["scope"]["expected_head"] = "60cf73abd166e14d34d73e8821589fc6cb412c57"
        later = comment(6221821907, root(number=2))
        later["body"] += "\n\nExplanatory text outside KAEP v0.2 fence"
        out, _ = self.run_view(
            [DEV], {(DEV, 576): issue()}, {(DEV, 576): [
                comment(6193914061, earlier), later,
            ]},
        )
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["validated_source_issues"], 0)
        self.assertEqual(out["partial_source_issues"], 1)
        self.assertEqual(out["quarantined_comment_count"], 1)
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["rows"][0]["source_comment_id"], 6193914061)
        self.assertEqual(out["rows"][0]["source_state"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["rows"][0]["reply_observation"], "UNKNOWN_QUARANTINED_SOURCE")
        self.assertEqual(out["errors"][0]["comment_id"], 6221821907)
        self.assertEqual(out["errors"][0]["reason_code"], "QUARANTINED_INVALID_WRAPPER")
        self.assertNotIn("PENDING_REPLY", to_markdown(out))
        self.assertFalse(out["complete_source_universe"])
        self.assertFalse(out["fallback_retirement_authorized"])

    def test_real_551_invalid_reference_quarantined_without_relaxing_codec(self):
        valid = root(n=551)
        bad = root(n=551, number=2)
        bad["evidence_refs"] = ["https://invalid.example/issue/not-accepted"]
        fence = chr(96) * 3
        invalid_body = MARKER + "\n" + fence + "json\n" + json.dumps(bad) + "\n" + fence
        out, _ = self.run_view(
            [DEV], {(DEV, 551): issue(n=551)},
            {(DEV, 551): [comment(100, valid), {
                "id": 6175605292, "body": invalid_body,
                "user": {"login": OWNER},
            }]},
        )
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["partial_source_issues"], 1)
        self.assertEqual(out["errors"][0]["reason_code"], "QUARANTINED_INVALID_REF")
        self.assertEqual(out["rows"][0]["reply_observation"], "UNKNOWN_QUARANTINED_SOURCE")
        self.assertFalse(out["can_authorize_execution"])

    def test_bot_root_with_owner_reply_stays_blocked_unknown_parent(self):
        bot = root(n=554)
        reply = json.loads(json.dumps(bot))
        reply.update({
            "message_id": "msg_testbot_owner_answer",
            "idempotency_key": "search.fixture.bot.owner.answer",
            "kind": "ANSWER", "recipient": "chatgpt",
            "in_reply_to": bot["message_id"],
        })
        out, _ = self.run_view(
            [DEV], {(DEV, 554): issue(n=554)},
            {(DEV, 554): [
                comment(100, bot, actor="github-actions[bot]"),
                comment(101, reply),
            ]},
        )
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["validated_source_issues"], 0)
        self.assertEqual(out["partial_source_issues"], 0)
        self.assertEqual(out["errors"][0]["reason_code"], "UNKNOWN_PARENT")

    def test_quarantined_parent_with_remaining_owner_reply_blocks_issue(self):
        original = root()
        malformed_parent = comment(100, original)
        malformed_parent["body"] += "\n\nInvalid trailing Markdown"
        reply = json.loads(json.dumps(original))
        reply.update({
            "message_id": "msg_quarantine_parent_reply",
            "idempotency_key": "search.fixture.quarantine.parent",
            "kind": "ANSWER", "recipient": "chatgpt",
            "in_reply_to": original["message_id"],
        })
        out, _ = self.run_view(
            [DEV], {(DEV, 576): issue()},
            {(DEV, 576): [malformed_parent, comment(101, reply)]},
        )
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["validated_source_issues"], 0)
        self.assertEqual(out["partial_source_issues"], 0)
        self.assertEqual(out["errors"][0]["reason_code"], "UNKNOWN_PARENT")

    def test_other_trusted_codec_violation_still_blocks_all_source_roots(self):
        good = root()
        malformed = root(number=2)
        malformed["message_id"] = "invalid_message_id"
        fence = chr(96) * 3
        invalid_body = MARKER + "\n" + fence + "json\n" + json.dumps(malformed) + "\n" + fence
        out, _ = self.run_view(
            [DEV], {(DEV, 576): issue()},
            {(DEV, 576): [comment(100, good), {
                "id": 101, "body": invalid_body, "user": {"login": OWNER},
            }]},
        )
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["validated_source_issues"], 0)
        self.assertEqual(out["partial_source_issues"], 0)
        self.assertEqual(out["errors"][0]["reason_code"], "INVALID_MESSAGE_ID")

    def test_search_false_positive_without_exact_comment_is_excluded(self):
        out, _ = self.run_view(
            [DEV], {(DEV, 531): issue(n=531)},
            {(DEV, 531): [{"id": 1,
                           "body": 'quoted kaep:message:v0.2 is not a root',
                           "user": {"login": OWNER}}]},
        )
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["unmatched_candidates"], 1)
        self.assertTrue(out["has_unknown_work"])

    def test_bot_authored_root_not_promoted_as_owner_request(self):
        msg = root(n=554)
        out, _ = self.run_view(
            [DEV], {(DEV, 554): issue(n=554)},
            {(DEV, 554): [comment(70, msg, actor="github-actions[bot]")]},
        )
        self.assertEqual(out["status"], "BOUNDED_SEARCH_READ")
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["unmatched_candidates"], 1)

    def test_cross_repo_bounded_positive_and_spare_negative(self):
        msg = root()
        out, seen = self.run_view(
            [TEST, DEV], {(DEV, 576): issue()},
            {(DEV, 576): [comment(50, msg)]},
            search={TEST: searched(TEST, []), DEV: searched(DEV, [576])},
        )
        self.assertEqual(out["searched_candidates"], 1)
        self.assertEqual(out["validated_source_issues"], 1)
        self.assertEqual(len(out["rows"]), 1)
        self.assertTrue(all(r == DEV for _, r, _ in seen))

    def test_incomplete_index_remains_partial_even_with_valid_root(self):
        msg = root()
        out, _ = self.run_view(
            [DEV], {(DEV, 576): issue()}, {(DEV, 576): [comment(50, msg)]},
            search={DEV: searched(DEV, [576], incomplete=True)},
        )
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(len(out["rows"]), 1)
        self.assertIn("SEARCH_PAGE_INCOMPLETE",
                      [x["reason_code"] for x in out["errors"]])
        self.assertTrue(out["has_unknown_work"])

    def test_source_identity_mismatch_is_never_accepted(self):
        out, _ = self.run_view(
            [DEV], {(DEV, 576): issue(n=577)}, {(DEV, 576): []},
        )
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["validated_source_issues"], 0)
        self.assertEqual(out["errors"][0]["reason_code"], "SOURCE_ISSUE_MISMATCH")

    def test_malformed_authoritative_comment_fails_closed(self):
        bad = {"id": 1, "body": "<!-- kaep:message:v0.2 -->\nnot-json",
               "user": {"login": OWNER}}
        out, _ = self.run_view(
            [DEV], {(DEV, 576): issue()}, {(DEV, 576): [bad]},
        )
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["rows"], [])
        self.assertTrue(out["errors"])

    def test_bounded_candidates_do_not_silently_truncate(self):
        n = [1, 2]
        sources = {(DEV, x): issue(n=x) for x in n}
        comments = {(DEV, x): [] for x in n}
        out, calls = self.run_view(
            [DEV], sources, comments, max_candidates=1,
        )
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["searched_candidates"], 2)
        self.assertIn("CANDIDATE_LIMIT", [x["reason_code"] for x in out["errors"]])
        self.assertEqual(out["validated_source_issues"], 1)
        self.assertEqual(len(calls), 2)

    def test_repository_scope_rejects_unexpected_search_locator(self):
        out, calls = self.run_view(
            [TEST], {}, {}, search={TEST: searched(DEV, [576])},
        )
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(calls, [])
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["errors"][0]["reason_code"], "SEARCH_LOCATOR_MISMATCH")


if __name__ == "__main__":
    unittest.main()
