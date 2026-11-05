"""Boundary checks for KAEP discovery source proofs and read-only hint shape."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tools import kaep_discovery_reader as reader
from tools.kaep_inbox_reader import InvalidMessage
from tests.test_kaep_discovery_reader import (
    ACTOR, SOURCE_REPO, SOURCE_ISSUE, comment, fixtures, pages,
)


class DiscoveryResponsibilityTests(unittest.TestCase):
    def test_cached_proof_is_checked_per_pointer_without_refetch(self):
        root, _, pointer = fixtures()
        source_cache = {}
        proof_cache = {}
        fetched = []
        def source_fetch(repo, number):
            fetched.append((repo, number))
            return pages([comment(77, root)])

        def verify(p):
            return reader._verified_source_pointer(
                p, repo=SOURCE_REPO, issue=SOURCE_ISSUE,
                expected_source_actor=ACTOR, fetch_source=source_fetch,
                source_cache=source_cache, proof_cache=proof_cache,
            )

        with (patch.object(reader, "_verify_source_request_from_snapshot",
                           wraps=reader._verify_source_request_from_snapshot) as check,
              patch.object(reader, "_source_context",
                           wraps=reader._source_context) as context):
            verified, observed = verify(pointer)
            self.assertEqual(verified, pointer)
            self.assertEqual(observed["observed_reply_kinds"], [])
            self.assertEqual(verify(pointer), (verified, observed))
            self.assertEqual(check.call_count, 1)
            self.assertEqual(context.call_count, 1)

            forged = dict(pointer, comment_id=78)
            with self.assertRaisesRegex(InvalidMessage, "DISCOVERY_SOURCE_MISMATCH"):
                verify(forged)
            self.assertEqual(check.call_count, 1)
            self.assertEqual(context.call_count, 1)
        self.assertEqual(fetched, [(SOURCE_REPO, SOURCE_ISSUE)])
        self.assertEqual(len(source_cache), 1)
        self.assertEqual(len(proof_cache), 1)

    def test_mismatched_first_pointer_never_writes_source_proof(self):
        root, _, pointer = fixtures()
        source_cache = {}
        proof_cache = {}
        forged = dict(pointer, comment_id=78)
        with patch.object(reader, "_source_context",
                          wraps=reader._source_context) as context:
            with self.assertRaisesRegex(InvalidMessage, "DISCOVERY_SOURCE_MISMATCH"):
                reader._verified_source_pointer(
                    forged, repo=SOURCE_REPO, issue=SOURCE_ISSUE,
                    expected_source_actor=ACTOR,
                    fetch_source=lambda repo, n: pages([comment(77, root)]),
                    source_cache=source_cache, proof_cache=proof_cache,
                )
        self.assertEqual(context.call_count, 0)
        self.assertEqual(len(source_cache), 1)
        self.assertEqual(proof_cache, {})

    def test_hint_projection_does_not_expose_original_payload_or_authorize(self):
        root, _, pointer = fixtures()
        hint = reader._verified_pointer_hint(
            88, pointer, pointer,
            {"expected_head": root["scope"]["expected_head"],
             "observed_reply_kinds": ["ANSWER", "ACK"]},
        )
        self.assertEqual(hint, {
            "index_comment_id": 88,
            "owning_issue": pointer["owning_issue"],
            "source_comment_id": pointer["comment_id"],
            "source_message_id": pointer["message_id"],
            "expected_head": root["scope"]["expected_head"],
            "observed_reply_kinds": ["ANSWER", "ACK"],
            "status": "POINTER_SOURCE_VERIFIED_ONLY",
        })
        self.assertNotIn("source payload private", json.dumps(hint))
        self.assertNotIn("can_authorize_execution", hint)
        self.assertNotIn("peer_identity_verified", hint)


if __name__ == "__main__":
    unittest.main()
