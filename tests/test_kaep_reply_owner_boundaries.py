"""KAEP reply authoring: parent eligibility and ID reservations are distinct."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from tools import kaep_reply_sender as sender
from tools.kaep_inbox_reader import InvalidMessage
from tests.test_kaep_reply_sender import (
    REPO, PARENT, FIXED_ACK, comment, pages, parent,
)


class ReplyOwnerBoundaryTests(unittest.TestCase):
    def _compose(self, src):
        return sender.make_reply(
            src, repository=REPO, issue=503, parent_message_id=PARENT,
            kind="ACK", response_text=FIXED_ACK, expect_actor="kinoko34077",
        )

    def test_untrusted_parent_rejected_before_reserved_reply_search(self):
        src = pages([comment(11, parent(), actor="untrusted")])
        with patch.object(
            sender, "_reserved_reply_comment",
            side_effect=AssertionError("reservation before parent verification")
        ) as reserved:
            with self.assertRaisesRegex(InvalidMessage, "PARENT_ACTOR_MISMATCH"):
                self._compose(src)
        reserved.assert_not_called()

    def test_existing_reply_requires_matching_actor_and_exact_fingerprint(self):
        src = pages([comment(11, parent())])
        first, existing = self._compose(src)
        self.assertIsNone(existing)
        durable = pages([comment(11, parent()), comment(12, first)])
        again, previous = self._compose(durable)
        self.assertEqual(again, first)
        self.assertEqual(previous, 12)
        other_actor = pages([comment(11, parent()), comment(12, first, actor="untrusted")])
        with self.assertRaisesRegex(InvalidMessage, "EXISTING_REPLY_ACTOR_MISMATCH"):
            self._compose(other_actor)
        with self.assertRaisesRegex(InvalidMessage, "REPLY_COLLISION"):
            sender.make_reply(
                durable, repository=REPO, issue=503,
                parent_message_id=PARENT, kind="ACK",
                response_text="changed content", expect_actor="kinoko34077",
            )

    def test_reply_reservation_never_promotes_quarantined_collision(self):
        first, _ = self._compose(pages([comment(11, parent())]))
        quarantined = dict(first)
        quarantined["exchange_id"] = "ex_different_777"
        source = pages([comment(11, parent()), comment(12, quarantined)])
        with self.assertRaisesRegex(InvalidMessage, "REPLY_COLLISION"):
            self._compose(source)


if __name__ == "__main__":
    unittest.main()
