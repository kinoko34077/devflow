"""B5 producer-source route audit: source identity, pointer and unknown states."""
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from tools.kaep_mailbox_codec import encode_comment, InvalidMessage
from tools.kaep_request_sender import make_request
from tools.kaep_route_notice import (
    DISCOVERY_ISSUE, DISCOVERY_REPOSITORY,
    verify_source_request,
)
from tools.kaep_source_route_audit import audit_route, main

REPO = "kinoko34077/devflow"
ISSUE = 726
ACTOR = "kinoko34077"


def pages(*groups):
    return json.dumps(list(groups), ensure_ascii=False)


def comment(cid, msg, actor=ACTOR):
    return {"id": cid, "body": encode_comment(msg), "user": {"login": actor}}


def source():
    request, old = make_request(
        pages([]), repository=REPO, issue=ISSUE,
        recipient="claude-code", intent="ANALYZE",
        request_key="kaep.source.route.audit.726.fixture",
        request_text="Confidential original text must stay in source Issue",
        expect_existing_actor=ACTOR, expected_head="a" * 40,
    )
    assert old is None
    return request


def route_comment(root, *, source_comment_id=101, index_comment_id=301,
                  actor=ACTOR):
    pointer = verify_source_request(
        pages([comment(source_comment_id, root)]),
        repository=REPO, issue=ISSUE, message_id=root["message_id"],
        expected_actor=ACTOR,
    )
    request, old = make_request(
        pages([]), repository=DISCOVERY_REPOSITORY, issue=DISCOVERY_ISSUE,
        recipient="claude-code", intent="REPORT",
        request_key="kaep.discovery." + root["message_id"],
        request_text=json.dumps(pointer, sort_keys=True, separators=(",", ":")),
        expect_existing_actor=ACTOR,
    )
    assert old is None
    return comment(index_comment_id, request, actor=actor)


def audited(root, *index, source_actor=ACTOR):
    # The canonical provider adapter admits up to 100 comments per page.
    batches = [list(index)[i:i + 100] for i in range(0, len(index), 100)] or [[]]
    return audit_route(
        pages([comment(101, root, actor=source_actor)]),
        pages(*batches),
        repository=REPO, issue=ISSUE,
        message_id=root["message_id"],
        expected_source_actor=ACTOR, expected_notice_actor=ACTOR,
    )


class RouteAuditTests(unittest.TestCase):
    def test_exact_pointer_match_is_bounded_observation_not_delivery(self):
        root = source()
        out = audited(root, route_comment(root))
        self.assertEqual(out["status"], "EXACT_POINTER_OBSERVED")
        self.assertEqual(out["pointer_comment_ids"], [301])
        self.assertTrue(out["exact_pointer_observed"])
        self.assertTrue(out["has_unknown_work"])
        self.assertFalse(out["complete_source_universe"])
        self.assertFalse(out["recipient_pickup_proven"])
        self.assertFalse(out["current_head_verified"])
        self.assertFalse(out["can_authorize_execution"])
        self.assertFalse(out["fallback_retirement_authorized"])
        self.assertNotIn("Confidential original text", json.dumps(out))

    def test_true_726_style_unindexed_root_is_not_called_no_work(self):
        root = source()
        out = audited(root)
        self.assertEqual(out["status"], "EXACT_POINTER_NOT_OBSERVED")
        self.assertEqual(out["pointer_comment_ids"], [])
        self.assertTrue(out["has_unknown_work"])
        self.assertFalse(out["can_authorize_execution"])

    def test_malformed_or_wrong_actor_index_prevents_clear_negative(self):
        root = source()
        malformed = {"id": 301, "body": "<!-- kaep:message:v0.2 -->BAD",
                     "user": {"login": ACTOR}}
        blocked = audited(root, malformed)
        self.assertEqual(blocked["status"], "PARTIAL_UNKNOWN")
        self.assertFalse(blocked["exact_pointer_observed"])
        self.assertEqual(blocked["index_warnings"][0]["reason_code"],
                         "INVALID_WRAPPER")
        untrusted = audited(root, route_comment(root, actor="outsider"))
        self.assertEqual(untrusted["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(untrusted["pointer_comment_ids"], [])
        self.assertEqual(untrusted["index_warnings"][0]["reason_code"],
                         "UNTRUSTED_DISCOVERY_ACTOR")

    def test_wrong_pointer_origin_fails_closed_without_misrouting(self):
        root = source()
        bad = route_comment(root, source_comment_id=101)
        data = json.loads(bad["body"].split("```json\n", 1)[1].split("\n```", 1)[0])
        pointer = json.loads(data["payload"]["text"])
        pointer["comment_id"] = 102
        data["payload"]["text"] = json.dumps(pointer)
        bad["body"] = encode_comment(data)
        out = audited(root, bad)
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertFalse(out["exact_pointer_observed"])
        self.assertEqual(out["index_warnings"][0]["reason_code"],
                         "DISCOVERY_SOURCE_MISMATCH")

    def test_source_actor_and_source_mailbox_remain_canonical(self):
        root = source()
        with self.assertRaisesRegex(InvalidMessage, "SOURCE_ACTOR_MISMATCH"):
            audited(root, route_comment(root), source_actor="outsider")
        with self.assertRaisesRegex(InvalidMessage, "SOURCE_MESSAGE_NOT_UNIQUE"):
            audit_route(pages([]), pages([]), repository=REPO, issue=ISSUE,
                        message_id=root["message_id"],
                        expected_source_actor=ACTOR, expected_notice_actor=ACTOR)

    def test_hard_index_comment_cap(self):
        root = source()
        rows = [{"id": i, "body": "non-marker text", "user": {"login": ACTOR}}
                for i in range(1, 502)]
        with self.assertRaisesRegex(InvalidMessage, "DISCOVERY_INDEX_TOO_LARGE"):
            audited(root, *rows)

    def test_cli_get_only_normal_success_and_missing(self):
        root = source()
        with patch("tools.kaep_source_route_audit.fetch_gh_pages",
                   side_effect=[pages([comment(101, root)]),
                                pages([route_comment(root)])]) as get, redirect_stdout(io.StringIO()) as stdout:
            rc = main(["--repository", REPO, "--issue", str(ISSUE),
                       "--message-id", root["message_id"],
                       "--expect-source-actor", ACTOR,
                       "--expect-notice-actor", ACTOR])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"],
                         "EXACT_POINTER_OBSERVED")
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[1].args,
                         (DISCOVERY_REPOSITORY, DISCOVERY_ISSUE))


if __name__ == "__main__":
    unittest.main()
