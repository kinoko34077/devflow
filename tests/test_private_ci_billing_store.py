"""SQLite journal regressions for devflow #752, all using temporary files."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from tools.private_ci_billing_block import JobLaunchReceipt
from tools.private_ci_billing_store import LocalBillingObservationStore

ACCOUNT = "kinoko34077"
NOW = datetime(2026, 10, 20, 5, 18, tzinfo=timezone.utc)
ANNOTATION = (
    "The job was not started because recent account payments have failed "
    "or your spending limit needs to be increased. Please check the "
    "'Billing & plans' section in your settings"
)


def receipt(**changes):
    sample = JobLaunchReceipt(
        account=ACCOUNT, repository=ACCOUNT + "/kinotch-default-canary",
        visibility="private", run_id=39373919107, job_id=118467669219,
        head_sha="0d72fceacb4cd458564c3269c46d47886e2127a5",
        completed_at_utc=NOW - timedelta(minutes=3),
        conclusion="failure", runner_name="", steps_count=0,
        annotation=ANNOTATION, authenticated_github_read=True,
    )
    return replace(sample, **changes)


class ObservationJournalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "quota-journal.sqlite3"
        self.store = LocalBillingObservationStore(self.path)

    def test_daily_store_survives_reopen(self):
        first = self.store.record_daily(ACCOUNT, NOW, "REPORT_RECEIVED_INCONCLUSIVE")
        other = LocalBillingObservationStore(self.path)
        self.assertEqual(other.read_daily(ACCOUNT, NOW), first)
        self.assertEqual(first.observation, "REPORT_RECEIVED_INCONCLUSIVE")

    def test_daily_second_call_idempotent(self):
        first = self.store.record_daily(ACCOUNT, NOW, "REPORT_RECEIVED_INCONCLUSIVE")
        second = self.store.record_daily(
            ACCOUNT, NOW + timedelta(seconds=30), "REPORT_RECEIVED_INCONCLUSIVE"
        )
        self.assertEqual(first, second)

    def test_conflicting_observation_holds_and_preserves_original(self):
        initial = self.store.record_daily(ACCOUNT, NOW, "REPORT_RECEIVED_INCONCLUSIVE")
        with self.assertRaisesRegex(ValueError, "CONFLICTING_DAILY_OBSERVATION"):
            self.store.record_daily(ACCOUNT, NOW, "BILLING_API_UNAVAILABLE")
        self.assertEqual(self.store.read_daily(ACCOUNT, NOW), initial)

    def test_next_jst_date_has_no_cached_observation(self):
        self.store.record_daily(ACCOUNT, NOW, "REPORT_RECEIVED_INCONCLUSIVE")
        next_day = NOW + timedelta(days=1)
        self.assertIsNone(self.store.read_daily(ACCOUNT, next_day))

    def test_utc_month_flip_within_same_jst_day_rechecks(self):
        before = datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc)
        after = before + timedelta(hours=1)
        a = self.store.record_daily(ACCOUNT, before, "REPORT_RECEIVED_INCONCLUSIVE")
        self.assertIsNone(self.store.read_daily(ACCOUNT, after))
        b = self.store.record_daily(ACCOUNT, after, "REPORT_RECEIVED_INCONCLUSIVE")
        self.assertEqual(a.date_jst, b.date_jst)
        self.assertNotEqual(a.billing_month, b.billing_month)

    def test_other_account_cannot_read_current_daily(self):
        self.store.record_daily(ACCOUNT, NOW, "REPORT_RECEIVED_INCONCLUSIVE")
        self.assertIsNone(self.store.read_daily("another", NOW))

    def test_invalid_input_wont_be_stored(self):
        for account, stamp, event in (
            ("x/y", NOW, "REPORT_RECEIVED_INCONCLUSIVE"),
            (ACCOUNT, NOW, "HOSTED_ELIGIBLE"),
            (ACCOUNT, NOW.replace(tzinfo=None), "BILLING_API_UNAVAILABLE"),
        ):
            with self.subTest(account=account, event=event):
                with self.assertRaises(ValueError):
                    self.store.record_daily(account, stamp, event)

    def test_billing_job_block_is_journaled_not_authorized(self):
        stored = self.store.record_launch_block(receipt(), NOW)
        self.assertEqual(stored.check_run_id, 118467669219)
        self.assertFalse(stored.verified_for_dispatch)
        self.assertEqual(self.store.read_monthly_block(ACCOUNT, NOW), stored)

    def test_wrong_unverified_source_does_not_make_month_flag(self):
        with self.assertRaises(ValueError):
            self.store.record_launch_block(
                receipt(authenticated_github_read=False), NOW
            )
        self.assertIsNone(self.store.read_monthly_block(ACCOUNT, NOW))

    def test_fake_billing_block_from_test_failure_not_recorded(self):
        with self.assertRaises(ValueError):
            self.store.record_launch_block(
                receipt(steps_count=2, runner_name="ubuntu-runner"), NOW
            )
        self.assertIsNone(self.store.read_monthly_block(ACCOUNT, NOW))

    def test_monthly_marker_expires_at_utc_month_boundary(self):
        self.store.record_launch_block(receipt(), NOW)
        nov = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.assertIsNone(self.store.read_monthly_block(ACCOUNT, nov))

    def test_replay_same_job_is_idempotent(self):
        initial = self.store.record_launch_block(receipt(), NOW)
        later = self.store.record_launch_block(receipt(), NOW + timedelta(minutes=1))
        self.assertEqual(initial, later)

    def test_conflicting_job_for_month_never_overwrites(self):
        initial = self.store.record_launch_block(receipt(), NOW)
        with self.assertRaisesRegex(ValueError, "CONFLICTING_MONTHLY_EVIDENCE"):
            self.store.record_launch_block(receipt(job_id=118467669220), NOW)
        self.assertEqual(self.store.read_monthly_block(ACCOUNT, NOW), initial)

    def test_other_accounts_cannot_inherit_block(self):
        self.store.record_launch_block(receipt(), NOW)
        self.assertIsNone(self.store.read_monthly_block("another", NOW))

    def test_database_contains_no_annotation_or_token(self):
        self.store.record_launch_block(receipt(), NOW)
        self.store.record_daily(ACCOUNT, NOW, "REPORT_RECEIVED_INCONCLUSIVE")
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            self.assertEqual(
                set(name for (name,) in rows),
                {"daily_observations", "monthly_billing_blocks"},
            )
        raw = self.path.read_bytes()
        self.assertNotIn(ANNOTATION.encode(), raw)
        self.assertNotIn(b"Bearer ", raw)
        self.assertNotIn(b"github_pat_", raw)

    def test_corrupted_stored_month_record_fails_closed(self):
        self.store.record_launch_block(receipt(), NOW)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "UPDATE monthly_billing_blocks SET check_run_id = 0 WHERE account = ?",
                (ACCOUNT,),
            )
        with self.assertRaisesRegex(ValueError, "INVALID_STORED_MONTHLY_EVIDENCE"):
            self.store.read_monthly_block(ACCOUNT, NOW)

    def test_parallel_daily_writers_do_not_duplicate_rows(self):
        errors = []
        def run_one():
            try:
                self.store.record_daily(ACCOUNT, NOW, "REPORT_RECEIVED_INCONCLUSIVE")
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=run_one) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM daily_observations").fetchone()[0],
                1,
            )


if __name__ == "__main__":
    unittest.main()
