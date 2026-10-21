"""Pure offline tests for token-ephemeral personal billing GET (#752)."""
from datetime import datetime, timezone
from io import BytesIO
import json
import tempfile
from pathlib import Path
import unittest
from urllib.error import HTTPError, URLError

from tools.private_ci_billing_readonly import fetch_actions_summary_once
from tools.private_ci_billing_store import LocalBillingObservationStore

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)
ACCOUNT = "kinoko34077"
TOKEN = "nonsecret-example-token-for-test"


class FakeResponse:
    status = 200
    def __init__(self, url, body, status=200, effective_url=None):
        self.url = effective_url or url
        self.body = BytesIO(body)
        self.status = status

    def geturl(self):
        return self.url

    def read(self, amount):
        return self.body.read(amount)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.body.close()


def report(**overrides):
    data = {
        "user": ACCOUNT,
        "timePeriod": {"year": 2026, "month": 10},
        "usageItems": [
            {
                "product": "Actions",
                "sku": "actions_linux",
                "grossQuantity": 30830,
                "discountQuantity": 30830,
                "netQuantity": 0,
            },
        ],
    }
    data.update(overrides)
    return json.dumps(data).encode()


class FakeOpener:
    def __init__(self, body=None, http_error=None, effective_url=None, status=200):
        self.body = report() if body is None else body
        self.http_error = http_error
        self.effective_url = effective_url
        self.status = status
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if self.http_error == "offline":
            raise URLError("offline")
        if self.http_error is not None:
            raise HTTPError(request.full_url, self.http_error, "HTTP failure", {}, None)
        return FakeResponse(request.full_url, self.body, status=self.status,
                            effective_url=self.effective_url)


def query(opener, token=TOKEN, account=ACCOUNT, now=NOW):
    return fetch_actions_summary_once(account, now, token, opener=opener)


class BillingReadOnlyTests(unittest.TestCase):
    def test_documented_year_only_period_is_valid_for_pinned_month(self):
        # GitHub official summary schema includes timePeriod.year only.
        # The request itself includes year/month, and no competing period.
        opener = FakeOpener(body=report(timePeriod={"year": 2026}))
        value = query(opener)
        self.assertEqual(value.status, "REPORT_RECEIVED_INCONCLUSIVE")
        self.assertTrue(value.request_attempted)
        self.assertIsNone(value.included_minutes_exhausted)

    def test_explicit_month_mismatch_or_malformed_month_rejected(self):
        for period in (
            {"year": 2026, "month": 9},
            {"year": 2026, "month": "10"},
            {"year": 2025},
        ):
            with self.subTest(period=period):
                result = query(FakeOpener(body=report(timePeriod=period)))
                self.assertEqual(result.status, "HOLD")
                self.assertTrue(result.request_attempted)

    def test_attempted_http_failure_vs_preflight_failure(self):
        blocked = query(FakeOpener(http_error=401))
        unavailable = query(FakeOpener(http_error="offline"))
        absent = query(FakeOpener(), token="")
        self.assertEqual(blocked.status, "AUTH_UNAVAILABLE")
        self.assertTrue(blocked.request_attempted)
        self.assertTrue(unavailable.request_attempted)
        self.assertFalse(absent.request_attempted)

    def test_fixed_destination_one_get_with_ephemeral_token(self):
        transport = FakeOpener()
        result = query(transport)
        self.assertEqual(result.status, "REPORT_RECEIVED_INCONCLUSIVE")
        self.assertEqual(result.included_minutes_exhausted, None)
        self.assertEqual(result.usage_rows, 1)
        self.assertEqual(len(transport.requests), 1)
        req, timeout = transport.requests[0]
        self.assertEqual(req.get_method(), "GET")
        self.assertEqual(req.full_url,
            "https://api.github.com/users/kinoko34077/settings/billing/usage/summary?year=2026&month=10&product=Actions")
        self.assertEqual(req.get_header("Authorization"), "Bearer " + TOKEN)
        self.assertEqual(timeout, 10)
        self.assertNotIn(TOKEN, repr(result))
        self.assertNotIn(TOKEN, req.full_url)

    def test_gross_free_discount_never_signals_exhaustion(self):
        transport = FakeOpener(body=report(usageItems=[
            {"product": "Actions", "sku": "actions_linux",
             "grossQuantity": 30830, "discountQuantity": 30830,
             "netQuantity": 0},
            {"product": "Actions", "sku": "actions_windows",
             "grossQuantity": 7708, "discountQuantity": 7708,
             "netQuantity": 0},
        ]))
        observed = query(transport)
        self.assertEqual(observed.status, "REPORT_RECEIVED_INCONCLUSIVE")
        self.assertIsNone(observed.included_minutes_exhausted)

    def test_missing_token_never_requests_network(self):
        opener = FakeOpener()
        result = query(opener, token="")
        self.assertEqual(result.status, "AUTH_UNAVAILABLE")
        self.assertEqual(opener.requests, [])

    def test_header_injection_rejected(self):
        for token in ("bad\rAuthorization: hi", "bad\nHost:evil"):
            with self.subTest(token=token):
                self.assertEqual(query(FakeOpener(), token=token).status,
                                 "AUTH_UNAVAILABLE")

    def test_invalid_account_or_clock(self):
        opener = FakeOpener()
        self.assertEqual(query(opener, account="../evil").status, "HOLD")
        self.assertEqual(query(opener, now=NOW.replace(tzinfo=None)).status, "HOLD")
        self.assertEqual(opener.requests, [])

    def test_auth_and_network_failures_sanitized(self):
        for code in (401, 403, 404):
            res = query(FakeOpener(http_error=code))
            self.assertEqual(res.status, "AUTH_UNAVAILABLE")
            self.assertNotIn(TOKEN, repr(res))
        self.assertEqual(query(FakeOpener(http_error="offline")).status,
                         "API_UNAVAILABLE")
        self.assertEqual(query(FakeOpener(http_error=500)).status,
                         "API_UNAVAILABLE")

    def test_redirect_or_unexpected_status_fail_closed(self):
        self.assertEqual(query(FakeOpener(
            effective_url="https://other.example/collect")).status, "HOLD")
        self.assertEqual(query(FakeOpener(status=204)).status, "API_UNAVAILABLE")

    def test_too_large_response_or_invalid_json(self):
        self.assertEqual(query(FakeOpener(body=b"x" * (1024*1024+5))).status, "HOLD")
        self.assertEqual(query(FakeOpener(body=b"{bad")).status, "HOLD")

    def test_wrong_owner_and_unknown_period_rejected(self):
        for payload in (
            {"user": "another"},
            {"timePeriod": {"year": "2026"}},
            {"timePeriod": {"year": 2025, "month": 10}},
            {"timePeriod": {"year": 2026, "month": 11}},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(query(FakeOpener(body=report(**payload))).status,
                                 "HOLD")

    def test_incompatible_schema_rejected(self):
        for payload in (
            {"usageItems": None},
            {"usageItems": [{"product": "Codespaces"}]},
            {"usageItems": [{"product": "Actions"}, {"product": None}]},
            {"user": 5},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(query(FakeOpener(body=report(**payload))).status,
                                 "HOLD")

    def test_summary_can_feed_journal_without_storing_token(self):
        observed = query(FakeOpener())
        with tempfile.TemporaryDirectory() as folder:
            filename = Path(folder) / "billing.sqlite3"
            store = LocalBillingObservationStore(filename)
            record = store.record_daily(ACCOUNT, NOW, observed.status)
            self.assertEqual(record.observation, "REPORT_RECEIVED_INCONCLUSIVE")
            self.assertIsNone(store.read_monthly_block(ACCOUNT, NOW))
            self.assertNotIn(TOKEN.encode(), filename.read_bytes())


if __name__ == "__main__":
    unittest.main()
