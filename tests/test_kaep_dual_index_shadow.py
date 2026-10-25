"""Offline A/B discovery-index proof with the canonical strict A3 reader.

The successor Issue number is synthetic. No GitHub Issue/comment is created,
and neither recipient processing nor full source coverage is proven.
"""
import json
import unittest

from tools.kaep_discovery_reader import discover_batch, discover_dual_index_shadow
from tools.kaep_inbox_reader import InvalidMessage
from tools.kaep_mailbox_codec import encode_comment
from tools.kaep_request_sender import make_request
from tools.kaep_route_notice import DISCOVERY_ISSUE, DISCOVERY_REPOSITORY

ACTOR = "kinoko34077"
ACTOR_ID = 79015263
SOURCE_REPO = "kinoko34077/UniverseGenome"
SOURCE_ISSUE = 336
SUCCESSOR_ISSUE = 9001  # synthetic fixture ID, never publish
SOURCE_CID = 77


def pages(*groups):
    return json.dumps(list(groups))


def actor_user(actor=ACTOR):
    return {"login": actor, "id": ACTOR_ID if actor == ACTOR else 999999999}


def comment(cid, payload, actor=ACTOR):
    body = encode_comment(payload) if isinstance(payload, dict) else payload
    return {"id": cid, "body": body, "user": actor_user(actor)}


def source_and_pointer(index_issue):
    root, old = make_request(
        pages([]), repository=SOURCE_REPO, issue=SOURCE_ISSUE,
        recipient="claude-code", intent="ANALYZE",
        request_key="kaep.dual.index.root001",
        request_text="source payload (must stay in original Issue)",
        expect_existing_actor=ACTOR, expected_head="a" * 40,
    )
    assert old is None
    pointer = {
        "type": "kaep.discovery-pointer.v1",
        "owning_issue": f"https://github.com/{SOURCE_REPO}/issues/{SOURCE_ISSUE}",
        "message_id": root["message_id"],
        "comment_id": SOURCE_CID,
    }
    notice, prior = make_request(
        pages([]), repository=DISCOVERY_REPOSITORY, issue=index_issue,
        recipient="claude-code", intent="REPORT",
        request_key=f"kaep.dual.index.{index_issue}.pointer001",
        request_text=json.dumps(pointer, sort_keys=True, separators=(",", ":")),
        expect_existing_actor=ACTOR,
    )
    assert prior is None
    return root, notice


def dual(old_comments, new_comments, root, **kwargs):
    fetched = []

    def read_source(repo, issue):
        fetched.append((repo, issue))
        return pages([comment(SOURCE_CID, root)])

    result = discover_dual_index_shadow(
        pages(old_comments), pages(new_comments),
        successor_issue=SUCCESSOR_ISSUE,
        expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
        fetch_source=read_source, **kwargs,
    )
    return result, fetched


class DualIndexShadowTests(unittest.TestCase):
    def test_strictly_verified_cross_index_replay_dedup(self):
        root, old = source_and_pointer(DISCOVERY_ISSUE)
        _, new = source_and_pointer(SUCCESSOR_ISSUE)
        out, fetched = dual([comment(91, old)], [comment(301, new)], root)
        self.assertEqual(out["status"], "BOUNDED_DUAL_INDEX_READ")
        self.assertEqual(out["cross_index_duplicate_count"], 1)
        self.assertEqual(out["cross_index_identity_conflicts"], 0)
        self.assertEqual(fetched, [(SOURCE_REPO, SOURCE_ISSUE)])
        self.assertEqual(len(out["source_verified_roots"]), 1)
        matched = out["source_verified_roots"][0]
        self.assertEqual(matched["index_origins"], ["legacy", "successor"])
        self.assertEqual(matched["index_comment_ids"], {"legacy": 91, "successor": 301})
        self.assertEqual(matched["source_comment_id"], SOURCE_CID)
        self.assertNotIn("source payload", json.dumps(out))
        for denied in ("complete_source_universe", "complete_work_inventory",
                       "recipient_pickup_proven", "current_head_verified",
                       "can_authorize_execution", "fallback_retirement_authorized",
                       "index_migration_approved"):
            self.assertFalse(out[denied])
        self.assertTrue(out["has_unknown_work"])

    def test_malformed_legacy_index_does_not_hide_new_verified_original(self):
        root, old = source_and_pointer(DISCOVERY_ISSUE)
        _, new = source_and_pointer(SUCCESSOR_ISSUE)
        malformed = encode_comment(old) + "\n"
        out, _ = dual([comment(90, malformed), comment(91, old)],
                      [comment(301, new)], root)
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["index_status"]["legacy"], "INDEX_EXHAUSTED_WITH_REJECTIONS")
        self.assertEqual(out["index_diagnostics"]["legacy"]["rejected"], [
            {"index_comment_id": 90, "reason_code": "INVALID_WRAPPER"},
        ])
        self.assertEqual(len(out["source_verified_roots"]), 1)
        self.assertEqual(out["source_verified_roots"][0]["index_origins"],
                         ["legacy", "successor"])
        self.assertFalse(out["complete_source_universe"])

    def test_untrusted_successor_actor_is_not_admitted(self):
        root, _ = source_and_pointer(DISCOVERY_ISSUE)
        _, new = source_and_pointer(SUCCESSOR_ISSUE)
        out, fetched = dual([], [comment(301, new, actor="untrusted")], root)
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["source_verified_roots"], [])
        self.assertEqual(fetched, [])
        self.assertEqual(
            out["index_diagnostics"]["successor"]["rejected"][0]["reason_code"],
            "UNTRUSTED_DISCOVERY_ACTOR")

    def test_successor_index_cannot_be_an_original_source(self):
        root, _ = source_and_pointer(DISCOVERY_ISSUE)
        pointer = {
            "type": "kaep.discovery-pointer.v1",
            "owning_issue": f"https://github.com/{DISCOVERY_REPOSITORY}/issues/{SUCCESSOR_ISSUE}",
            "message_id": root["message_id"], "comment_id": SOURCE_CID,
        }
        forged, _ = make_request(
            pages([]), repository=DISCOVERY_REPOSITORY,
            issue=SUCCESSOR_ISSUE, recipient="claude-code", intent="REPORT",
            request_key="kaep.dual.index.invalid.loop001",
            request_text=json.dumps(pointer), expect_existing_actor=ACTOR,
        )
        out, fetched = dual([], [comment(301, forged)], root)
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["source_verified_roots"], [])
        self.assertEqual(fetched, [])
        self.assertEqual(
            out["index_diagnostics"]["successor"]["rejected"][0]["reason_code"],
            "DISCOVERY_LOOP")

    def test_legacy_index_cannot_point_at_known_successor_issue(self):
        root, _ = source_and_pointer(DISCOVERY_ISSUE)
        pointer = {
            "type": "kaep.discovery-pointer.v1",
            "owning_issue": f"https://github.com/{DISCOVERY_REPOSITORY}/issues/{SUCCESSOR_ISSUE}",
            "message_id": root["message_id"], "comment_id": SOURCE_CID,
        }
        forged, _ = make_request(
            pages([]), repository=DISCOVERY_REPOSITORY, issue=DISCOVERY_ISSUE,
            recipient="claude-code", intent="REPORT",
            request_key="kaep.dual.index.invalid.legacyloop001",
            request_text=json.dumps(pointer), expect_existing_actor=ACTOR,
        )
        out, fetched = dual([comment(91, forged)], [], root)
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["source_verified_roots"], [])
        self.assertEqual(fetched, [])
        self.assertEqual(
            out["index_diagnostics"]["legacy"]["rejected"][0]["reason_code"],
            "DISCOVERY_LOOP")

    def test_source_mailbox_corruption_stays_partial_blocked(self):
        root, _ = source_and_pointer(DISCOVERY_ISSUE)
        _, new = source_and_pointer(SUCCESSOR_ISSUE)
        corrupt_source = pages([comment(76, "<!-- kaep:message:v0.2 -->BAD"),
                                comment(SOURCE_CID, root)])
        out = discover_dual_index_shadow(
            pages([]), pages([comment(301, new)]),
            successor_issue=SUCCESSOR_ISSUE,
            expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
            fetch_source=lambda _r, _i: corrupt_source,
        )
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["source_verified_roots"], [])
        self.assertEqual(out["index_diagnostics"]["successor"]["blocked"][0]["reason_code"],
                         "INVALID_WRAPPER")
        self.assertFalse(out["can_authorize_execution"])

    def test_truncated_index_does_not_claim_complete(self):
        root, old = source_and_pointer(DISCOVERY_ISSUE)
        filler = [comment(i, "ordinary notice") for i in range(10, 30)]
        out, _ = dual(filler + [comment(30, old)], [], root, max_batches=1)
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertTrue(out["index_diagnostics"]["legacy"]["truncated"])
        self.assertEqual(out["source_verified_roots"], [])

    def test_transport_or_pagination_error_never_yields_success(self):
        root, old = source_and_pointer(DISCOVERY_ISSUE)
        with self.assertRaises(InvalidMessage):
            discover_dual_index_shadow(
                '{"invalid":"pagination"}', pages([]),
                successor_issue=SUCCESSOR_ISSUE,
                expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                fetch_source=lambda _r, _i: pages([comment(SOURCE_CID, root)]),
            )
        with self.assertRaises(OSError):
            discover_dual_index_shadow(
                pages([comment(91, old)]), pages([]),
                successor_issue=SUCCESSOR_ISSUE,
                expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                fetch_source=lambda _r, _i: (_ for _ in ()).throw(OSError("network failure")),
            )

    def test_invalid_successor_issue_is_rejected_without_source_lookup(self):
        for bad in (DISCOVERY_ISSUE, True, -1, 0, "9001"):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(InvalidMessage, "INVALID_SUCCESSOR_INDEX"):
                    discover_dual_index_shadow(
                        pages([]), pages([]), successor_issue=bad,
                        expected_notice_actor=ACTOR, expected_source_actor=ACTOR,
                        fetch_source=lambda _r, _i: self.fail("no fetch"),
                    )
        with self.assertRaisesRegex(InvalidMessage, "INVALID_DISCOVERY_INDEX"):
            discover_batch(
                pages([]), index_issue=True, expected_notice_actor=ACTOR,
                expected_source_actor=ACTOR,
                fetch_source=lambda _r, _i: self.fail("no fetch"),
            )


if __name__ == "__main__":
    unittest.main()
