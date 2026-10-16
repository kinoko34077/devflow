"""Opt-in B5 verified-pointer candidate shadow, no GitHub or task writes."""
from __future__ import annotations

import json
import unittest

from tools.kaep_mailbox_codec import encode_comment
from tools.kaep_request_sender import make_request
from tools.kaep_discovery_reader import POINTER_VERSION
from tools.kaep_source_roster_shadow import source_root_shadow, MAX_SOURCE_ISSUES

ACTOR = "kinoko34077"
REPO = "kinoko34077/devflow"
ISSUE = 576


def pages(*groups):
    return json.dumps(list(groups))


def comment(cid, msg, actor=ACTOR):
    return {"id": cid, "body": encode_comment(msg), "user": {"login": actor}}


def root(number, *, issue=ISSUE, recipient="claude-code"):
    msg, _ = make_request(
        pages([]), repository=REPO, issue=issue, recipient=recipient,
        intent="ANALYZE", expected_head="a" * 40,
        request_key=f"kaep.shadow.root.{number:04d}.{issue}",
        request_text="sanitized historical task body",
        expect_existing_actor=ACTOR,
    )
    return msg


def pointer_notice(msg, *, issue=ISSUE, cid, notice_id):
    pointer = {
        "type": POINTER_VERSION,
        "owning_issue": f"https://github.com/{REPO}/issues/{issue}",
        "message_id": msg["message_id"],
        "comment_id": cid,
    }
    notice, _ = make_request(
        pages([]), repository=REPO, issue=503, recipient="claude-code",
        intent="REPORT", expected_head=None,
        request_key=f"kaep.shadow.pointer.{notice_id:04d}.{issue}",
        request_text=json.dumps(pointer, sort_keys=True, separators=(",", ":")),
        expect_existing_actor=ACTOR,
    )
    return notice


def compare(index, sources, *, max_sources=MAX_SOURCE_ISSUES):
    fetched = []
    def fetch(r, i):
        fetched.append((r, i))
        return sources[(r, i)]
    output = source_root_shadow(
        index, fetch_source=fetch, expected_notice_actor=ACTOR,
        expected_source_actor=ACTOR, max_sources=max_sources,
    )
    return output, fetched


class SourceRootShadowTests(unittest.TestCase):
    def test_real_576_identity_replay_unindexed_original_detected(self):
        old = root(1)
        old["message_id"] = "msg_cursor576_readonly_audit_20261015a"
        old["exchange_id"] = "ex_cursor576_readonly_audit_20261015a"
        old["scope"]["expected_head"] = "60cf73abd166e14d34d73e8821589fc6cb412c57"
        new = root(2)
        new["message_id"] = "msg_cursor576_claude_delta_review_20261016d"
        new["exchange_id"] = "ex_cursor576_claude_delta_review_20261016d"
        new["scope"]["expected_head"] = "eef92defe34d5dadbde79c3c379581769ea3a6fe"
        notice = pointer_notice(new, cid=6198495044, notice_id=1)
        result, fetched = compare(
            pages([comment(6198497020, notice)]),
            {(REPO, ISSUE): pages([
                comment(6193914061, old), comment(6198495044, new),
            ])},
        )
        self.assertEqual(result["status"], "BOUNDED_CANDIDATE_SOURCE_READ")
        self.assertEqual(fetched, [(REPO, ISSUE)])
        self.assertEqual(result["index_hint_count"], 1)
        self.assertEqual(result["candidate_issue_count"], 1)
        self.assertEqual(result["issues"][0]["root_count"], 2)
        self.assertEqual(result["issues"][0]["original_only_count"], 1)
        roots = result["issues"][0]["roots"]
        self.assertEqual([(x["source_comment_id"], x["comparison"]) for x in roots], [
            (6193914061, "ORIGINAL_ONLY"),
            (6198495044, "INDEXED_AND_ORIGINAL"),
        ])
        self.assertEqual(roots[0]["head_freshness"], "NOT_REVALIDATED")
        self.assertTrue(result["has_unknown_work"])
        self.assertFalse(result["complete_source_universe"])
        self.assertFalse(result["can_authorize_execution"])
        self.assertFalse(result["fallback_retirement_authorized"])
        self.assertNotIn("sanitized historical task body", json.dumps(result))

    def test_all_indexed_is_still_not_full_source_completeness(self):
        msg = root(3)
        hint = pointer_notice(msg, cid=101, notice_id=3)
        res, _ = compare(
            pages([comment(102, hint)]),
            {(REPO, ISSUE): pages([comment(101, msg)])},
        )
        self.assertEqual(res["status"], "BOUNDED_CANDIDATE_SOURCE_READ")
        self.assertEqual(res["issues"][0]["original_only_count"], 0)
        self.assertTrue(res["has_unknown_work"])
        self.assertFalse(res["fallback_retirement_authorized"])

    def test_recipient_isolation_other_recipient_root_not_promoted(self):
        msg = root(4)
        other = root(5, recipient="codex")
        hint = pointer_notice(msg, cid=103, notice_id=4)
        res, _ = compare(
            pages([comment(104, hint)]),
            {(REPO, ISSUE): pages([
                comment(102, other), comment(103, msg)
            ])},
        )
        self.assertEqual(res["status"], "BOUNDED_CANDIDATE_SOURCE_READ")
        self.assertEqual(res["issues"][0]["root_count"], 1)
        self.assertEqual(res["issues"][0]["original_only_count"], 0)
        self.assertEqual(res["recipient"], "claude-code")

    def test_source_limit_blocks_without_emitting_partial_roster(self):
        msg1, msg2 = root(6, issue=576), root(7, issue=577)
        one = pointer_notice(msg1, issue=576, cid=201, notice_id=6)
        two = pointer_notice(msg2, issue=577, cid=301, notice_id=7)
        out, fetched = compare(
            pages([comment(401, one), comment(402, two)]),
            {
                (REPO, 576): pages([comment(201, msg1)]),
                (REPO, 577): pages([comment(301, msg2)]),
            }, max_sources=1,
        )
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["issues"], [])
        self.assertEqual(out["blocked_index_count"], 1)
        self.assertEqual(len(fetched), 1)
        self.assertTrue(out["has_unknown_work"])

    def test_bad_limit_type_and_boolean_rejected(self):
        with self.assertRaisesRegex(ValueError, "INVALID_SOURCE_LIMIT"):
            compare(pages([]), {}, max_sources=True)
        with self.assertRaisesRegex(ValueError, "INVALID_SOURCE_LIMIT"):
            compare(pages([]), {}, max_sources=21)

    def test_malformed_trusted_source_blocks_not_empty_success(self):
        msg = root(8)
        notice = pointer_notice(msg, cid=501, notice_id=8)
        corrupt = {"id": 502,
                   "body": "<!-- kaep:message:v0.2 -->\nmalformed",
                   "user": {"login": ACTOR}}
        out, _ = compare(
            pages([comment(601, notice)]),
            {(REPO, ISSUE): pages([comment(501, msg), corrupt])},
        )
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["issues"], [])
        self.assertTrue(out["has_unknown_work"])

    def test_untrusted_index_actor_cannot_admit_candidate(self):
        msg = root(9)
        notice = pointer_notice(msg, cid=701, notice_id=9)
        out, fetched = compare(
            pages([comment(801, notice, actor="outsider")]),
            {(REPO, ISSUE): pages([comment(701, msg)])},
        )
        self.assertEqual(fetched, [])
        self.assertEqual(out["index_hint_count"], 0)
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["rejected_index_count"], 1)
        self.assertTrue(out["has_unknown_work"])

    def test_invalid_provider_index_pages_fail_closed(self):
        from tools.kaep_inbox_reader import InvalidMessage
        with self.assertRaises(InvalidMessage):
            compare("not json", {})

    def test_no_pointer_no_scan_and_no_completeness_claim(self):
        out, fetched = compare(pages([]), {})
        self.assertEqual(fetched, [])
        self.assertEqual(out["status"], "BOUNDED_CANDIDATE_SOURCE_READ")
        self.assertEqual(out["candidate_issue_count"], 0)
        self.assertTrue(out["has_unknown_work"])
        self.assertFalse(out["complete_source_universe"])


if __name__ == "__main__":
    unittest.main()
