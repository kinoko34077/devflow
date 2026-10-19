"""Opt-in B5 verified-pointer candidate shadow, no GitHub or task writes."""
from __future__ import annotations

import json
import unittest

from tools.kaep_mailbox_codec import encode_comment
from tools.kaep_request_sender import make_request
from tools.kaep_discovery_reader import POINTER_VERSION
from tools.kaep_source_roster_shadow import (
    source_root_shadow, MAX_SOURCE_ISSUES, MAX_OPT_IN_SOURCE_ISSUES,
)

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
    def task_view(self, numbers, *, state="open", freshness="CURRENT",
                  status="AVAILABLE"):
        return {
            "repository": REPO,
            "source_status": status,
            "source_freshness": freshness,
            "machine_task_count": len(numbers),
            "observed_task_view": {"known_task_count": len(numbers),
                                   "unresolved_open_issue_count": 17,
                                   "is_complete_read": False},
            "coverage_status": "INCOMPLETE",
            "task_records": [
                {"issue_number": n, "url": f"https://github.com/{REPO}/issues/{n}",
                 "record_role": "TASK", "state": state,
                 "work_status": "IMPLEMENTING"}
                for n in numbers
            ],
        }

    def test_trusted_live_task_without_pointer_admits_nonpointer_issue(self):
        # Unlike historical closed #553, this fixture represents an OPEN
        # machine-verified TASK from the real M3 Work View data shape.
        msg = root(31, issue=553)
        fetched = []
        def fetch(repo, issue):
            fetched.append((repo, issue))
            return pages([comment(900, msg)])
        from tools.kaep_source_roster_shadow import source_root_shadow
        out = source_root_shadow(
            pages([]), fetch_source=fetch,
            expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
            task_views=[self.task_view([553])],
        )
        self.assertEqual(out["status"], "BOUNDED_CANDIDATE_SOURCE_READ")
        self.assertEqual(fetched, [(REPO, 553)])
        self.assertEqual(out["index_hint_count"], 0)
        self.assertEqual(out["source_mode"],
                         "VERIFIED_POINTER_AND_TRUSTED_M3_TASK")
        self.assertEqual(out["candidate_issue_count"], 1)
        self.assertEqual(out["issues"][0]["provenance"], ["TRUSTED_M3_TASK"])
        self.assertEqual(out["issues"][0]["roots"][0]["comparison"],
                         "ORIGINAL_ONLY")
        self.assertFalse(out["issues"][0]["not_covered_by_task_classification"])
        self.assertTrue(out["has_unknown_work"])
        self.assertFalse(out["fallback_retirement_authorized"])
        self.assertNotIn("sanitized historical task body", json.dumps(out))

    def test_pointer_and_live_task_overlap_one_original_issue_read(self):
        msg = root(32)
        note = pointer_notice(msg, cid=701, notice_id=32)
        calls = []
        def fetch(repo, issue):
            calls.append((repo, issue))
            return pages([comment(701, msg)])
        from tools.kaep_source_roster_shadow import source_root_shadow
        out = source_root_shadow(
            pages([comment(801, note)]), fetch_source=fetch,
            expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
            task_views=[self.task_view([ISSUE])],
        )
        self.assertEqual(calls, [(REPO, ISSUE)])
        self.assertEqual(out["candidate_issue_count"], 1)
        self.assertEqual(out["issues"][0]["provenance"],
                         ["VERIFIED_POINTER", "TRUSTED_M3_TASK"])
        self.assertEqual(out["issues"][0]["root_count"], 1)
        self.assertEqual(out["issues"][0]["roots"][0]["comparison"],
                         "INDEXED_AND_ORIGINAL")
        self.assertFalse(out["issues"][0]["not_covered_by_task_classification"])

    def test_stale_or_unknown_machine_view_fails_closed(self):
        from tools.kaep_source_roster_shadow import source_root_shadow
        for changed in ({"source_freshness": "STALE"},
                        {"source_status": "UNAVAILABLE"},
                        {"machine_task_count": 99}):
            view = self.task_view([553])
            view.update(changed)
            calls = []
            def fetch(repo, issue):
                calls.append((repo, issue))
                raise AssertionError("untrusted TASK was fetched")
            out = source_root_shadow(
                pages([]), fetch_source=fetch,
                expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                task_views=[view],
            )
            self.assertEqual(out["status"], "BLOCKED")
            self.assertEqual(calls, [])
            self.assertTrue(out["has_unknown_work"])
            self.assertEqual(out["issues"], [])

    def test_invalid_task_role_state_url_or_duplicate_blocks(self):
        from tools.kaep_source_roster_shadow import source_root_shadow
        for key, value in (("record_role", "REFERENCE"),
                           ("state", "closed"),
                           ("url", f"https://github.com/{REPO}/issues/554")):
            view = self.task_view([553])
            view["task_records"][0][key] = value
            out = source_root_shadow(
                pages([]), fetch_source=lambda repo, issue: pages([]),
                expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                task_views=[view],
            )
            self.assertEqual(out["status"], "BLOCKED")
            self.assertEqual(out["issues"], [])
        with self.assertRaisesRegex(Exception, "INVALID_TASK_VIEW_COUNT"):
            from tools.kaep_source_roster_shadow import trusted_m3_task_locators
            trusted_m3_task_locators([self.task_view([553])] * 3)

    def test_task_source_read_or_total_cap_block_no_partial_roster(self):
        from tools.kaep_source_roster_shadow import source_root_shadow
        view = self.task_view([553, 554])
        calls = []
        def fetch(repo, issue):
            calls.append((repo, issue))
            return pages([])
        out = source_root_shadow(
            pages([]), fetch_source=fetch,
            expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
            max_sources=1, task_views=[view],
        )
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(len(calls), 1)
        self.assertEqual(out["issues"], [])
        self.assertTrue(out["has_unknown_work"])

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
        self.assertEqual(res["index_blockers"], [])
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
        self.assertEqual(out["index_blockers"], [
            {"index_comment_id": 402, "reason_code": "CANDIDATE_LIMIT"}])
        self.assertEqual(len(fetched), 1)
        self.assertTrue(out["has_unknown_work"])

    def test_default_twenty_vs_explicit_twenty_one_pointer_sources(self):
        # Only 21 fully valid owner-pointer original Issue sources, no broad
        # enumeration. Old/default callers remain capped at exactly 20.
        msgs = {600 + n: root(100 + n, issue=600 + n) for n in range(21)}
        notes = [comment(
            30000 + n,
            pointer_notice(msgs[600 + n], issue=600 + n,
                           cid=20000 + n, notice_id=200 + n))
            for n in range(21)]
        source_pages = {
            (REPO, 600 + n): pages([comment(20000 + n, msgs[600 + n])])
            for n in range(21)
        }
        old, old_gets = compare(pages(notes), source_pages)
        self.assertEqual(MAX_SOURCE_ISSUES, 20)
        self.assertEqual(MAX_OPT_IN_SOURCE_ISSUES, 40)
        self.assertEqual(old["status"], "BLOCKED")
        self.assertEqual(len(old_gets), 20)
        self.assertEqual(old["issues"], [])
        self.assertTrue(old["has_unknown_work"])
        self.assertEqual(old["index_blockers"][-1]["reason_code"], "CANDIDATE_LIMIT")

        expanded, source_gets = compare(pages(notes), source_pages,
                                        max_sources=21)
        self.assertEqual(expanded["status"], "BOUNDED_CANDIDATE_SOURCE_READ")
        self.assertEqual(expanded["index_blockers"], [])
        self.assertEqual(expanded["candidate_issue_count"], 21)
        self.assertEqual(len(expanded["issues"]), 21)
        self.assertEqual(len(set(source_gets)), 21)
        self.assertEqual(sum(x["root_count"] for x in expanded["issues"]), 21)
        self.assertTrue(expanded["has_unknown_work"])
        self.assertFalse(expanded["complete_source_universe"])
        self.assertFalse(expanded["can_authorize_execution"])
        self.assertFalse(expanded["fallback_retirement_authorized"])

    def test_opt_in_forty_still_rejects_malformed_source_original(self):
        msg = root(45)
        note = pointer_notice(msg, cid=20001, notice_id=45)
        malformed = {"id": 20002,
                     "body": "<!-- kaep:message:v0.2 -->\\n`\\`\\`json\\n{}\\n\\`\\`\\`\\nUntrusted prose",
                     "user": {"login": ACTOR}}
        res, _ = compare(
            pages([comment(30001, note)]),
            {(REPO, ISSUE): pages([comment(20001, msg), malformed])},
            max_sources=40,
        )
        self.assertEqual(res["status"], "BLOCKED")
        self.assertEqual(res["issues"], [])
        self.assertFalse(res["can_authorize_execution"])

    def test_bad_limit_type_and_boolean_rejected(self):
        with self.assertRaisesRegex(ValueError, "INVALID_SOURCE_LIMIT"):
            compare(pages([]), {}, max_sources=True)
        with self.assertRaisesRegex(ValueError, "INVALID_SOURCE_LIMIT"):
            compare(pages([]), {}, max_sources=41)

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
        self.assertEqual(out["errors"][0]["reason_code"], "INDEX_SOURCE_INCOMPLETE")
        self.assertEqual(out["index_blockers"], [
            {"index_comment_id": 601, "reason_code": "INVALID_WRAPPER"}])
        self.assertFalse(out["can_authorize_execution"])
        self.assertFalse(out["fallback_retirement_authorized"])
        self.assertNotIn("malformed", json.dumps(out))
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
