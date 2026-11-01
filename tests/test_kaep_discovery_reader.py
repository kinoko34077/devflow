"""Strict KAEP discovery reader tests, all in memory and read-only."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tools import agent_inbox
from tools.kaep_mailbox_codec import encode_comment, InvalidMessage
from tools.kaep_inbox_reader import inspect_pages, parse_pages
from tools.kaep_request_sender import make_request
from tools.kaep_discovery_reader import (
    discover, discover_batch, discover_index_shadow, parse_pointer,
    POINTER_VERSION, MAX_INDEX_BATCH, MAX_SHADOW_BATCHES,
)
from tools.kaep_route_notice import DISCOVERY_REPOSITORY, DISCOVERY_ISSUE
from tools.kaep_reply_sender import _mailbox

SOURCE_REPO = "kinoko34077/UniverseGenome"
SOURCE_ISSUE = 336
ACTOR = "kinoko34077"
ACTOR_ID = 79015263


def pages(*groups):
    return json.dumps(list(groups))


def actor_user(actor=ACTOR):
    return {"login": actor, "id": ACTOR_ID if actor == ACTOR else 999999999}


def comment(cid, msg, actor=ACTOR):
    return {"id": cid, "body": encode_comment(msg), "user": actor_user(actor)}


def fixtures():
    root, _ = make_request(
        pages([]), repository=SOURCE_REPO, issue=SOURCE_ISSUE,
        recipient="claude-code", intent="ANALYZE", expected_head="a" * 40,
        request_key="kaep.discovery.source0001", request_text="source payload private",
        expect_existing_actor=ACTOR)
    pointer = {
        "type": POINTER_VERSION,
        "owning_issue": f"https://github.com/{SOURCE_REPO}/issues/{SOURCE_ISSUE}",
        "message_id": root["message_id"],
        "comment_id": 77,
    }
    hint, _ = make_request(
        pages([]), repository=DISCOVERY_REPOSITORY, issue=DISCOVERY_ISSUE,
        recipient="claude-code", intent="REPORT",
        request_key=f"kaep.discovery.{root['message_id']}",
        request_text=json.dumps(pointer, sort_keys=True, separators=(",", ":")),
        expect_existing_actor=ACTOR)
    return root, hint, pointer


def other_notice(text: str, key: str):
    msg, _ = make_request(
        pages([]), repository=DISCOVERY_REPOSITORY, issue=DISCOVERY_ISSUE,
        recipient="claude-code", intent="REPORT", request_key=key,
        request_text=text, expect_existing_actor=ACTOR)
    return msg


def read(index, source, *, after_id=0, notice_actor=ACTOR, source_actor=ACTOR):
    return discover(index, expected_notice_actor=notice_actor,
                    expected_source_actor=source_actor,
                    after_id=after_id, fetch_source=lambda r, i: source)


class DiscoveryReaderTests(unittest.TestCase):
    def test_multiple_pointers_to_one_source_decode_one_complete_mailbox(self):
        root, first_notice, pointer = fixtures()
        second_notice = other_notice(
            json.dumps(pointer), "kaep.discovery.second.notice0002",
        )
        original = pages([comment(77, root)])
        index = pages([comment(88, first_notice), comment(89, second_notice)])
        fetched = []

        def fetch_source(repository, issue):
            fetched.append((repository, issue))
            return original

        # Prior code: verify_source_request + _source_context per pointer,
        # resulting in four full mailbox decodes for these two notices.
        with patch("tools.kaep_discovery_reader._mailbox",
                   wraps=_mailbox) as strict_read:
            result = discover_batch(
                index, expected_notice_actor=ACTOR,
                expected_source_actor=ACTOR, fetch_source=fetch_source,
            )
        self.assertEqual(fetched, [(SOURCE_REPO, SOURCE_ISSUE)])
        self.assertEqual(strict_read.call_count, 1)
        self.assertEqual(len(result["hints"]), 2)
        self.assertEqual(result["blocked"], [])
        self.assertEqual(result["rejected"], [])
        self.assertEqual(
            {item["source_message_id"] for item in result["hints"]},
            {root["message_id"]},
        )

    def test_source_proof_reused_for_same_root_but_each_pointer_is_checked(self):
        root, first_notice, pointer = fixtures()
        second_notice = other_notice(
            json.dumps(pointer), "kaep.discovery.proof.second.notice",
        )
        forged = dict(pointer)
        forged["comment_id"] = 78
        tampered_notice = other_notice(
            json.dumps(forged), "kaep.discovery.proof.tampered.notice",
        )
        index = pages([
            comment(1000 + n, {
                0: first_notice, 35: second_notice, 40: tampered_notice,
            }[n]) if n in (0, 35, 40) else {
                "id": 1000 + n, "body": "operator note",
                "user": actor_user(),
            }
            for n in range(42)
        ])
        fetched = []
        def fetch_source(repository, issue):
            fetched.append((repository, issue))
            return pages([comment(77, root)])
        from tools import kaep_discovery_reader as reader
        with (patch.object(reader, "_verify_source_request_from_snapshot",
                           wraps=reader._verify_source_request_from_snapshot) as verified,
              patch.object(reader, "_source_context",
                           wraps=reader._source_context) as context):
            out = discover_index_shadow(
                index, expected_notice_actor=ACTOR,
                expected_source_actor=ACTOR, fetch_source=fetch_source)
        self.assertEqual(verified.call_count, 1)
        self.assertEqual(context.call_count, 1)
        self.assertEqual(fetched, [(SOURCE_REPO, SOURCE_ISSUE)])
        self.assertEqual(out["scanned_batches"], 3)
        self.assertEqual(len(out["hints"]), 1)
        self.assertEqual(out["duplicate_verified_pointers"], 1)
        self.assertEqual(out["rejected"], [{
            "index_comment_id": 1040,
            "reason_code": "DISCOVERY_SOURCE_MISMATCH",
        }])
        self.assertEqual(out["blocked"], [])
        self.assertEqual(out["hints"][0]["source_comment_id"], 77)
        self.assertFalse(out["complete_work_inventory"])

    def test_valid_pointer_has_actual_root_and_no_payload(self):
        root, hint, pointer = fixtures()
        x = read(pages([comment(88, hint)]), pages([comment(77, root)]))
        self.assertEqual(len(x), 1)
        self.assertEqual(x[0]["index_comment_id"], 88)
        self.assertEqual(x[0]["source_message_id"], pointer["message_id"])
        self.assertEqual(x[0]["status"], "POINTER_SOURCE_VERIFIED_ONLY")
        self.assertNotIn("source payload private", json.dumps(x))

    def test_b5_real_unclassified_576_root_needs_pointer_not_task_selection(self):
        """Sanitized replay of verified #576/#503 source IDs, never live task admission.

        Source: devflow #576 comment 6198495044 and #503 comment 6198497020.
        The original read-only REQUEST payload is intentionally not copied.
        """
        repo, issue = "kinoko34077/devflow", 576
        root_id = "msg_cursor576_claude_delta_review_20261016d"
        head = "eef92defe34d5dadbde79c3c379581769ea3a6fe"
        root, _ = make_request(
            pages([]), repository=repo, issue=issue,
            recipient="claude-code", intent="ANALYZE", expected_head=head,
            request_key="kaep.cursor576.delta.eef92defe34d5dadbde79c3c",
            request_text="redacted public source; read-only audit",
            expect_existing_actor=ACTOR,
        )
        root.update(
            exchange_id="ex_cursor576_claude_delta_review_20261016d",
            message_id=root_id,
        )
        pointer = {
            "type": POINTER_VERSION,
            "owning_issue": f"https://github.com/{repo}/issues/{issue}",
            "message_id": root_id,
            "comment_id": 6198495044,
        }
        notice, _ = make_request(
            pages([]), repository=DISCOVERY_REPOSITORY, issue=DISCOVERY_ISSUE,
            recipient="claude-code", intent="REPORT",
            request_key="kaep.discovery.cursor576.delta.eef92defe34d5dadbde79c3c",
            request_text=json.dumps(pointer, sort_keys=True, separators=(",", ":")),
            expect_existing_actor=ACTOR,
        )

        # The real #576 is open but lacks a trusted TASK metadata marker.
        # The M3-derived Inbox must not pretend it is a complete work inventory.
        task_view = {
            "repository": repo, "source_status": "AVAILABLE",
            "source_freshness": "CURRENT", "coverage_status": "INCOMPLETE",
            "task_records": [],
            "observed_task_view": {
                "status": "INCOMPLETE", "known_task_count": 0,
                "unresolved_open_issue_count": 1, "is_complete_read": False,
            },
            "manual_control": {"active_work": "retain original Issue/#503 pointer"},
        }
        selected = agent_inbox.select_task_records(task_view, recipient="claude-code")
        self.assertEqual(selected["selected"], [])
        self.assertEqual(selected["coverage_status"], "INCOMPLETE")
        self.assertEqual(selected["unresolved_open_issue_count"], 1)
        self.assertFalse(selected["is_full_work_inventory"])
        self.assertFalse(selected["can_authorize_execution"])

        fetched = []
        def fetch_source(repository, issue_number):
            fetched.append((repository, issue_number))
            return pages([comment(6198495044, root)])

        discovered = discover_batch(
            pages([comment(6198497020, notice)]),
            expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
            fetch_source=fetch_source,
        )
        self.assertEqual(fetched, [(repo, issue)])
        self.assertEqual(discovered["status"], "READ_ONLY")
        self.assertEqual(discovered["rejected"], [])
        self.assertEqual(discovered["blocked"], [])
        self.assertFalse(discovered["truncated"])
        self.assertEqual(len(discovered["hints"]), 1)
        self.assertEqual(discovered["hints"][0]["owning_issue"], pointer["owning_issue"])
        self.assertEqual(discovered["hints"][0]["source_comment_id"], 6198495044)
        self.assertEqual(discovered["hints"][0]["source_message_id"], root_id)
        self.assertEqual(discovered["hints"][0]["expected_head"], head)
        self.assertEqual(discovered["hints"][0]["status"], "POINTER_SOURCE_VERIFIED_ONLY")
        self.assertTrue(discovered["read_only"])
        self.assertFalse(discovered["peer_identity_verified"])
        self.assertNotIn("redacted public source", json.dumps(discovered))
    def test_b5_unindexed_576_root_visible_only_in_original_issue_reader(self):
        """Sanitized reencoding of real #576 old root absent from #503.

        Immutable source/comment IDs match the read-only public evidence, but
        no original prompt prose is copied. This is not a live provider read.
        A clean index scan never certifies complete original-root coverage.
        """
        repo, issue = "kinoko34077/devflow", 576
        old_id = "msg_cursor576_readonly_audit_20261015a"
        new_id = "msg_cursor576_claude_delta_review_20261016d"
        old, _ = make_request(
            pages([]), repository=repo, issue=issue,
            recipient="claude-code", intent="ANALYZE",
            expected_head="60cf73abd166e14d34d73e8821589fc6cb412c57",
            request_key="kaep.cursor576.oldroot.20261015a",
            request_text="sanitized historical read-only request",
            expect_existing_actor=ACTOR,
        )
        old.update(exchange_id="ex_cursor576_readonly_audit_20261015a",
                   message_id=old_id)
        new, _ = make_request(
            pages([]), repository=repo, issue=issue,
            recipient="claude-code", intent="ANALYZE",
            expected_head="eef92defe34d5dadbde79c3c379581769ea3a6fe",
            request_key="kaep.cursor576.newroot.20261016d",
            request_text="sanitized newer read-only request",
            expect_existing_actor=ACTOR,
        )
        new.update(exchange_id="ex_cursor576_claude_delta_review_20261016d",
                   message_id=new_id)
        source_pages = pages([comment(6193914061, old),
                              comment(6198495044, new)])
        pointer = {
            "type": POINTER_VERSION,
            "owning_issue": f"https://github.com/{repo}/issues/{issue}",
            "message_id": new_id, "comment_id": 6198495044,
        }
        hint, _ = make_request(
            pages([]), repository=DISCOVERY_REPOSITORY, issue=DISCOVERY_ISSUE,
            recipient="claude-code", intent="REPORT",
            request_key="kaep.discovery.cursor576.newroot.20261016d",
            request_text=json.dumps(pointer, sort_keys=True, separators=(",", ":")),
            expect_existing_actor=ACTOR,
        )
        # Pointer path completes cleanly: it sees only the newer specific root.
        shadow = discover_index_shadow(
            pages([comment(6198497020, hint)]),
            expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
            fetch_source=lambda r, n: source_pages,
        )
        self.assertEqual(shadow["status"], "INDEX_EXHAUSTED_SOURCE_VERIFIED_ONLY")
        self.assertEqual(len(shadow["hints"]), 1)
        self.assertEqual(shadow["hints"][0]["source_message_id"], new_id)
        self.assertFalse(shadow["complete_work_inventory"])
        self.assertFalse(shadow["fallback_retirement_authorized"])

        # The already-accepted direct original-Issue reader sees BOTH roots.
        direct = inspect_pages(
            source_pages, repository=repo, issue=issue, recipient="claude-code")
        self.assertEqual(
            [(row["comment_id"], row["message_id"]) for row in direct["messages"]],
            [(6193914061, old_id), (6198495044, new_id)])
        indexed_ids = {item["source_message_id"] for item in shadow["hints"]}
        self.assertEqual({row["message_id"] for row in direct["messages"]} - indexed_ids,
                         {old_id})
        self.assertNotIn("sanitized historical", json.dumps(shadow))
        self.assertNotIn("sanitized historical", json.dumps(direct))
        # This test does not create or infer a TASK, an actionable live HEAD,
        # provider pickup, source-universe completeness, or recipient authority.

    def test_shadow_bounded_full_65_comment_index_with_21_strict_roots(self):
        """Index-only completeness: 21 verified roots / 65 comments / 4 batches."""
        sources = {}
        hints = {}
        for n in range(21):
            issue = 400 + n
            root, _ = make_request(
                pages([]), repository=SOURCE_REPO, issue=issue,
                recipient="claude-code", intent="ANALYZE",
                expected_head="a" * 40,
                request_key=f"kaep.shadow.root.{n:03d}",
                request_text="hidden source payload",
                expect_existing_actor=ACTOR,
            )
            source_id = 500 + n
            sources[(SOURCE_REPO, issue)] = pages([comment(source_id, root)])
            pointer = {
                "type": POINTER_VERSION,
                "owning_issue": f"https://github.com/{SOURCE_REPO}/issues/{issue}",
                "message_id": root["message_id"], "comment_id": source_id,
            }
            hint = other_notice(json.dumps(pointer), f"kaep.shadow.notice.{n:03d}")
            hints[2 + n * 3] = hint
        index = pages([
            comment(1000 + n, hints[n]) if n in hints
            else {"id": 1000 + n, "body": "operator note",
                  "user": actor_user()}
            for n in range(65)
        ])
        reads = []
        def get_source(repo, issue):
            reads.append((repo, issue))
            return sources[(repo, issue)]
        with patch("tools.kaep_discovery_reader.parse_pages",
                   wraps=parse_pages) as strict_pages:
            out = discover_index_shadow(
                index, expected_notice_actor=ACTOR,
                expected_source_actor=ACTOR, fetch_source=get_source)
        # Four 20-comment batches must share ONE complete, strictly
        # validated index parse rather than rescanning the JSON four times.
        self.assertEqual(strict_pages.call_count, 1)
        self.assertEqual(out["status"], "INDEX_EXHAUSTED_SOURCE_VERIFIED_ONLY")
        self.assertEqual(len(out["hints"]), 21)
        self.assertEqual(out["scanned_batches"], 4)
        self.assertEqual(out["distinct_source_issue_count"], 21)
        self.assertEqual(len(reads), 21)
        self.assertEqual(out["next_after_id"], 1064)
        self.assertEqual(out["rejected"], [])
        self.assertEqual(out["blocked"], [])
        self.assertFalse(out["truncated"])
        self.assertTrue(out["read_only"])
        self.assertFalse(out["peer_identity_verified"])
        self.assertFalse(out["complete_work_inventory"])
        self.assertFalse(out["fallback_retirement_authorized"])
        self.assertNotIn("hidden source payload", json.dumps(out))

    def test_shadow_and_public_batch_parse_once_per_independent_entry(self):
        root, hint, _ = fixtures()
        index = pages([comment(88, hint)])
        source = lambda _repo, _issue: pages([comment(77, root)])
        with patch("tools.kaep_discovery_reader.parse_pages",
                   wraps=parse_pages) as strict_pages:
            first = discover_batch(
                index, expected_notice_actor=ACTOR,
                expected_source_actor=ACTOR, fetch_source=source)
            self.assertEqual(strict_pages.call_count, 1)
            shadow = discover_index_shadow(
                index, expected_notice_actor=ACTOR,
                expected_source_actor=ACTOR, fetch_source=source)
            self.assertEqual(strict_pages.call_count, 2)
        self.assertEqual(first["hints"], shadow["hints"])
        self.assertFalse(shadow["truncated"])

    def test_shadow_cross_batch_replay_and_explicit_limit_are_not_new_work(self):
        root, hint, _ = fixtures()
        index = pages([
            comment(1000 + n, hint) if n in (0, 35)
            else {"id": 1000 + n, "body": "operator note",
                  "user": actor_user()}
            for n in range(42)
        ])
        read = lambda repo, issue: pages([comment(77, root)])
        with patch("tools.kaep_discovery_reader._mailbox",
                   wraps=_mailbox) as strict_read:
            out = discover_index_shadow(
                index, expected_notice_actor=ACTOR,
                expected_source_actor=ACTOR, fetch_source=read)
        # Both pointers refer to the same verified Issue across three
        # batches. The source is decoded once, never re-decoded per pointer.
        self.assertEqual(strict_read.call_count, 1)
        self.assertEqual(len(out["hints"]), 1)
        self.assertEqual(out["duplicate_verified_pointers"], 1)
        self.assertEqual(out["distinct_source_issue_count"], 1)
        self.assertEqual(out["scanned_batches"], 3)
        cut = discover_index_shadow(
            index, expected_notice_actor=ACTOR,
            expected_source_actor=ACTOR, fetch_source=read, max_batches=1)
        self.assertEqual(cut["status"], "BOUNDED_TRUNCATED")
        self.assertTrue(cut["truncated"])
        self.assertEqual(cut["next_after_id"], 1019)
        with self.assertRaisesRegex(InvalidMessage, "INVALID_SHADOW_LIMIT"):
            discover_index_shadow(
                index, expected_notice_actor=ACTOR,
                expected_source_actor=ACTOR, fetch_source=read,
                max_batches=MAX_SHADOW_BATCHES + 1)

    def test_shadow_rejects_conflicting_index_identity_across_batches(self):
        root, hint, pointer = fixtures()
        for identity_field in ("message_id", "idempotency_key"):
            with self.subTest(identity_field=identity_field):
                altered = other_notice(
                    json.dumps(pointer), "kaep.shadow.othernotice0002",
                )
                altered[identity_field] = hint[identity_field]
                index = pages([
                    comment(1000 + n, hint if n == 0 else altered)
                    if n in (0, 35) else {
                        "id": 1000 + n, "body": "operator note",
                        "user": actor_user(),
                    }
                    for n in range(42)
                ])
                out = discover_index_shadow(
                    index, expected_notice_actor=ACTOR,
                    expected_source_actor=ACTOR,
                    fetch_source=lambda _r, _i: pages([comment(77, root)]),
                )
                self.assertEqual(out["status"], "INDEX_EXHAUSTED_WITH_REJECTIONS")
                self.assertEqual(len(out["hints"]), 1)
                self.assertEqual(len(out["rejected"]), 1)
                self.assertEqual(out["rejected"][0]["index_comment_id"], 1035)
                self.assertEqual(
                    out["rejected"][0]["reason_code"], "CONFLICTING_INDEX_REPLAY"
                )
                self.assertEqual(out["distinct_source_issue_count"], 1)
                self.assertEqual(out["scanned_batches"], 3)
                self.assertFalse(out["complete_work_inventory"])

    def test_shadow_blocked_original_pins_safe_cursor_not_full_index(self):
        root, hint, _ = fixtures()
        index = pages([
            comment(1021, hint) if n == 21
            else {"id": 1000 + n, "body": "operator note",
                  "user": actor_user()}
            for n in range(42)
        ])
        bad_source = pages([
            {"id": 76, "body": "<!-- kaep:message:v0.2 -->bad",
             "user": actor_user()},
            comment(77, root)
        ])
        out = discover_index_shadow(
            index, expected_notice_actor=ACTOR,
            expected_source_actor=ACTOR,
            fetch_source=lambda r, i: bad_source)
        self.assertEqual(out["status"], "PARTIAL_BLOCKED")
        self.assertEqual(out["scanned_batches"], 2)
        self.assertEqual(out["next_after_id"], 1020)
        self.assertTrue(out["truncated"])
        self.assertEqual(out["blocked"][0]["index_comment_id"], 1021)
        self.assertEqual(out["hints"], [])
        self.assertFalse(out["fallback_retirement_authorized"])

    def test_shadow_rejects_untrusted_actor_without_clean_status(self):
        root, hint, _ = fixtures()
        out = discover_index_shadow(
            pages([comment(88, hint, actor="intruder")]),
            expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
            fetch_source=lambda r, i: pages([comment(77, root)]))
        self.assertEqual(out["status"], "INDEX_EXHAUSTED_WITH_REJECTIONS")
        self.assertEqual(out["rejected"][0]["reason_code"],
                         "UNTRUSTED_DISCOVERY_ACTOR")
        self.assertFalse(out["complete_work_inventory"])
    def test_cursor_skips_old_hints(self):
        root, hint, _ = fixtures()
        x = read(pages([comment(88, hint)]), pages([comment(77, root)]), after_id=88)
        self.assertEqual(x, [])

    def test_unverified_notice_actor_is_quarantined_not_a_global_abort(self):
        root, hint, _ = fixtures()
        index = pages([comment(87, hint, actor="attacker"), comment(88, hint)])
        result = discover_batch(index, expected_notice_actor=ACTOR,
                                expected_source_actor=ACTOR,
                                fetch_source=lambda r, i: pages([comment(77, root)]))
        self.assertEqual([x["index_comment_id"] for x in result["hints"]], [88])
        self.assertEqual(result["rejected"], [
            {"index_comment_id": 87, "reason_code": "UNTRUSTED_DISCOVERY_ACTOR"}])
        self.assertEqual(result["next_after_id"], 88)

    def test_source_mismatch_is_quarantined(self):
        root, hint, _ = fixtures()
        result = discover_batch(pages([comment(88, hint)]),
                                expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                                fetch_source=lambda r, i: pages([]))
        self.assertEqual(result["hints"], [])
        self.assertEqual(result["rejected"][0]["reason_code"], "SOURCE_MESSAGE_NOT_UNIQUE")

    def test_fake_source_comment_id_rejected(self):
        root, hint, pointer = fixtures()
        new_pointer = dict(pointer, comment_id=999)
        tampered = dict(hint)
        tampered["payload"] = {"text": json.dumps(new_pointer)}
        result = discover_batch(pages([comment(88, tampered)]),
                                expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                                fetch_source=lambda r, i: pages([comment(77, root)]))
        self.assertEqual(result["hints"], [])
        self.assertEqual(result["rejected"][0]["reason_code"], "DISCOVERY_SOURCE_MISMATCH")

    def test_non_pointer_report_is_ignored(self):
        root, hint, _ = fixtures()
        other = dict(hint)
        other["payload"] = {"text": "ordinary status report"}
        x = read(pages([comment(88, other)]), pages([comment(77, root)]))
        self.assertEqual(x, [])

    def test_pointer_duplicate_json_key_rejected(self):
        with self.assertRaisesRegex(InvalidMessage, "DUPLICATE_JSON_KEY"):
            parse_pointer('{"type":"'+POINTER_VERSION+'","type":"'+POINTER_VERSION+'"}')

    def test_invalid_pointer_fields_and_unsafe_urls(self):
        _, _, pointer = fixtures()
        for bad in [
            dict(pointer, owning_issue="https://evil.invalid/x"),
            dict(pointer, comment_id=True),
            dict(pointer, message_id="bad"),
            dict(pointer, extra="unapproved"),
            dict(pointer, owning_issue=f"https://github.com/{DISCOVERY_REPOSITORY}/issues/{DISCOVERY_ISSUE}"),
        ]:
            with self.subTest(bad=bad):
                with self.assertRaises(InvalidMessage):
                    parse_pointer(json.dumps(bad))

    def test_malformed_marker_cannot_hide_later_valid_pointer(self):
        root, hint, _ = fixtures()
        malformed = {"id": 86, "body": "<!-- kaep:message:v0.2 -->malformed",
                     "user": actor_user()}
        result = discover_batch(pages([malformed, comment(88, hint)]),
                                expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                                fetch_source=lambda r, i: pages([comment(77, root)]))
        self.assertEqual(result["hints"][0]["index_comment_id"], 88)
        self.assertEqual(result["rejected"], [
            {"index_comment_id": 86, "reason_code": "INVALID_WRAPPER"}])

    def test_benign_report_mentions_pointer_version(self):
        root, hint, _ = fixtures()
        prose = other_notice("Please explain kaep.discovery-pointer.v1 in prose",
                             "kaep.discovery.prose0001")
        result = discover_batch(pages([comment(87, prose), comment(88, hint)]),
                                expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                                fetch_source=lambda r, i: pages([comment(77, root)]))
        self.assertEqual(len(result["hints"]), 1)
        self.assertEqual(result["rejected"], [])
        self.assertEqual(result["hints"][0]["index_comment_id"], 88)

    def test_bounded_scan_has_explicit_cursor_and_continuation(self):
        root, hint, _ = fixtures()
        boring = [{"id": i, "body": "ordinary update", "user": actor_user()}
                  for i in range(100, 100 + MAX_INDEX_BATCH)]
        index = pages(boring + [comment(100 + MAX_INDEX_BATCH, hint)])
        fetch = lambda r, i: pages([comment(77, root)])
        first = discover_batch(index, expected_notice_actor=ACTOR,
                               expected_source_actor=ACTOR, fetch_source=fetch)
        self.assertEqual(first["hints"], [])
        self.assertTrue(first["truncated"])
        self.assertEqual(first["next_after_id"], 99 + MAX_INDEX_BATCH)
        later = discover_batch(index, expected_notice_actor=ACTOR,
                               expected_source_actor=ACTOR, fetch_source=fetch,
                               after_id=first["next_after_id"])
        self.assertEqual(later["hints"][0]["index_comment_id"], 100 + MAX_INDEX_BATCH)
        self.assertFalse(later["truncated"])
        self.assertEqual(later["next_after_id"], 100 + MAX_INDEX_BATCH)

    def test_source_expected_head_and_replies_are_observations_not_identity(self):
        root, hint, _ = fixtures()
        answer = dict(root)
        answer.update({
            "message_id": "msg_peer_answer_001",
            "in_reply_to": root["message_id"],
            "recipient": "chatgpt",
            "kind": "ANSWER",
            "idempotency_key": "kaep.peer.answer.001",
            "payload": {"text": "technical analysis only"},
        })
        out = discover_batch(pages([comment(88, hint)]),
                             expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                             fetch_source=lambda r, i: pages([comment(77, root), comment(80, answer)]))
        self.assertEqual(out["hints"][0]["expected_head"], "a" * 40)
        self.assertEqual(out["hints"][0]["observed_reply_kinds"], ["ANSWER"])
        self.assertFalse(out["peer_identity_verified"])
        self.assertEqual(out["hints"][0]["status"], "POINTER_SOURCE_VERIFIED_ONLY")

    def test_malformed_source_wrapper_blocks_safe_cursor_not_other_sources(self):
        root, hint, _ = fixtures()
        malformed = {"id": 76, "body": "<!-- kaep:message:v0.2 -->bad",
                     "user": actor_user()}
        corrupt_source = pages([malformed, comment(77, root)])
        index = pages([comment(88, hint)])
        out = discover_batch(index, expected_notice_actor=ACTOR,
                             expected_source_actor=ACTOR,
                             fetch_source=lambda r, i: corrupt_source)
        self.assertEqual(out["status"], "PARTIAL_BLOCKED")
        self.assertEqual(out["hints"], [])
        self.assertEqual(out["blocked"], [
            {"index_comment_id": 88, "reason_code": "INVALID_WRAPPER"}])
        self.assertEqual(out["next_after_id"], 0)
        self.assertEqual(out["next_scan_after_id"], 88)
        with self.assertRaisesRegex(InvalidMessage, "DISCOVERY_SOURCE_BLOCKED"):
            read(index, corrupt_source)

    def test_untrusted_source_actor_is_not_answer_evidence(self):
        root, hint, _ = fixtures()
        reply = dict(root)
        reply.update({"message_id": "msg_reply_other_user_01",
                      "in_reply_to": root["message_id"], "recipient": "chatgpt",
                      "kind": "ANSWER", "idempotency_key": "kaep.answer.alien001"})
        out = discover_batch(pages([comment(88, hint)]),
                             expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                             fetch_source=lambda r, i: pages([
                                 comment(77, root), comment(80, reply, actor="unauthorized")]))
        self.assertEqual(out["hints"][0]["observed_reply_kinds"], [])

    def test_malformed_typed_pointer_is_rejected_but_prose_is_skipped(self):
        root, hint, _ = fixtures()
        self.assertIsNone(parse_pointer("Ordinary mention of kaep.discovery-pointer.v1"))
        with self.assertRaisesRegex(InvalidMessage, "INVALID_DISCOVERY_POINTER"):
            parse_pointer('{"type":"kaep.discovery-pointer.v1",')
        invalid = other_notice('{"type":"kaep.discovery-pointer.v1",',
                               "kaep.discovery.invalid0001")
        out = discover_batch(pages([comment(87, invalid), comment(88, hint)]),
                             expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                             fetch_source=lambda r, i: pages([comment(77, root)]))
        self.assertEqual(out["rejected"][0]["reason_code"], "INVALID_DISCOVERY_POINTER")
        self.assertEqual(len(out["hints"]), 1)

    def test_conflicting_index_replay_is_isolated(self):
        root, hint, _ = fixtures()
        altered = dict(hint)
        altered["payload"] = {"text": '{"type":"kaep.discovery-pointer.v1","comment_id":99}'}
        out = discover_batch(pages([
            comment(87, hint), comment(88, altered), comment(89, hint)]),
            expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
            fetch_source=lambda r, i: pages([comment(77, root)]))
        self.assertEqual([x["index_comment_id"] for x in out["hints"]], [87])
        self.assertEqual(out["rejected"][0]["reason_code"], "CONFLICTING_INDEX_REPLAY")

    def test_identical_index_replay_returns_single_actionable_hint(self):
        root, hint, _ = fixtures()
        index = pages([comment(88, hint), comment(89, hint)])
        out = discover_batch(index, expected_notice_actor=ACTOR,
                             expected_source_actor=ACTOR,
                             fetch_source=lambda r, i: pages([comment(77, root)]))
        self.assertEqual([x["index_comment_id"] for x in out["hints"]], [88])
        self.assertEqual(out["blocked"], [])
        self.assertEqual(out["rejected"], [])
        self.assertEqual(out["next_after_id"], 89)

    def test_corrupt_source_pins_commit_cursor_but_allows_later_valid_pointer(self):
        root, hint, _ = fixtures()
        other_root, _ = make_request(
            pages([]), repository=SOURCE_REPO, issue=337,
            recipient="claude-code", intent="ANALYZE",
            expected_head="b" * 40,
            request_key="kaep.discovery.other.source0001",
            request_text="second independent source", expect_existing_actor=ACTOR)
        other_ptr = {
            "type": POINTER_VERSION,
            "owning_issue": f"https://github.com/{SOURCE_REPO}/issues/337",
            "message_id": other_root["message_id"],
            "comment_id": 78,
        }
        second = other_notice(json.dumps(other_ptr), "kaep.discovery.secondindex0001")
        malformed = {"id": 76, "body": "<!-- kaep:message:v0.2 -->bad",
                     "user": actor_user()}
        index = pages([
            {"id": 85, "body": "ordinary", "user": actor_user()},
            comment(88, hint), comment(89, second),
        ])
        def fetch(repo, issue):
            if issue == SOURCE_ISSUE:
                return pages([malformed, comment(77, root)])
            self.assertEqual(issue, 337)
            return pages([comment(78, other_root)])
        out = discover_batch(index, expected_notice_actor=ACTOR,
                             expected_source_actor=ACTOR, fetch_source=fetch)
        self.assertEqual(out["status"], "PARTIAL_BLOCKED")
        self.assertEqual(out["blocked"], [
            {"index_comment_id": 88, "reason_code": "INVALID_WRAPPER"}])
        self.assertEqual([x["index_comment_id"] for x in out["hints"]], [89])
        self.assertEqual(out["next_after_id"], 85)  # cannot commit over poison
        self.assertEqual(out["next_scan_after_id"], 89)  # can scan beyond poison
        self.assertFalse(out["truncated"])

    def test_bad_index_pagination_still_fatal_and_no_cursor_returned(self):
        bad = json.dumps([[{"id": 2, "body": "ordinary",
                            "user": actor_user()},
                           {"id": 1, "body": "ordinary",
                            "user": actor_user()} ]])
        with self.assertRaisesRegex(InvalidMessage, "INVALID_COMMENT_SEQUENCE"):
            discover_batch(bad, expected_notice_actor=ACTOR,
                           expected_source_actor=ACTOR,
                           fetch_source=lambda r, i: pages([]))

    def test_invalid_cursor(self):
        with self.assertRaisesRegex(InvalidMessage, "INVALID_CURSOR"):
            discover(pages([]), expected_notice_actor=ACTOR,
                     expected_source_actor=ACTOR, fetch_source=lambda r, i: pages([]),
                     after_id=-1)

    def test_source_fetch_failure_blocks_all_results(self):
        root, hint, _ = fixtures()
        def unavailable(repo, issue):
            raise InvalidMessage("GITHUB_READ_UNAVAILABLE")
        index = pages([comment(88, hint)])
        batch = discover_batch(index, expected_notice_actor=ACTOR,
                               expected_source_actor=ACTOR, fetch_source=unavailable)
        self.assertEqual(batch["blocked"][0]["reason_code"], "GITHUB_READ_UNAVAILABLE")
        self.assertEqual(batch["next_after_id"], 0)
        with self.assertRaisesRegex(InvalidMessage, "DISCOVERY_SOURCE_BLOCKED"):
            discover(index, expected_notice_actor=ACTOR,
                     expected_source_actor=ACTOR, fetch_source=unavailable)


class NumericOwnerTrustRegression(unittest.TestCase):
    def test_index_owner_id_rejected_when_missing_malformed_or_mismatched(self):
        _, hint, _ = fixtures()
        for identity in ({}, {"id": True}, {"id": 999999999}, {"id": "79015263"}, {"id": 79015263, "login": "spoof"}):
            with self.subTest(identity=identity):
                original = comment(88, hint)
                original["user"] = {"login": ACTOR, **identity}
                result = discover_batch(
                    pages([original]), expected_notice_actor=ACTOR,
                    expected_source_actor=ACTOR,
                    fetch_source=lambda _r, _i: pages([]))
                self.assertEqual(result["rejected"][0]["reason_code"], "UNTRUSTED_DISCOVERY_ACTOR")


if __name__ == "__main__":
    unittest.main()
