"""Change-reason boundary: Discovery notice replay and conflict identity."""
from __future__ import annotations

import unittest

from tools import kaep_discovery_reader as reader
from tools.kaep_inbox_reader import InvalidMessage
from tests.test_kaep_discovery_reader import fixtures, other_notice


class DiscoveryNoticeIdentityTests(unittest.TestCase):
    def test_same_batch_identical_replay_is_ignored(self):
        _root, notice, _pointer = fixtures()
        seen_messages, seen_keys = {}, {}
        replay_history = ({}, {})
        def record(msg):
            return reader._record_index_notice_identity(
                msg, seen_messages=seen_messages, seen_keys=seen_keys,
                replay_history=replay_history,
            )
        self.assertTrue(record(notice))
        self.assertFalse(record(dict(notice)))
        self.assertEqual(len(seen_messages), 1)
        self.assertEqual(len(seen_keys), 1)
        self.assertEqual(len(replay_history[0]), 1)
        self.assertEqual(len(replay_history[1]), 1)

    def test_identical_cross_batch_notice_is_rechecked_not_suppressed(self):
        _root, notice, _pointer = fixtures()
        replay_history = ({}, {})
        def batch():
            return reader._record_index_notice_identity(
                notice, seen_messages={}, seen_keys={},
                replay_history=replay_history,
            )
        self.assertTrue(batch())
        self.assertTrue(batch())
        self.assertEqual(len(replay_history[0]), 1)
        self.assertEqual(len(replay_history[1]), 1)

    def test_cross_batch_message_or_idempotency_conflict_does_not_mutate_history(self):
        _root, notice, pointer = fixtures()
        replay_history = ({}, {})
        self.assertTrue(reader._record_index_notice_identity(
            notice, seen_messages={}, seen_keys={},
            replay_history=replay_history,
        ))
        baseline = (dict(replay_history[0]), dict(replay_history[1]))
        changed = other_notice('{"type":"not-a-pointer"}', "kaep.discovery.identity.other")
        for field in ("message_id", "idempotency_key"):
            with self.subTest(field=field):
                bad = dict(changed, **{field: notice[field]})
                with self.assertRaisesRegex(
                    InvalidMessage, "CONFLICTING_INDEX_REPLAY"
                ):
                    reader._record_index_notice_identity(
                        bad, seen_messages={}, seen_keys={},
                        replay_history=replay_history,
                    )
                self.assertEqual(replay_history, baseline)

    def test_same_batch_conflicting_identity_is_rejected_before_history_mutation(self):
        _root, notice, pointer = fixtures()
        seen_messages, seen_keys = {}, {}
        assert reader._record_index_notice_identity(
            notice, seen_messages=seen_messages, seen_keys=seen_keys,
            replay_history=None,
        )
        baseline = (dict(seen_messages), dict(seen_keys))
        bad = dict(other_notice("changed", "kaep.discovery.identity.other2"))
        bad["message_id"] = notice["message_id"]
        with self.assertRaisesRegex(InvalidMessage, "CONFLICTING_INDEX_REPLAY"):
            reader._record_index_notice_identity(
                bad, seen_messages=seen_messages, seen_keys=seen_keys,
                replay_history=None,
            )
        self.assertEqual((seen_messages, seen_keys), baseline)


if __name__ == "__main__":
    unittest.main()
