"""Strict KAEP discovery reader tests, all in memory and read-only."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tools.kaep_mailbox_codec import encode_comment, InvalidMessage
from tools.kaep_request_sender import make_request
from tools.kaep_discovery_reader import (
    discover, discover_batch, parse_pointer, POINTER_VERSION, MAX_INDEX_BATCH,
)
from tools.kaep_route_notice import DISCOVERY_REPOSITORY, DISCOVERY_ISSUE

SOURCE_REPO = "kinoko34077/UniverseGenome"
SOURCE_ISSUE = 336
ACTOR = "kinoko34077"


def pages(*groups):
    return json.dumps(list(groups))


def comment(cid, msg, actor=ACTOR):
    return {"id": cid, "body": encode_comment(msg), "user": {"login": actor}}


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


def read(index, source, *, after_id=0, notice_actor=ACTOR, source_actor=ACTOR):
    return discover(index, expected_notice_actor=notice_actor,
                    expected_source_actor=source_actor,
                    after_id=after_id, fetch_source=lambda r, i: source)


class DiscoveryReaderTests(unittest.TestCase):
    def test_valid_pointer_has_actual_root_and_no_payload(self):
        root, hint, pointer = fixtures()
        x = read(pages([comment(88, hint)]), pages([comment(77, root)]))
        self.assertEqual(len(x), 1)
        self.assertEqual(x[0]["index_comment_id"], 88)
        self.assertEqual(x[0]["source_message_id"], pointer["message_id"])
        self.assertEqual(x[0]["status"], "POINTER_SOURCE_VERIFIED_ONLY")
        self.assertNotIn("source payload private", json.dumps(x))

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
                     "user": {"login": ACTOR}}
        result = discover_batch(pages([malformed, comment(88, hint)]),
                                expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                                fetch_source=lambda r, i: pages([comment(77, root)]))
        self.assertEqual(result["hints"][0]["index_comment_id"], 88)
        self.assertEqual(result["rejected"], [
            {"index_comment_id": 86, "reason_code": "INVALID_WRAPPER"}])

    def test_benign_report_mentions_pointer_version(self):
        root, hint, _ = fixtures()
        prose = dict(hint)
        prose["payload"] = {"text": "Please explain kaep.discovery-pointer.v1 in prose"}
        result = discover_batch(pages([comment(87, prose), comment(88, hint)]),
                                expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                                fetch_source=lambda r, i: pages([comment(77, root)]))
        self.assertEqual(len(result["hints"]), 1)
        self.assertEqual(result["rejected"], [])
        self.assertEqual(result["hints"][0]["index_comment_id"], 88)

    def test_bounded_scan_has_explicit_cursor_and_continuation(self):
        root, hint, _ = fixtures()
        boring = [{"id": i, "body": "ordinary update", "user": {"login": ACTOR}}
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

    def test_malformed_source_wrapper_still_blocks_cursor_advance(self):
        root, hint, _ = fixtures()
        malformed = {"id": 76, "body": "<!-- kaep:message:v0.2 -->bad",
                     "user": {"login": ACTOR}}
        with self.assertRaisesRegex(InvalidMessage, "INVALID_WRAPPER"):
            discover_batch(pages([comment(88, hint)]),
                           expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                           fetch_source=lambda r, i: pages([malformed, comment(77, root)]))

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
        invalid = dict(hint)
        invalid["payload"] = {"text": '{"type":"kaep.discovery-pointer.v1",'}
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
        self.assertEqual([x["index_comment_id"] for x in out["hints"]], [87, 89])
        self.assertEqual(out["rejected"][0]["reason_code"], "CONFLICTING_INDEX_REPLAY")

    def test_invalid_cursor(self):
        with self.assertRaisesRegex(InvalidMessage, "INVALID_CURSOR"):
            discover(pages([]), expected_notice_actor=ACTOR,
                     expected_source_actor=ACTOR, fetch_source=lambda r, i: pages([]),
                     after_id=-1)

    def test_source_fetch_failure_blocks_all_results(self):
        root, hint, _ = fixtures()
        def unavailable(repo, issue):
            raise InvalidMessage("GITHUB_READ_UNAVAILABLE")
        with self.assertRaisesRegex(InvalidMessage, "GITHUB_READ_UNAVAILABLE"):
            discover(pages([comment(88, hint)]),
                     expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                     fetch_source=unavailable)


if __name__ == "__main__":
    unittest.main()
