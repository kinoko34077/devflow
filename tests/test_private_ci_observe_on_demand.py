"""Offline orchestration checks with synthetic identities only (#752)."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest

from tools.private_ci_billing_block import JobLaunchReceipt
from tools.private_ci_billing_store import LocalBillingObservationStore
from tools.private_ci_observe_on_demand import observe_private_ci_on_demand

OWNER = "fixture-owner"
NOW = datetime(2026, 10, 20, 5, 18, tzinfo=timezone.utc)


class Response:
    status = 200

    def __init__(self, url, month):
        self.url = url
        self.stream = BytesIO(json.dumps({
            "user": OWNER,
            "timePeriod": {"year": 2026, "month": month},
            "usageItems": [{"product": "Actions", "sku": "actions_linux"}],
        }).encode())

    def geturl(self):
        return self.url

    def read(self, n):
        return self.stream.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stream.close()


class FakeOpener:
    def __init__(self):
        self.calls = 0

    def open(self, request, timeout):
        self.calls += 1
        from urllib.parse import urlsplit, parse_qs
        month = int(parse_qs(urlsplit(request.full_url).query)["month"][0])
        return Response(request.full_url, month)


class OnDemandObservationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "journal.sqlite3"

    def observe(self, opener, now=NOW, token="fixture"):
        return observe_private_ci_on_demand(
            OWNER, now, token, self.path, opener=opener)

    def test_http_auth_rejection_is_reported_as_attempted(self):
        from urllib.error import HTTPError

        class Unauthorized:
            def open(self, request, timeout):
                raise HTTPError(request.full_url, 401, "unauthorized", {}, None)

        failed = self.observe(Unauthorized())
        self.assertEqual(failed.action, "QUERY_BILLING_ERROR")
        self.assertTrue(failed.queried_github_billing)

    def test_first_read_and_second_cached(self):
        opener = FakeOpener()
        first = self.observe(opener)
        second = self.observe(opener)
        self.assertEqual(first.action, "REPORT_CACHED")
        self.assertEqual(second.action, "RETAIN_DAILY_INCONCLUSIVE")
        self.assertEqual(opener.calls, 1)

    def test_new_jst_day_rechecks(self):
        opener = FakeOpener()
        self.observe(opener)
        self.observe(opener, now=NOW + timedelta(days=1))
        self.assertEqual(opener.calls, 2)

    def test_utc_month_reset_inside_one_jst_day(self):
        opener = FakeOpener()
        first = datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc)
        self.observe(opener, now=first)
        self.observe(opener, now=first + timedelta(hours=1))
        self.assertEqual(opener.calls, 2)

    def test_no_token_does_not_poison_daily_cache(self):
        opener = FakeOpener()
        missing = self.observe(opener, token="")
        valid = self.observe(opener)
        self.assertEqual(missing.action, "QUERY_BILLING_ERROR")
        self.assertEqual(valid.action, "REPORT_CACHED")
        self.assertEqual(opener.calls, 1)

    def test_month_block_journal_skips_billing_read(self):
        store = LocalBillingObservationStore(self.path)
        fixture = JobLaunchReceipt(
            account=OWNER, repository=OWNER + "/fixture-canary",
            visibility="private", run_id=101, job_id=202,
            head_sha="a" * 40, completed_at_utc=NOW,
            conclusion="failure", runner_name="", steps_count=0,
            annotation=(
                "The job was not started because recent account payments "
                "have failed or your spending limit needs to be increased."
            ),
            authenticated_github_read=True,
        )
        store.record_launch_block(fixture, NOW)
        opener = FakeOpener()
        held = self.observe(opener, token="")
        self.assertEqual(held.action, "PRIVATE_HOSTED_SUPPRESSED")
        self.assertEqual(opener.calls, 0)

    def test_journal_block_is_not_authorization(self):
        first = self.observe(FakeOpener())
        self.assertEqual(first.status, "PLAN_ONLY")
        self.assertNotIn(first.action, {"DISPATCH", "EXECUTE", "APPROVE"})

    def test_missing_database_parent_fails_closed(self):
        self.path = self.path.parent / "missing" / "journal.sqlite3"
        opener = FakeOpener()
        result = self.observe(opener)
        self.assertEqual((result.status, result.action), ("HOLD", "HOLD"))
        self.assertEqual(opener.calls, 0)


if __name__ == "__main__":
    unittest.main()
