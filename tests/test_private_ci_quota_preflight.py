"""Offline-only regression tests for devflow #752 daily quota plan."""
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import unittest

from tools.private_ci_quota_preflight import (
    MonthFlag, UsageProof, plan_private_quota_preflight,
)

OWNER = "kinoko34077"
NOW = datetime(2026, 10, 20, 4, 0, tzinfo=timezone.utc)


def usage(**changes):
    return replace(UsageProof(
        account=OWNER, billing_month="2026-10",
        checked_on_jst="2026-10-20", equivalent_minutes=1200,
        included_minutes=2000, authenticated=True, metering_complete=True,
    ), **changes)


def decide(*, now=NOW, proof=None, flag=None, account=OWNER):
    return plan_private_quota_preflight(account, now, proof, flag)


class DailyQueryTests(unittest.TestCase):
    def test_new_day_requests_one_new_query(self):
        self.assertEqual(decide().action, "QUERY_BILLING")
        self.assertEqual(decide(proof=usage()).action, "HOSTED_CANDIDATE")
        next_day = NOW + timedelta(days=1)
        self.assertEqual(decide(now=next_day, proof=usage()).action,
                         "QUERY_BILLING")

    def test_jst_day_boundary_is_not_utc_day_boundary(self):
        just_before = datetime(2026, 10, 20, 14, 59, tzinfo=timezone.utc)
        just_after = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
        self.assertEqual(decide(now=just_before, proof=usage()).action,
                         "HOSTED_CANDIDATE")
        self.assertEqual(decide(now=just_after, proof=usage()).action,
                         "QUERY_BILLING")

    def test_at_quota_plan_write_once_flag(self):
        self.assertEqual(decide(proof=usage(equivalent_minutes=2000)).action,
                         "WRITE_FLAG")
        self.assertEqual(decide(proof=usage(equivalent_minutes=2001)).status,
                         "PLAN_ONLY")

    def test_unknown_metering_never_sets_exhaustion(self):
        self.assertEqual(decide(proof=usage(metering_complete=False)).action,
                         "HOLD")
        self.assertEqual(decide(proof=usage(equivalent_minutes=None)).action,
                         "HOLD")
        self.assertEqual(decide(proof=usage(equivalent_minutes=float("nan"))).action,
                         "HOLD")
        self.assertEqual(decide(proof=usage(included_minutes=0)).action,
                         "HOLD")

    def test_untrusted_and_wrong_account_reports_rejected(self):
        self.assertEqual(decide(proof=usage(authenticated=False)).action, "HOLD")
        self.assertEqual(decide(proof=usage(account="other")).action, "HOLD")
        self.assertEqual(decide(account="other", proof=usage()).action, "HOLD")
        self.assertEqual(decide(proof=usage(billing_month="2026-11")).action,
                         "HOLD")

    def test_utc_clock_required(self):
        naive = datetime(2026, 10, 20)
        self.assertEqual(decide(now=naive).action, "HOLD")
        jst = timezone(timedelta(hours=9))
        self.assertEqual(decide(now=NOW.astimezone(jst)).action, "HOLD")


class MonthFlagTests(unittest.TestCase):
    def test_verified_month_flag_skips_usage_api(self):
        f = MonthFlag(OWNER, "2026-10", True)
        self.assertEqual(decide(flag=f).action, "FALLBACK_CANDIDATE")
        self.assertEqual(decide(proof=usage(), flag=f).action, "FALLBACK_CANDIDATE")

    def test_next_billing_month_expires_without_timer(self):
        f = MonthFlag(OWNER, "2026-10", True)
        nov = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(decide(now=nov, flag=f).action, "QUERY_BILLING")
        self.assertEqual(decide(now=nov, proof=usage(), flag=f).action,
                         "QUERY_BILLING")

    def test_year_boundary_and_future_flag(self):
        dec = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)
        jan = dec + timedelta(minutes=1)
        f = MonthFlag(OWNER, "2026-12", True)
        self.assertEqual(decide(now=dec, flag=f).action, "FALLBACK_CANDIDATE")
        self.assertEqual(decide(now=jan, flag=f).action, "QUERY_BILLING")
        self.assertEqual(decide(flag=MonthFlag(OWNER, "2026-11", True)).action,
                         "HOLD")

    def test_untrusted_flag_must_not_switch_routes(self):
        for f in (
            MonthFlag("other", "2026-10", True),
            MonthFlag(OWNER, "2026-10", False),
            MonthFlag(OWNER, "2026-13", True),
            MonthFlag(OWNER, "2026-X0", True),
        ):
            with self.subTest(f=f):
                self.assertEqual(decide(flag=f).action, "HOLD")

    def test_flag_only_plans_no_execution(self):
        for result in (decide(), decide(proof=usage()),
                       decide(flag=MonthFlag(OWNER, "2026-10", True)),
                       decide(proof=usage(equivalent_minutes=2000))):
            self.assertNotEqual(result.status, "EXECUTED")
            self.assertIn(result.status, ("PLAN_ONLY", "HOLD"))


if __name__ == "__main__":
    unittest.main()
