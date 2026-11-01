"""Two-phase send option validation remains strict and side-effect free."""
from __future__ import annotations

import unittest
from unittest.mock import patch
from tools import kaep_send_with_discovery as sender
from tools.kaep_inbox_reader import InvalidMessage
from tools.kaep_route_notice import DISCOVERY_REPOSITORY, DISCOVERY_ISSUE


class SendOptionsOwnershipTests(unittest.TestCase):
    def _base(self):
        return dict(
            repository="kinoko34077/devflow", issue=847, intent="ANALYZE",
            request_key="no.post.option.validation.001",
            request_text="read-only fixture",
            expected_source_actor="kinoko34077",
            expected_notice_actor="kinoko34077",
            do_send=False,
        )

    def test_invalid_options_stop_all_read_and_post_paths(self):
        options = self._base()
        bad = (
            ({"do_send": 1}, "INVALID_SEND_MODE"),
            ({"discovery_issue": 847}, "DISCOVERY_INDEX_NOT_APPROVED"),
            ({"repository": DISCOVERY_REPOSITORY, "issue": DISCOVERY_ISSUE}, "DISCOVERY_LOOP"),
            ({"expected_notice_actor": "bad actor"}, "INVALID_ACTOR"),
            ({"intent": "EXECUTE"}, "ROUTE_UNSUPPORTED_INTENT"),
            ({"offline_source_pages": "[]"}, "INCOMPLETE_OFFLINE_FIXTURE"),
            ({"do_send": True, "offline_source_pages": "[]",
              "offline_discovery_pages": "[]"}, "OFFLINE_POST_FORBIDDEN"),
        )
        with (patch.object(sender, "verify_public_source",
                           side_effect=AssertionError("unexpected visibility")),
              patch.object(sender, "_discovery_read_preflight",
                           side_effect=AssertionError("unexpected preflight")),
              patch.object(sender, "send_request",
                           side_effect=AssertionError("unexpected source post"))):
            for changed, reason in bad:
                with self.subTest(changed=changed), self.assertRaisesRegex(
                    InvalidMessage, reason
                ):
                    sender.publish_source_and_route(**(options | changed))

    def test_valid_option_check_does_not_attempt_transport(self):
        options = self._base()
        sender._validate_two_phase_options(
            repository=options["repository"], issue=options["issue"],
            intent=options["intent"], discovery_issue=DISCOVERY_ISSUE,
            expected_notice_actor=options["expected_notice_actor"],
            do_send=False, offline_source_pages=None,
            offline_discovery_pages=None,
        )


if __name__ == "__main__":
    unittest.main()
