"""Opt-in B5 verified-pointer candidate shadow, no GitHub or task writes."""
from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from tools.kaep_inbox_reader import InvalidMessage
from tools.kaep_mailbox_codec import encode_comment
from tools.kaep_request_sender import make_request
from tools.kaep_discovery_reader import POINTER_VERSION
from tools.kaep_route_notice import DISCOVERY_ISSUE, APPROVED_SUCCESSOR_ISSUE
from tools.kaep_source_roster_shadow import (
    source_root_shadow, main, MAX_SOURCE_ISSUES, MAX_OPT_IN_SOURCE_ISSUES,
    MAX_SHADOW_BATCHES,
)

ACTOR = "kinoko34077"
REPO = "kinoko34077/devflow"
ISSUE = 576


def pages(*groups):
    return json.dumps(list(groups))


def comment(cid, msg, actor=ACTOR):
    return {"id": cid, "body": encode_comment(msg),
            "user": {"id": 79015263 if actor == ACTOR else 123456789,
                     "login": actor}}


def invalid_ref_comment(cid, msg):
    """Valid outer envelope, invalid evidence URL. The codec must reject it."""
    payload = {**msg, "evidence_refs": [
        "https://github.com/kinoko34077/devflow/pull/252#pullrequestreview-1234",
    ]}
    fence = chr(96) * 3
    return {"id": cid,
            "body": "<!-- kaep:message:v0.2 -->\n" + fence + "json\n"
                    + json.dumps(payload) + "\n" + fence,
            "user": {"id": 79015263, "login": ACTOR}}


def root(number, *, issue=ISSUE, recipient="claude-code"):
    msg, _ = make_request(
        pages([]), repository=REPO, issue=issue, recipient=recipient,
        intent="ANALYZE", expected_head="a" * 40,
        request_key=f"kaep.shadow.root.{number:04d}.{issue}",
        request_text="sanitized historical task body",
        expect_existing_actor=ACTOR,
    )
    return msg


def pointer_notice(msg, *, issue=ISSUE, cid, notice_id,
                   discovery_issue=DISCOVERY_ISSUE):
    pointer = {
        "type": POINTER_VERSION,
        "owning_issue": f"https://github.com/{REPO}/issues/{issue}",
        "message_id": msg["message_id"],
        "comment_id": cid,
    }
    notice, _ = make_request(
        pages([]), repository=REPO, issue=discovery_issue,
        recipient="claude-code",
        intent="REPORT", expected_head=None,
        request_key=f"kaep.shadow.pointer.{notice_id:04d}.{issue}",
        request_text=json.dumps(pointer, sort_keys=True, separators=(",", ":")),
        expect_existing_actor=ACTOR,
    )
    return notice


def compare(index, sources, *, max_sources=MAX_SOURCE_ISSUES,
            discovery_issue=DISCOVERY_ISSUE, isolate_invalid_wrapper=False,
            isolate_invalid_ref=False, index_after_id=0,
            index_batches=MAX_SHADOW_BATCHES):
    fetched = []
    def fetch(r, i):
        fetched.append((r, i))
        return sources[(r, i)]
    output = source_root_shadow(
        index, fetch_source=fetch, expected_notice_actor=ACTOR,
        expected_source_actor=ACTOR, max_sources=max_sources,
        discovery_issue=discovery_issue,
        isolate_invalid_wrapper=isolate_invalid_wrapper,
        isolate_invalid_ref=isolate_invalid_ref,
        index_after_id=index_after_id, index_batches=index_batches,
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

    def test_successor_index_roster_reads_verified_original_without_503(self):
        original = root(782)
        successor = pointer_notice(
            original, cid=701, notice_id=782,
            discovery_issue=APPROVED_SUCCESSOR_ISSUE,
        )
        out, fetched = compare(
            pages([comment(801, successor)]),
            {(REPO, ISSUE): pages([comment(701, original)])},
            discovery_issue=APPROVED_SUCCESSOR_ISSUE,
        )
        self.assertEqual(out["status"], "BOUNDED_CANDIDATE_SOURCE_READ")
        self.assertEqual(out["discovery_issue"], f"{REPO}#789")
        self.assertEqual(fetched, [(REPO, ISSUE)])
        self.assertEqual(out["issues"][0]["root_count"], 1)
        self.assertEqual(out["issues"][0]["roots"][0]["comparison"],
                         "INDEXED_AND_ORIGINAL")
        self.assertFalse(out["complete_source_universe"])
        self.assertFalse(out["can_authorize_execution"])

    def test_successor_rejects_legacy_task_ref_without_source_fetch(self):
        original = root(783)
        legacy = pointer_notice(original, cid=701, notice_id=783)
        out, fetched = compare(
            pages([comment(801, legacy)]), {},
            discovery_issue=APPROVED_SUCCESSOR_ISSUE,
        )
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["issues"], [])
        self.assertEqual(fetched, [])
        self.assertGreater(out["rejected_index_count"], 0)
        self.assertTrue(out["has_unknown_work"])

    def test_unapproved_successor_never_fetches_original(self):
        for invalid in (9001, True, "789", 0):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                InvalidMessage, "DISCOVERY_INDEX_NOT_APPROVED"
            ):
                compare(pages([]), {}, discovery_issue=invalid)

    def test_opt_in_malformed_source_does_not_starve_valid_peer(self):
        valid = root(810, issue=576)
        broken = root(811, issue=577)
        good_notice = pointer_notice(valid, issue=576, cid=601, notice_id=810)
        bad_notice = pointer_notice(broken, issue=577, cid=701, notice_id=811)
        malformed = {
            "id": 702,
            "body": "<!-- kaep:message:v0.2 -->\n\u0060\u0060\u0060json\n{}\n\u0060\u0060\u0060\nextra historical prose",
            "user": {"id": 79015263, "login": ACTOR},
        }
        index = pages([comment(901, good_notice), comment(902, bad_notice)])
        sources = {
            (REPO, 576): pages([comment(601, valid)]),
            (REPO, 577): pages([comment(701, broken), malformed]),
        }
        strict, reads = compare(index, sources)
        self.assertEqual(strict["status"], "BLOCKED")
        self.assertEqual(strict["issues"], [])
        self.assertEqual(reads, [(REPO, 576), (REPO, 577)])
        self.assertEqual(strict["index_blockers"], [
            {"index_comment_id": 902, "reason_code": "INVALID_WRAPPER"}
        ])

        diagnostic, reads = compare(
            index, sources, isolate_invalid_wrapper=True,
        )
        self.assertEqual(diagnostic["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(diagnostic["index_blockers"], [
            {"index_comment_id": 902, "reason_code": "INVALID_WRAPPER"}
        ])
        self.assertEqual(diagnostic["isolated_invalid_wrapper_sources"], 1)
        self.assertEqual(diagnostic["errors"], [
            {"reason_code": "INDEX_SOURCE_INCOMPLETE"}
        ])
        self.assertEqual(len(diagnostic["issues"]), 1)
        self.assertEqual(diagnostic["issues"][0]["owning_issue"],
                         f"https://github.com/{REPO}/issues/576")
        self.assertEqual(diagnostic["issues"][0]["roots"][0]["comparison"],
                         "INDEXED_AND_ORIGINAL")
        self.assertEqual(reads, [(REPO, 576), (REPO, 577)])
        self.assertTrue(diagnostic["has_unknown_work"])
        self.assertFalse(diagnostic["complete_source_universe"])
        self.assertFalse(diagnostic["can_authorize_execution"])
        self.assertFalse(diagnostic["fallback_retirement_authorized"])
        self.assertNotIn("extra historical prose", json.dumps(diagnostic))

    def test_b5_diagnostic_reaches_later_index_batch_without_claiming_coverage(self):
        bad_root = root(820, issue=577)
        good_root = root(821, issue=576)
        bad_notice = pointer_notice(bad_root, issue=577, cid=701,
                                    notice_id=820)
        good_notice = pointer_notice(good_root, issue=576, cid=601,
                                     notice_id=821)
        invalid = {
            "id": 702, "body": "<!-- kaep:message:v0.2 -->bad",
            "user": {"id": 79015263, "login": ACTOR},
        }
        index = pages([
            comment(1000 + n, bad_notice) if n == 1 else
            comment(1000 + n, good_notice) if n == 40 else
            {"id": 1000 + n, "body": "ordinary", "user": {
                "id": 79015263, "login": ACTOR}}
            for n in range(45)
        ])
        sources = {
            (REPO, 577): pages([comment(701, bad_root), invalid]),
            (REPO, 576): pages([comment(601, good_root)]),
        }
        strict, strict_reads = compare(index, sources)
        self.assertEqual(strict["status"], "BLOCKED")
        self.assertEqual(strict["issues"], [])
        self.assertEqual(strict_reads, [(REPO, 577)])

        diagnostic, reads = compare(index, sources,
                                    isolate_invalid_wrapper=True)
        self.assertEqual(diagnostic["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(diagnostic["index_hint_count"], 1)
        self.assertEqual(diagnostic["index_blockers"], [
            {"index_comment_id": 1001, "reason_code": "INVALID_WRAPPER"}
        ])
        self.assertEqual(diagnostic["isolated_invalid_wrapper_sources"], 1)
        self.assertEqual([r["owning_issue"] for r in diagnostic["issues"]],
                         [f"https://github.com/{REPO}/issues/576"])
        self.assertEqual(reads, [(REPO, 577), (REPO, 576)])
        self.assertTrue(diagnostic["has_unknown_work"])
        self.assertFalse(diagnostic["complete_source_universe"])
        self.assertFalse(diagnostic["can_authorize_execution"])

    def test_invalid_ref_requires_separate_opt_in_and_excludes_whole_issue(self):
        good = root(841, issue=576)
        bad = root(842, issue=577)
        good_notice = pointer_notice(good, issue=576, cid=601, notice_id=841)
        bad_notice = pointer_notice(bad, issue=577, cid=701, notice_id=842)
        index = pages([comment(901, good_notice), comment(902, bad_notice)])
        sources = {
            (REPO, 576): pages([comment(601, good)]),
            (REPO, 577): pages([comment(701, bad),
                                invalid_ref_comment(702, root(843, issue=577))]),
        }
        strict, _ = compare(index, sources)
        wrapper_only, _ = compare(index, sources, isolate_invalid_wrapper=True)
        self.assertEqual(strict["status"], "BLOCKED")
        self.assertEqual(wrapper_only["status"], "BLOCKED")
        self.assertEqual(wrapper_only["issues"], [])
        self.assertEqual(wrapper_only["index_blockers"], [
            {"index_comment_id": 902, "reason_code": "INVALID_REF"}
        ])
        diagnostic, reads = compare(index, sources,
                                    isolate_invalid_wrapper=True,
                                    isolate_invalid_ref=True)
        self.assertEqual(diagnostic["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(diagnostic["isolated_invalid_ref_sources"], 1)
        self.assertEqual(diagnostic["isolated_invalid_wrapper_sources"], 0)
        self.assertEqual(diagnostic["index_blockers"], [
            {"index_comment_id": 902, "reason_code": "INVALID_REF"}
        ])
        self.assertEqual([x["owning_issue"] for x in diagnostic["issues"]],
                         [f"https://github.com/{REPO}/issues/576"])
        self.assertEqual(reads, [(REPO, 576), (REPO, 577)])
        self.assertTrue(diagnostic["has_unknown_work"])
        self.assertFalse(diagnostic["complete_source_universe"])
        self.assertFalse(diagnostic["can_authorize_execution"])
        self.assertFalse(diagnostic["fallback_retirement_authorized"])
        self.assertNotIn("pullrequestreview-", json.dumps(diagnostic))

    def test_mixed_ref_and_wrapper_reaches_later_batch_safe_cursor_pinned(self):
        wrapper_root = root(844, issue=577)
        ref_root = root(845, issue=578)
        good_root = root(846, issue=576)
        notices = {
            1: pointer_notice(wrapper_root, issue=577, cid=701, notice_id=844),
            2: pointer_notice(ref_root, issue=578, cid=801, notice_id=845),
            40: pointer_notice(good_root, issue=576, cid=601, notice_id=846),
        }
        index = pages([
            comment(1000 + n, notices[n]) if n in notices else
            {"id": 1000 + n, "body": "ordinary",
             "user": {"id": 79015263, "login": ACTOR}}
            for n in range(45)
        ])
        fence = chr(96) * 3
        sources = {
            (REPO, 577): pages([
                comment(701, wrapper_root),
                {"id": 702, "body": "<!-- kaep:message:v0.2 -->\n"
                 + fence + "json\n{}\n" + fence + "\nextra",
                 "user": {"id": 79015263, "login": ACTOR}},
            ]),
            (REPO, 578): pages([
                comment(801, ref_root),
                invalid_ref_comment(802, root(847, issue=578)),
            ]),
            (REPO, 576): pages([comment(601, good_root)]),
        }
        strict, _ = compare(index, sources)
        wrapper_only, _ = compare(index, sources,
                                  isolate_invalid_wrapper=True)
        self.assertEqual(strict["status"], "BLOCKED")
        self.assertEqual(wrapper_only["status"], "BLOCKED")
        diagnostic, reads = compare(index, sources,
                                    isolate_invalid_wrapper=True,
                                    isolate_invalid_ref=True)
        self.assertEqual(diagnostic["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(diagnostic["index_hint_count"], 1)
        self.assertEqual(diagnostic["isolated_invalid_wrapper_sources"], 1)
        self.assertEqual(diagnostic["isolated_invalid_ref_sources"], 1)
        self.assertEqual(diagnostic["index_blockers"], [
            {"index_comment_id": 1001, "reason_code": "INVALID_WRAPPER"},
            {"index_comment_id": 1002, "reason_code": "INVALID_REF"},
        ])
        self.assertEqual([x["owning_issue"] for x in diagnostic["issues"]],
                         [f"https://github.com/{REPO}/issues/576"])
        self.assertEqual(reads, [(REPO, 577), (REPO, 578), (REPO, 576)])
        from tools.kaep_discovery_reader import discover_index_shadow
        shadow = discover_index_shadow(
            index, expected_notice_actor=ACTOR,
            expected_source_actor=ACTOR,
            fetch_source=lambda r, i: sources[(r, i)],
            diagnostic_scan_after_blocked=True,
            diagnostic_isolate_invalid_ref=True)
        self.assertEqual(shadow["status"], "PARTIAL_BLOCKED")
        self.assertEqual(shadow["next_after_id"], 1000)
        self.assertTrue(shadow["truncated"])
        self.assertFalse(shadow["fallback_retirement_authorized"])

    def test_invalid_ref_task_only_quarantine_preserves_nonref_errors(self):
        good = root(848, issue=576)
        bad = root(849, issue=577)
        sources = {
            (REPO, 576): pages([comment(601, good)]),
            (REPO, 577): pages([comment(701, bad),
                                invalid_ref_comment(702, root(850, issue=577))]),
        }
        def fetch(r, i):
            return sources[(r, i)]
        def inspect():
            return source_root_shadow(
                pages([]), fetch_source=fetch,
                expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                task_views=[self.task_view([576, 577])],
                isolate_invalid_wrapper=True, isolate_invalid_ref=True)
        out = inspect()
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["isolated_invalid_ref_sources"], 1)
        self.assertEqual(len(out["issues"]), 1)
        self.assertEqual(out["errors"][-1], {
            "owning_issue": f"https://github.com/{REPO}/issues/577",
            "reason_code": "INVALID_REF",
        })
        fence = chr(96) * 3
        sources[(REPO, 577)] = pages([
            comment(701, bad),
            {"id": 702,
             "body": "<!-- kaep:message:v0.2 -->\n" + fence
                     + "json\n{}\n" + fence,
             "user": {"id": 79015263, "login": ACTOR}},
        ])
        blocked = inspect()
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertEqual(blocked["errors"][-1]["reason_code"], "INVALID_FIELDS")
        self.assertEqual(blocked["isolated_invalid_ref_sources"], 0)

    def test_invalid_ref_diagnostic_never_bypasses_hard_source_cap(self):
        poisoned = root(851, issue=577)
        clean_a = root(852, issue=576)
        clean_b = root(853, issue=578)
        index = pages([
            comment(901, pointer_notice(poisoned, issue=577,
                                        cid=701, notice_id=851)),
            comment(902, pointer_notice(clean_a, issue=576,
                                        cid=601, notice_id=852)),
            comment(903, pointer_notice(clean_b, issue=578,
                                        cid=801, notice_id=853)),
        ])
        sources = {
            (REPO, 577): pages([
                comment(701, poisoned),
                invalid_ref_comment(702, root(854, issue=577)),
            ]),
            (REPO, 576): pages([comment(601, clean_a)]),
            (REPO, 578): pages([comment(801, clean_b)]),
        }
        result, fetched = compare(index, sources, max_sources=2,
                                  isolate_invalid_wrapper=True,
                                  isolate_invalid_ref=True)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["issues"], [])
        self.assertIn("CANDIDATE_LIMIT",
                      [x["reason_code"] for x in result["index_blockers"]])
        self.assertEqual(fetched, [(REPO, 577), (REPO, 576)])
        self.assertFalse(result["can_authorize_execution"])

    def test_index_ref_quarantine_requires_explicit_scan_mode(self):
        from tools.kaep_discovery_reader import discover_index_shadow
        with self.assertRaisesRegex(InvalidMessage, "INVALID_DIAGNOSTIC_SCAN_MODE"):
            discover_index_shadow(
                pages([]), expected_notice_actor=ACTOR,
                expected_source_actor=ACTOR,
                fetch_source=lambda *_: pages([]),
                diagnostic_isolate_invalid_ref=True,
            )

    def test_bounded_index_windows_read_45_sources_without_raising_cap(self):
        # The ordinary full-index read still hits the 40-Issue ceiling.
        sources = {}
        indexed = []
        for n in range(45):
            issue = 600 + n
            root_message = root(900 + n, issue=issue)
            root_id = 1000 + n
            sources[(REPO, issue)] = pages([comment(root_id, root_message)])
            notice = pointer_notice(root_message, issue=issue, cid=root_id,
                                    notice_id=900 + n)
            indexed.append(comment(2000 + n, notice))
        index = pages(indexed)
        blocked, fetched = compare(
            index, sources, max_sources=40,
            isolate_invalid_wrapper=True, isolate_invalid_ref=True)
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertEqual(len(fetched), 40)
        self.assertEqual(blocked["issues"], [])
        self.assertIn("CANDIDATE_LIMIT",
                      [x["reason_code"] for x in blocked["index_blockers"]])

        first, fetched = compare(
            index, sources, max_sources=40,
            isolate_invalid_wrapper=True, isolate_invalid_ref=True,
            index_batches=2)
        self.assertEqual(first["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(len(fetched), 40)
        self.assertEqual(len(first["issues"]), 40)
        self.assertTrue(first["index_window_explicit"])
        self.assertFalse(first["index_scan_exhausted"])
        self.assertTrue(first["index_truncated"])
        self.assertEqual(first["index_scanned_batches"], 2)
        self.assertEqual(first["index_next_diagnostic_after_id"], 2039)
        self.assertEqual(first["index_safe_after_id"], 2039)
        self.assertEqual(first["index_hint_count"], 40)
        self.assertFalse(first["complete_source_universe"])
        self.assertTrue(first["has_unknown_work"])
        self.assertFalse(first["can_authorize_execution"])
        self.assertFalse(first["fallback_retirement_authorized"])

        second, fetched = compare(
            index, sources, max_sources=40,
            isolate_invalid_wrapper=True, isolate_invalid_ref=True,
            index_after_id=first["index_next_diagnostic_after_id"],
            index_batches=2)
        self.assertEqual(second["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(len(fetched), 5)
        self.assertEqual(len(second["issues"]), 5)
        self.assertTrue(second["index_scan_exhausted"])
        self.assertFalse(second["index_truncated"])
        self.assertIsNone(second["index_next_diagnostic_after_id"])
        self.assertEqual(second["index_safe_after_id"], 2044)
        self.assertEqual(len({
            entry["owning_issue"] for entry in first["issues"] + second["issues"]
        }), 45)
        self.assertFalse(second["complete_source_universe"])

    def test_index_window_preserves_safe_cursor_with_poisoned_first_batch(self):
        bad_root = root(871, issue=577)
        ok_root = root(872, issue=576)
        notice_bad = pointer_notice(bad_root, issue=577, cid=701, notice_id=871)
        notice_ok = pointer_notice(ok_root, issue=576, cid=601, notice_id=872)
        index = pages([
            comment(1000 + n, notice_bad) if n == 1 else
            comment(1000 + n, notice_ok) if n == 24 else
            {"id": 1000 + n, "body": "ordinary",
             "user": {"id": 79015263, "login": ACTOR}}
            for n in range(35)
        ])
        fence = chr(96) * 3
        sources = {
            (REPO, 577): pages([
                comment(701, bad_root),
                {"id": 702,
                 "body": "<!-- kaep:message:v0.2 -->\n"
                         + fence + "json\n{}\n" + fence + "\nextra",
                 "user": {"id": 79015263, "login": ACTOR}},
            ]),
            (REPO, 576): pages([comment(601, ok_root)]),
        }
        first, _ = compare(
            index, sources, isolate_invalid_wrapper=True,
            index_batches=1)
        self.assertEqual(first["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(first["index_safe_after_id"], 1000)
        self.assertEqual(first["index_next_diagnostic_after_id"], 1019)
        self.assertEqual(first["isolated_invalid_wrapper_sources"], 1)
        self.assertEqual(first["issues"], [])
        second, _ = compare(
            index, sources, isolate_invalid_wrapper=True,
            index_after_id=first["index_next_diagnostic_after_id"],
            index_batches=1)
        self.assertEqual(second["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(second["index_after_id"], 1019)
        self.assertTrue(second["index_scan_exhausted"])
        self.assertIsNone(second["index_next_diagnostic_after_id"])
        self.assertEqual(second["index_safe_after_id"], 1034)
        self.assertEqual(len(second["issues"]), 1)
        self.assertEqual(second["issues"][0]["roots"][0]["comparison"],
                         "INDEXED_AND_ORIGINAL")
        self.assertFalse(first["complete_source_universe"])
        self.assertFalse(second["complete_source_universe"])

    def test_index_windows_never_bypass_source_cap_and_refuse_invalid_args(self):
        r1 = root(875, issue=576)
        r2 = root(876, issue=577)
        index = pages([
            comment(901, pointer_notice(r1, issue=576,
                                        cid=601, notice_id=875)),
            comment(902, pointer_notice(r2, issue=577,
                                        cid=701, notice_id=876)),
        ])
        sources = {
            (REPO, 576): pages([comment(601, r1)]),
            (REPO, 577): pages([comment(701, r2)]),
        }
        capped, fetched = compare(
            index, sources, max_sources=1,
            isolate_invalid_wrapper=True,
            index_batches=1)
        self.assertEqual(capped["status"], "BLOCKED")
        self.assertIn("CANDIDATE_LIMIT",
                      [b["reason_code"] for b in capped["index_blockers"]])
        self.assertEqual(capped["issues"], [])
        self.assertEqual(fetched, [(REPO, 576)])
        self.assertIsNone(capped["index_next_diagnostic_after_id"])
        for invalid in (0, 11, True, "2"):
            with self.subTest(batches=invalid), self.assertRaisesRegex(
                    InvalidMessage, "INVALID_INDEX_WINDOW"):
                compare(index, sources, index_batches=invalid,
                        isolate_invalid_wrapper=True)
        for invalid in (-1, True, "901"):
            with self.subTest(after_id=invalid), self.assertRaisesRegex(
                    InvalidMessage, "INVALID_INDEX_WINDOW"):
                compare(index, sources, index_after_id=invalid,
                        isolate_invalid_wrapper=True)
        with self.assertRaisesRegex(
                InvalidMessage, "INDEX_WINDOW_REQUIRES_DIAGNOSTIC"):
            compare(index, sources, index_batches=1)

    def test_failed_task_source_has_no_diagnostic_next_cursor(self):
        # A clean index-window scan cannot overrule later full-source failure.
        index = pages([
            {"id": 2000 + n, "body": "ordinary",
             "user": {"id": 79015263, "login": ACTOR}}
            for n in range(25)
        ])
        bad = root(880, issue=577)
        fence = chr(96) * 3
        bad_source = pages([
            comment(701, bad),
            {"id": 702,
             "body": "<!-- kaep:message:v0.2 -->\n"
                     + fence + "json\n{}\n" + fence,
             "user": {"id": 79015263, "login": ACTOR}},
        ])
        output = source_root_shadow(
            index, fetch_source=lambda *_: bad_source,
            expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
            task_views=[self.task_view([577])],
            isolate_invalid_wrapper=True,
            index_batches=1,
        )
        self.assertEqual(output["status"], "BLOCKED")
        self.assertEqual(output["source_status"], "BOUNDED_TRUNCATED")
        self.assertEqual(output["errors"][-1]["reason_code"], "INVALID_FIELDS")
        self.assertIsNone(output["index_next_diagnostic_after_id"])
        self.assertEqual(output["issues"], [])
        self.assertFalse(output["can_authorize_execution"])

    def test_cli_index_window_rejected_before_external_get(self):
        with (patch("tools.kaep_source_roster_shadow.fetch_gh_pages") as fetch,
              redirect_stdout(io.StringIO()) as capture):
            rc = main(["--expect-notice-actor", ACTOR,
                       "--expect-source-actor", ACTOR,
                       "--index-batches", "1"])
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(capture.getvalue())["reason_code"],
                         "INDEX_WINDOW_REQUIRES_DIAGNOSTIC")
        fetch.assert_not_called()
        with (patch("tools.kaep_source_roster_shadow.fetch_gh_pages",
                    return_value=pages([])) as fetch,
              redirect_stdout(io.StringIO()) as capture):
            rc = main(["--expect-notice-actor", ACTOR,
                       "--expect-source-actor", ACTOR,
                       "--isolate-invalid-wrapper",
                       "--index-batches", "1"])
        self.assertEqual(rc, 2)
        data = json.loads(capture.getvalue())
        self.assertEqual(data["status"], "PARTIAL_UNKNOWN")
        self.assertTrue(data["index_window_explicit"])
        self.assertTrue(data["index_scan_exhausted"])
        self.assertIsNone(data["index_next_diagnostic_after_id"])
        fetch.assert_called_once_with(REPO, 503)

    def test_invalid_ref_flag_without_wrapper_fails_before_get(self):
        with self.assertRaisesRegex(InvalidMessage, "INVALID_DIAGNOSTIC_MODE"):
            compare(pages([]), {}, isolate_invalid_ref=True)
        with (patch("tools.kaep_source_roster_shadow.fetch_gh_pages") as fetch,
              redirect_stdout(io.StringIO()) as capture):
            rc = main(["--expect-notice-actor", ACTOR,
                       "--expect-source-actor", ACTOR,
                       "--isolate-invalid-ref"])
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(capture.getvalue())["reason_code"],
                         "INVALID_DIAGNOSTIC_MODE")
        fetch.assert_not_called()
        with (patch("tools.kaep_source_roster_shadow.fetch_gh_pages",
                    return_value=pages([])) as fetch,
              redirect_stdout(io.StringIO()) as capture):
            rc = main(["--expect-notice-actor", ACTOR,
                       "--expect-source-actor", ACTOR,
                       "--isolate-invalid-wrapper", "--isolate-invalid-ref"])
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(capture.getvalue())["status"],
                         "PARTIAL_UNKNOWN")
        fetch.assert_called_once_with(REPO, 503)

    def test_opt_in_cannot_isolate_non_wrapper_source_failure(self):
        valid = root(812, issue=576)
        broken = root(813, issue=577)
        good_notice = pointer_notice(valid, issue=576, cid=601, notice_id=812)
        bad_notice = pointer_notice(broken, issue=577, cid=701, notice_id=813)
        malformed = {
            "id": 702,
            "body": "<!-- kaep:message:v0.2 -->\n\u0060\u0060\u0060json\n{}\n\u0060\u0060\u0060",
            "user": {"id": 79015263, "login": ACTOR},
        }
        out, _ = compare(
            pages([comment(901, good_notice), comment(902, bad_notice)]),
            {
                (REPO, 576): pages([comment(601, valid)]),
                (REPO, 577): pages([comment(701, broken), malformed]),
            }, isolate_invalid_wrapper=True,
        )
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["issues"], [])
        self.assertEqual(out["isolated_invalid_wrapper_sources"], 0)
        self.assertEqual(out["index_blockers"][-1]["reason_code"], "INVALID_FIELDS")

    def test_opt_in_isolates_malformed_independent_task_source(self):
        good = root(814, issue=576)
        corrupted = root(815, issue=577)
        invalid = {
            "id": 703,
            "body": "<!-- kaep:message:v0.2 -->\n\u0060\u0060\u0060json\n{}\n\u0060\u0060\u0060\nextra",
            "user": {"id": 79015263, "login": ACTOR},
        }
        source_map = {
            (REPO, 576): pages([comment(601, good)]),
            (REPO, 577): pages([comment(701, corrupted), invalid]),
        }
        calls = []

        def fetch(repo, issue):
            calls.append((repo, issue))
            return source_map[(repo, issue)]

        view = self.task_view([576, 577])
        strict = source_root_shadow(
            pages([]), fetch_source=fetch,
            expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
            task_views=[view],
        )
        self.assertEqual(strict["status"], "BLOCKED")
        self.assertEqual(len(strict["issues"]), 1)
        calls.clear()
        isolated = source_root_shadow(
            pages([]), fetch_source=fetch,
            expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
            task_views=[view], isolate_invalid_wrapper=True,
        )
        self.assertEqual(isolated["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(len(isolated["issues"]), 1)
        self.assertEqual(isolated["isolated_invalid_wrapper_sources"], 1)
        self.assertEqual(isolated["errors"][-1]["owning_issue"],
                         f"https://github.com/{REPO}/issues/577")
        self.assertEqual(isolated["errors"][-1]["reason_code"], "INVALID_WRAPPER")
        self.assertFalse(isolated["can_authorize_execution"])
        self.assertFalse(isolated["complete_source_universe"])
        self.assertEqual(calls, [(REPO, 576), (REPO, 577)])

    def test_invalid_diagnostic_type_fails_without_fetching_sources(self):
        from tools.kaep_inbox_reader import InvalidMessage
        with self.assertRaisesRegex(InvalidMessage, "INVALID_DIAGNOSTIC_MODE"):
            compare(pages([]), {}, isolate_invalid_wrapper="true")

    def test_diagnostic_cli_flag_explicit_and_non_authoritative(self):
        with (patch("tools.kaep_source_roster_shadow.fetch_gh_pages",
                    return_value=pages([])) as fetch,
              redirect_stdout(io.StringIO()) as capture):
            rc = main([
                "--expect-notice-actor", ACTOR,
                "--expect-source-actor", ACTOR,
                "--isolate-invalid-wrapper",
            ])
        data = json.loads(capture.getvalue())
        self.assertEqual(rc, 2)
        self.assertEqual(data["status"], "PARTIAL_UNKNOWN")
        self.assertTrue(data["diagnostic_isolation_enabled"])
        self.assertFalse(data["complete_source_universe"])
        self.assertFalse(data["can_authorize_execution"])
        fetch.assert_called_once_with(REPO, 503)

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
                     "body": "<!-- kaep:message:v0.2 -->\n```json\n{}\n```\nUntrusted prose",
                     "user": {"id": 79015263, "login": ACTOR}}
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
                   "user": {"id": 79015263, "login": ACTOR}}
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
