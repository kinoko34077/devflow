"""Non-effectful regression cases for Private billing-block planning (#752)."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from tools.private_ci_billing_block import (
    JobLaunchReceipt, MonthlyBillingBlock,
    classify_job_launch, plan_monthly_billing_block,
)

NOW = datetime(2026, 10, 20, 5, 18, tzinfo=timezone.utc)
ACCOUNT = "kinoko34077"
BLOCK = (
    "The job was not started because recent account payments have failed "
    "or your spending limit needs to be increased. Please check the "
    "'Billing & plans' section in your settings"
)


def receipt(**overrides):
    sample = JobLaunchReceipt(
        account=ACCOUNT, repository=ACCOUNT + "/kinotch-default-canary",
        visibility="private", run_id=39373919107, job_id=118467669219,
        head_sha="0d72fceacb4cd458564c3269c46d47886e2127a5",
        completed_at_utc=NOW-timedelta(minutes=3), conclusion="failure",
        runner_name="", steps_count=0, annotation=BLOCK,
        authenticated_github_read=True,
    )
    return replace(sample, **overrides)


def flag(**overrides):
    sample = MonthlyBillingBlock(
        account=ACCOUNT, billing_month="2026-10", reason="BILLING_BLOCKED",
        check_run_id=118467669219, source_verified=True,
    )
    return replace(sample, **overrides)


class BillingBlockEvidenceTests(unittest.TestCase):
    def test_observed_exact_private_launch_block_not_quota(self):
        r = classify_job_launch(receipt(), NOW, ACCOUNT)
        self.assertEqual((r.status, r.action), ("PLAN_ONLY", "RECORD_BILLING_BLOCK"))
        self.assertEqual(r.reason, "PRIVATE_HOSTED_BILLING_BLOCKED_NOT_QUOTA_PROOF")

    def test_no_forged_unverified_source(self):
        self.assertEqual(
            classify_job_launch(receipt(authenticated_github_read=False), NOW, ACCOUNT).action,
            "HOLD",
        )

    def test_wrong_account_and_public_rejected(self):
        for override in (
            {"account": "other"}, {"repository": "other/repo"},
            {"visibility": "public"}, {"visibility": "unknown"},
        ):
            with self.subTest(override=override):
                self.assertEqual(
                    classify_job_launch(receipt(**override), NOW, ACCOUNT).action, "HOLD"
                )

    def test_missing_identity_rejected(self):
        for override in (
            {"run_id": 0}, {"job_id": 0}, {"job_id": True},
            {"head_sha": "unverified"}, {"head_sha": "A"*40},
        ):
            with self.subTest(override=override):
                self.assertEqual(
                    classify_job_launch(receipt(**override), NOW, ACCOUNT).action, "HOLD"
                )

    def test_running_test_failure_never_becomes_block_flag(self):
        for override in (
            {"steps_count": 1},
            {"runner_name": "GitHub Actions 1"},
            {"conclusion": "success"},
            {"annotation": "Tests failed"},
            {"annotation": "Actions quota has expired"},
        ):
            with self.subTest(override=override):
                self.assertEqual(
                    classify_job_launch(receipt(**override), NOW, ACCOUNT).action, "HOLD"
                )

    def test_old_historical_block_requires_new_diagnostic(self):
        past = NOW-timedelta(days=11)
        p = classify_job_launch(receipt(completed_at_utc=past), NOW, ACCOUNT)
        self.assertEqual(p.reason, "HISTORICAL_RECEIPT_RECHECK_REQUIRED")

    def test_reject_future_receipt_and_invalid_clock(self):
        self.assertEqual(
            classify_job_launch(receipt(completed_at_utc=NOW+timedelta(minutes=1)), NOW, ACCOUNT).action,
            "HOLD")
        self.assertEqual(
            classify_job_launch(receipt(), NOW.replace(tzinfo=None), ACCOUNT).action,
            "HOLD")

    def test_malformed_job_metadata_is_not_actionable(self):
        for override in (
            {"steps_count": -1}, {"steps_count": False},
            {"runner_name": None}, {"annotation": None},
            {"completed_at_utc": NOW.replace(tzinfo=None)},
        ):
            with self.subTest(override=override):
                self.assertEqual(
                    classify_job_launch(receipt(**override), NOW, ACCOUNT).action,
                    "HOLD",
                )


class BillingMonthFlagTests(unittest.TestCase):
    def test_current_month_verified_flag_skips_billing(self):
        plan = plan_monthly_billing_block(ACCOUNT, NOW, flag=flag())
        self.assertEqual(plan.action, "FALLBACK_CANDIDATE")
        self.assertEqual(plan.reason, "CURRENT_MONTH_BILLING_BLOCK_NOT_QUOTA")

    def test_current_flag_prioritized_even_with_other_receipt(self):
        plan = plan_monthly_billing_block(
            ACCOUNT, NOW, flag=flag(), receipt=receipt(annotation="test failure")
        )
        self.assertEqual(plan.action, "FALLBACK_CANDIDATE")

    def test_next_month_resets_without_scheduler(self):
        nov = datetime(2026, 11, 1, tzinfo=timezone.utc)
        plan = plan_monthly_billing_block(ACCOUNT, nov, flag=flag())
        self.assertEqual(plan.action, "QUERY_BILLING")

    def test_year_boundary(self):
        dec = flag(billing_month="2026-12")
        jan = datetime(2027, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(
            plan_monthly_billing_block(ACCOUNT, jan, flag=dec).action, "QUERY_BILLING"
        )

    def test_untrusted_flag_fails_closed(self):
        for overrides in (
            {"account": "other"}, {"source_verified": False},
            {"reason": "QUOTA_EXHAUSTED"}, {"billing_month": "2026-13"},
            {"check_run_id": 0}, {"billing_month": "bad"},
        ):
            with self.subTest(overrides=overrides):
                self.assertEqual(
                    plan_monthly_billing_block(ACCOUNT, NOW, flag=flag(**overrides)).action,
                    "HOLD",
                )

    def test_future_month_flag_holds(self):
        self.assertEqual(
            plan_monthly_billing_block(
                ACCOUNT, NOW, flag=flag(billing_month="2026-11")
            ).reason,
            "FUTURE_BILLING_BLOCK_FLAG",
        )

    def test_recent_receipt_proposes_flag_not_execution(self):
        plan = plan_monthly_billing_block(ACCOUNT, NOW, receipt=receipt())
        self.assertEqual(plan.action, "RECORD_BILLING_BLOCK")
        self.assertEqual(plan.status, "PLAN_ONLY")

    def test_no_evidence_requests_billing_without_dispatch(self):
        plan = plan_monthly_billing_block(ACCOUNT, NOW)
        self.assertEqual(plan.action, "QUERY_BILLING")
        self.assertEqual(plan.status, "PLAN_ONLY")

    def test_never_authorizes_actual_worker(self):
        decisions = (
            plan_monthly_billing_block(ACCOUNT, NOW),
            plan_monthly_billing_block(ACCOUNT, NOW, flag=flag()),
            plan_monthly_billing_block(ACCOUNT, NOW, receipt=receipt()),
        )
        for result in decisions:
            self.assertIn(result.status, {"HOLD", "PLAN_ONLY"})
            self.assertNotEqual(result.action, "EXECUTE")


if __name__ == "__main__":
    unittest.main()
