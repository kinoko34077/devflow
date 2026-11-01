"""Source-proof ownership and same-scan cache invariants for KAEP Discovery."""
from __future__ import annotations
import unittest
from unittest.mock import patch

from tools import kaep_discovery_reader as reader
from tools.kaep_inbox_reader import InvalidMessage
from tests.test_kaep_discovery_reader import (
    ACTOR, SOURCE_REPO, SOURCE_ISSUE, comment, fixtures, pages,
)


class DiscoveryProofResponsibilityTests(unittest.TestCase):
    def test_forged_pointer_never_caches_proof_even_if_original_mailbox_cached(self):
        root, _notice, valid = fixtures()
        forged = dict(valid)
        forged["comment_id"] = valid["comment_id"] + 1
        source = pages([comment(77, root)])
        seen = []
        def fetch(repo, number):
            seen.append((repo, number))
            return source
        mailboxes, proofs = {}, {}
        with patch.object(reader, "_source_context", wraps=reader._source_context) as ctx:
            with self.assertRaisesRegex(InvalidMessage, "DISCOVERY_SOURCE_MISMATCH"):
                reader._verify_pointer_source(
                    forged, repository=SOURCE_REPO, issue=SOURCE_ISSUE,
                    fetch_source=fetch, expected_actor=ACTOR,
                    source_mailboxes=mailboxes, source_proofs=proofs,
                )
            self.assertEqual(proofs, {})
            self.assertEqual(ctx.call_count, 0)
            verified, context = reader._verify_pointer_source(
                valid, repository=SOURCE_REPO, issue=SOURCE_ISSUE,
                fetch_source=fetch, expected_actor=ACTOR,
                source_mailboxes=mailboxes, source_proofs=proofs,
            )
            self.assertEqual(verified, valid)
            self.assertEqual(context["expected_head"], "a" * 40)
            self.assertEqual(ctx.call_count, 1)
            self.assertEqual(seen, [(SOURCE_REPO, SOURCE_ISSUE)])
            with self.assertRaisesRegex(InvalidMessage, "DISCOVERY_SOURCE_MISMATCH"):
                reader._verify_pointer_source(
                    forged, repository=SOURCE_REPO, issue=SOURCE_ISSUE,
                    fetch_source=fetch, expected_actor=ACTOR,
                    source_mailboxes=mailboxes, source_proofs=proofs,
                )
            self.assertEqual(ctx.call_count, 1)
            self.assertEqual(len(proofs), 1)

    def test_invalid_original_cannot_poison_source_or_proof_cache(self):
        _root, _notice, pointer = fixtures()
        malformed = pages([{
            "id": 77, "body": "<!-- kaep:message:v0.2 -->bad",
            "user": {"id": 79015263, "login": ACTOR},
        }])
        sources, proofs = {}, {}
        with self.assertRaises(InvalidMessage):
            reader._verify_pointer_source(
                pointer, repository=SOURCE_REPO, issue=SOURCE_ISSUE,
                fetch_source=lambda _r, _n: malformed, expected_actor=ACTOR,
                source_mailboxes=sources, source_proofs=proofs,
            )
        self.assertEqual(sources, {})
        self.assertEqual(proofs, {})

    def test_unavailable_source_does_not_enter_cache(self):
        _root, _notice, pointer = fixtures()
        def offline(_repo, _n):
            raise InvalidMessage("GITHUB_READ_UNAVAILABLE")
        sources, proofs = {}, {}
        with self.assertRaisesRegex(InvalidMessage, "GITHUB_READ_UNAVAILABLE"):
            reader._verify_pointer_source(
                pointer, repository=SOURCE_REPO, issue=SOURCE_ISSUE,
                fetch_source=offline, expected_actor=ACTOR,
                source_mailboxes=sources, source_proofs=proofs,
            )
        self.assertEqual(sources, {})
        self.assertEqual(proofs, {})


if __name__ == "__main__":
    unittest.main()
