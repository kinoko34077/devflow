import unittest

from tools import maintenance_ledger as ml


REPO = "kinoko34077/example"


def ledger_body(status="AUDITED", block=""):
    return (
        "# Maintenance Audit Ledger\n\n"
        "## Repository\n\n"
        f"`{REPO}`\n\n"
        "## Work Status\n\n"
        f"`{status}`\n"
        + ("\n" + block if block else "")
    )


def active(**overrides):
    value = ml.ActiveRun(
        repository=REPO,
        run_id=f"audit:{REPO}:common.correctness:1",
        slot_id="common.correctness",
        generation=1,
        catalog_digest="sha256:" + "a" * 64,
        fingerprint="sha256:" + "b" * 64,
        depth="STANDARD",
        coverage_key="common.correctness",
        selected_at="2026-10-07T00:00:00Z",
        publisher_attempt_id="attempt-a",
        score_breakdown=(("never_run", 40), ("unexecuted_lens", 15)),
    )
    return ml.replace_active(value, **overrides)


def record(**overrides):
    value = ml.RunRecord(
        repository=REPO,
        run_id=f"audit:{REPO}:common.correctness:1",
        slot_id="common.correctness",
        generation=1,
        lens="correctness",
        depth="STANDARD",
        fingerprint="sha256:" + "b" * 64,
        result="CLEAN",
        findings_summary="none",
        completed_at="2026-10-07T00:30:00Z",
        next_eligibility_reason=None,
        evidence_refs=("https://github.com/kinoko34077/example/issues/1",),
    )
    return ml.replace_record(value, **overrides)


class ActiveRunTests(unittest.TestCase):
    def test_zero_active_run_is_valid_when_ledger_is_not_runnable(self):
        self.assertIsNone(ml.extract_active_run(ledger_body(), REPO))
        self.assertEqual("AUDITED", ml.ledger_work_status(ledger_body()))

    def test_replace_active_run_sets_ready_status_and_round_trips(self):
        body, changed = ml.replace_active_run(ledger_body(), active())
        self.assertTrue(changed)
        self.assertEqual("READY_FOR_IMPLEMENTATION", ml.ledger_work_status(body))
        self.assertEqual(active(), ml.extract_active_run(body, REPO))

    def test_rendering_identical_active_run_is_noop(self):
        body, _ = ml.replace_active_run(ledger_body(), active())
        same, changed = ml.replace_active_run(body, active())
        self.assertFalse(changed)
        self.assertEqual(body, same)

    def test_clearing_active_run_is_deterministic_and_sets_audited(self):
        body, _ = ml.replace_active_run(ledger_body(), active())
        cleared, changed = ml.replace_active_run(body, None)
        self.assertTrue(changed)
        self.assertIsNone(ml.extract_active_run(cleared, REPO))
        self.assertEqual("AUDITED", ml.ledger_work_status(cleared))
        same, changed = ml.replace_active_run(cleared, None)
        self.assertFalse(changed)
        self.assertEqual(cleared, same)

    def test_duplicate_reversed_and_malformed_markers_fail_closed(self):
        payload = ml.render_active_run(active())
        duplicate = ledger_body("READY_FOR_IMPLEMENTATION", payload + "\n" + payload)
        with self.assertRaisesRegex(ml.MaintenanceLedgerError, "ambiguous"):
            ml.extract_active_run(duplicate, REPO)

        reversed_block = (
            ml.ACTIVE_RUN_END + "\n{}\n" + ml.ACTIVE_RUN_BEGIN
        )
        with self.assertRaisesRegex(ml.MaintenanceLedgerError, "order"):
            ml.extract_active_run(
                ledger_body("READY_FOR_IMPLEMENTATION", reversed_block),
                REPO,
            )

        malformed = ml.ACTIVE_RUN_BEGIN + "\nnot-json\n" + ml.ACTIVE_RUN_END
        with self.assertRaises(ml.MaintenanceLedgerError):
            ml.extract_active_run(
                ledger_body("READY_FOR_IMPLEMENTATION", malformed),
                REPO,
            )

    def test_repository_mismatch_fails_closed(self):
        body, _ = ml.replace_active_run(ledger_body(), active())
        with self.assertRaisesRegex(ml.MaintenanceLedgerError, "repository"):
            ml.extract_active_run(body, "kinoko34077/other")

    def test_unknown_active_field_fails_closed(self):
        rendered = ml.render_active_run(active())
        rendered = rendered.replace(
            '"coverage_key":"common.correctness"',
            '"coverage_key":"common.correctness","surprise":true',
        )
        with self.assertRaisesRegex(ml.MaintenanceLedgerError, "unknown"):
            ml.extract_active_run(
                ledger_body("READY_FOR_IMPLEMENTATION", rendered),
                REPO,
            )

    def test_active_run_requires_ready_for_implementation(self):
        rendered = ml.render_active_run(active())
        with self.assertRaisesRegex(ml.MaintenanceLedgerError, "Work Status"):
            ml.extract_active_run(ledger_body("AUDITED", rendered), REPO)

    def test_ready_status_without_active_run_is_invalid(self):
        with self.assertRaisesRegex(ml.MaintenanceLedgerError, "active run"):
            ml.extract_active_run(ledger_body("READY_FOR_IMPLEMENTATION"), REPO)


class RunCommentTests(unittest.TestCase):
    def test_run_comment_round_trips(self):
        comment = ml.render_run_comment(record())
        self.assertEqual(record(), ml.parse_run_comment(comment))

    def test_unrecognized_comment_returns_none(self):
        self.assertIsNone(ml.parse_run_comment("ordinary discussion"))

    def test_duplicate_sentinel_and_unknown_field_fail_closed(self):
        comment = ml.render_run_comment(record())
        with self.assertRaisesRegex(ml.MaintenanceLedgerError, "ambiguous"):
            ml.parse_run_comment(comment + "\n" + comment)

        tampered = comment.replace(
            '"result":"CLEAN"',
            '"result":"CLEAN","surprise":1',
        )
        with self.assertRaisesRegex(ml.MaintenanceLedgerError, "unknown"):
            ml.parse_run_comment(tampered)

    def test_generation_increments_only_for_same_repository_and_slot(self):
        history = (
            record(generation=1),
            record(generation=3, run_id=f"audit:{REPO}:common.correctness:3"),
            record(
                repository="kinoko34077/other",
                run_id="audit:kinoko34077/other:common.correctness:8",
                generation=8,
            ),
            record(
                slot_id="common.security",
                run_id=f"audit:{REPO}:common.security:9",
                generation=9,
            ),
        )
        self.assertEqual(
            4,
            ml.next_generation(history, REPO, "common.correctness"),
        )
        self.assertEqual(1, ml.next_generation((), REPO, "common.correctness"))


if __name__ == "__main__":
    unittest.main()
