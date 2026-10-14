"""Strict KAEP discovery reader tests, all in memory and read-only."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tools.kaep_mailbox_codec import encode_comment, InvalidMessage
from tools.kaep_request_sender import make_request
from tools.kaep_discovery_reader import discover, parse_pointer, POINTER_VERSION
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

    def test_unverified_notice_actor_rejected(self):
        root, hint, _ = fixtures()
        with self.assertRaisesRegex(InvalidMessage, "UNTRUSTED_DISCOVERY_ACTOR"):
            read(pages([comment(88, hint, actor="attacker")]),
                 pages([comment(77, root)]))

    def test_source_mismatch_fail_closed(self):
        root, hint, _ = fixtures()
        with self.assertRaisesRegex(InvalidMessage, "SOURCE_MESSAGE_NOT_UNIQUE"):
            read(pages([comment(88, hint)]), pages([]))

    def test_fake_source_comment_id_rejected(self):
        root, hint, pointer = fixtures()
        new_pointer = dict(pointer, comment_id=999)
        tampered = dict(hint)
        tampered["payload"] = {"text": json.dumps(new_pointer)}
        with self.assertRaisesRegex(InvalidMessage, "DISCOVERY_SOURCE_MISMATCH"):
            read(pages([comment(88, tampered)]), pages([comment(77, root)]))

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

    def test_invalid_cursor(self):
        with self.assertRaisesRegex(InvalidMessage, "INVALID_CURSOR"):
            discover(pages([]), expected_notice_actor=ACTOR,
                     expected_source_actor=ACTOR, fetch_source=lambda r, i: pages([]),
                     after_id=-1)

    def test_source_fetch_failure_blocks_all_results(self):
        root, hint, _ = fixtures()
        def unavailable(repo, issue):
            raise InvalidMessage("SOURCE_UNAVAILABLE")
        with self.assertRaisesRegex(InvalidMessage, "SOURCE_UNAVAILABLE"):
            discover(pages([comment(88, hint)]),
                     expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                     fetch_source=unavailable)


if __name__ == "__main__":
    unittest.main()
