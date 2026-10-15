"""A5 offline contract: read/plan/freshness/no-op/reconcile for Issue metadata."""
import dataclasses
import unittest

from tools.operation_issue_metadata_preflight import (
    MetadataPreflightRejected, plan_section_transition, postwrite_verdict,
    prewrite_verdict, snapshot_issue,
)

REPO = "kinoko34077/devflow"
BEGIN = "### P1 — Shared operation safety #487 — A3 COMPLETE"
END = "### P1 — Separate gateway #541"
ORIGINAL = (
    "## Repository\n\nkinoko34077/devflow\n\n"
    + BEGIN + "\n- A3 accepted; A4 pending\n\n"
    + END + "\n- Gateway separately owned\n\n"
    "### Other section\n- do not change\n"
)
REPLACEMENT = (
    "### P1 — Shared operation safety #487 — A4 ACCEPTED\n"
    "- A3 and A4 accepted, read-first metadata proof\n"
    "- No new writer authority or atomic GitHub Issue CAS\n\n"
)


def raw(body=ORIGINAL, updated="2026-10-15T10:00:00Z", **overrides):
    return {
        "repository": REPO, "number": 16, "state": "open",
        "updated_at": updated, "body": body, **overrides,
    }


def observed(**overrides):
    return snapshot_issue(raw(**overrides), repository=REPO, number=16)


def plan(snapshot=None, replacement=REPLACEMENT, start=BEGIN, end=END):
    return plan_section_transition(
        snapshot or observed(), start_anchor=start, end_anchor=end,
        replacement_section=replacement,
    )


class IssueMetadataPreflightTests(unittest.TestCase):
    def test_exact_bounded_scope_and_no_permissions(self):
        p = plan()
        self.assertEqual(p.after_body, ORIGINAL.replace(
            BEGIN + "\n- A3 accepted; A4 pending\n\n", REPLACEMENT,
        ))
        self.assertEqual(p.before_body, ORIGINAL)
        self.assertEqual(len(p.observed_body_sha256), 64)
        self.assertEqual(len(p.after_body_sha256), 64)
        self.assertFalse(p.effect_authorized)
        self.assertFalse(p.atomic_compare_available)
        self.assertEqual(p.repository, REPO)
        self.assertEqual(p.number, 16)
        self.assertEqual(prewrite_verdict(p, observed()), "READY")
        self.assertIn(END, p.after_body)
        self.assertIn("### Other section\n- do not change", p.after_body)

    def test_realistic_noop_replay_and_postwrite_readback(self):
        p = plan()
        after = observed(body=p.after_body, updated="2026-10-15T10:01:00Z")
        self.assertEqual(prewrite_verdict(p, after), "NO_OP")
        self.assertEqual(postwrite_verdict(p, after), "POSTREAD_VERIFIED")
        self.assertEqual(postwrite_verdict(p, observed()), "NOT_APPLIED")

    def test_stale_time_and_same_timestamp_body_detected(self):
        p = plan()
        newer = observed(updated="2026-10-15T10:01:00Z")
        self.assertEqual(prewrite_verdict(p, newer), "STALE")
        changed = observed(body=ORIGINAL + "\ninterleaving actor")
        self.assertEqual(prewrite_verdict(p, changed), "STALE")
        self.assertEqual(postwrite_verdict(p, changed), "UNKNOWN_RECONCILE")
        self.assertEqual(postwrite_verdict(p, newer), "NOT_APPLIED")

    def test_target_mismatch_wrong_issue_or_repository_rejected(self):
        p = plan()
        altered = dataclasses.replace(observed(), number=17)
        self.assertEqual(prewrite_verdict(p, altered), "REJECTED")
        self.assertEqual(postwrite_verdict(p, altered), "REJECTED")
        other = dataclasses.replace(observed(), repository="kinoko34077/testapp")
        self.assertEqual(prewrite_verdict(p, other), "REJECTED")

    def test_snapshots_must_have_bounded_authenticated_caller_shape(self):
        bad = (
            {"number": 17}, {"number": True}, {"repository": "other/repo"},
            {"state": "closed"}, {"updated_at": "unknown"},
            {"body": "x" * 263000}, {"body": None},
        )
        for edits in bad:
            with self.subTest(edits=edits), self.assertRaises(MetadataPreflightRejected):
                snapshot_issue(raw(**edits), repository=REPO, number=16)
        with self.assertRaises(MetadataPreflightRejected):
            snapshot_issue(raw(), repository=REPO, number=True)
        with self.assertRaises(MetadataPreflightRejected):
            snapshot_issue(raw(), repository="other/repo", number=16)

    def test_missing_duplicate_reordered_anchor_fails_closed(self):
        variants = [
            ORIGINAL.replace(BEGIN, ""),
            ORIGINAL + BEGIN,
            ORIGINAL + END,
            ORIGINAL.replace(END, "temporary"),
            END + "\n" + ORIGINAL.replace(END, "temporary"),
        ]
        for body in variants:
            with self.subTest(body=body[:32]), self.assertRaises(MetadataPreflightRejected):
                plan(observed(body=body))
        with self.assertRaises(MetadataPreflightRejected):
            plan(start="short")
        with self.assertRaises(MetadataPreflightRejected):
            plan(end=BEGIN)

    def test_delta_size_restricted_even_if_same_length(self):
        with self.assertRaises(MetadataPreflightRejected):
            plan(replacement=REPLACEMENT + ("a" * 8300))
        with self.assertRaises(MetadataPreflightRejected):
            plan(replacement=REPLACEMENT + ("b" * 5000))
        with self.assertRaises(MetadataPreflightRejected):
            plan(replacement=REPLACEMENT.replace("\n\n", "\n"))
        with self.assertRaises(MetadataPreflightRejected):
            plan(replacement=REPLACEMENT + END + "\n\n")

    def test_reject_no_effect_or_noncanonical_replacement(self):
        before = BEGIN + "\n- A3 accepted; A4 pending\n\n"
        with self.assertRaises(MetadataPreflightRejected):
            plan(replacement=before)
        with self.assertRaises(MetadataPreflightRejected):
            plan(replacement="not-a-section\n\n")

    def test_ambiguity_does_not_imply_commit_or_retry(self):
        p = plan()
        unknown = observed(body=ORIGINAL.replace(
            "- Gateway separately owned", "- someone else changed gateway"
        ), updated="2026-10-15T10:01:01Z")
        self.assertEqual(postwrite_verdict(p, unknown), "UNKNOWN_RECONCILE")
        self.assertEqual(prewrite_verdict(p, unknown), "STALE")
        self.assertNotEqual(postwrite_verdict(p, unknown), "POSTREAD_VERIFIED")

    def test_no_network_or_mutation_api_exposed(self):
        import tools.operation_issue_metadata_preflight as module
        for forbidden in ("patch", "post", "request", "send", "commit"):
            self.assertFalse(hasattr(module, forbidden))
        p = plan()
        self.assertTrue(dataclasses.is_dataclass(p))
        self.assertTrue(p.__dataclass_params__.frozen)


if __name__ == "__main__":
    unittest.main()
