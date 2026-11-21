"""Regression cases for GitHub Billing UI observation. Synthetic data only."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import private_ci_billing_ui as observer

NOW = datetime(2026, 7, 12, 10, tzinfo=timezone.utc)
ACCOUNT = "fixture-user"
REQUEST_ID = "a" * 32


def fixture(**changes):
    raw = {
        "account": ACCOUNT,
        "period": "Gross metered usage for July 1 - July 31, 2026.",
        "discount_period": "Included usage discounts for July 1 - July 31, 2026.",
        "gross": "$52.80", "included_discount": "$52.80",
        "consumed": "$52.91", "actions_discount": "$52.91", "billable": "$0",
        "compute": "$13.00 used / $12.00 included",
        "storage": "0 GB used / 0.5 GB included",
        "budget_amount": "$0.00 / $0.00 spent",
        "budget_state": "100% of budget limit used 100% Usage blocked",
    }
    raw.update(changes)
    return raw


class BillingUiTests(unittest.TestCase):
    def test_compute_and_budget_independently_observed(self):
        observed = observer.normalize_ui(fixture(), ACCOUNT, NOW)
        self.assertEqual(observed["status"], "INCLUDED_COMPUTE_AT_OR_ABOVE_LIMIT_AND_BUDGET_BLOCKED")
        self.assertEqual(observed["compute_used_usd"], "13.00")
        self.assertEqual(observed["actions_billable_usd"], "0.00")
        self.assertIs(observed["actions_budget_usage_blocked"], True)
        self.assertIs(observed["verified_for_dispatch"], False)

    def test_zero_extra_budget_does_not_imply_free_compute_exhaustion(self):
        result = observer.normalize_ui(fixture(compute="$3.25 used / $12.00 included"), ACCOUNT, NOW)
        self.assertEqual(result["status"], "WITHIN_INCLUDED_COMPUTE_AND_BUDGET_BLOCKED")

    def test_when_compute_within_limit_without_budget_block(self):
        result = observer.normalize_ui(fixture(
            compute="$3.25 used / $12.00 included",
            budget_state="10% of budget limit used 10%",
        ), ACCOUNT, NOW)
        self.assertEqual(result["status"], "WITHIN_INCLUDED_COMPUTE")
        summary = observer.status_view(result)
        self.assertIsNone(summary["actions_budget_usage_blocked"])

    def test_absence_of_budget_block_label_is_not_permission(self):
        result = observer.normalize_ui(fixture(budget_state="10% of budget limit used 10%"),
                                       ACCOUNT, NOW)
        self.assertIsNone(result["actions_budget_usage_blocked"])
        self.assertIs(result["verified_for_dispatch"], False)

    def test_at_limit(self):
        result = observer.normalize_ui(fixture(compute="$12 used / $12 included"), ACCOUNT, NOW)
        self.assertEqual(result["status"], "INCLUDED_COMPUTE_AT_OR_ABOVE_LIMIT_AND_BUDGET_BLOCKED")

    def test_unsupported_or_stale_fields_fail_closed(self):
        for changes in (
            {"account": "wrong-account"}, {"period": "July"},
            {"discount_period": "Included usage discounts for June 1 - June 30, 2026."},
            {"compute": "$0.00"}, {"compute": "$-1 used / $12 included"},
            {"budget_state": "100% of budget limit used 10% Usage blocked"},
            {"gross": "$1,2.00"}, {"budget_amount": "$0.00 / $0.00"},
            {"storage": "unknown"}, {"billable": None},
        ):
            with self.subTest(changes=changes), self.assertRaises(observer.ObservationUnavailable):
                observer.normalize_ui(fixture(**changes), ACCOUNT, NOW)

    def test_valid_cache_freshness_and_tampering(self):
        observed = observer.normalize_ui(fixture(), ACCOUNT, NOW)
        self.assertEqual(observer.validate_cached(observed, ACCOUNT, NOW + timedelta(minutes=1)), observed)
        for changed in (
            dict(observed, status="WITHIN_INCLUDED_COMPUTE"),
            dict(observed, verified_for_dispatch=True),
            dict(observed, compute_used_usd="nan"),
            dict(observed, account="someone-else"),
        ):
            with self.subTest(changed=changed), self.assertRaises(observer.ObservationUnavailable):
                observer.validate_cached(changed, ACCOUNT, NOW)
        for clock in (NOW - timedelta(seconds=1), NOW + timedelta(hours=13),
                      datetime(2026, 8, 1, tzinfo=timezone.utc)):
            with self.assertRaises(observer.ObservationUnavailable):
                observer.validate_cached(observed, ACCOUNT, clock)

    def test_status_view_redacts_financial_amounts(self):
        result = observer.status_view(observer.normalize_ui(fixture(), ACCOUNT, NOW))
        self.assertNotIn("account", result)
        self.assertFalse(any(k.endswith("_usd") for k in result))

    def test_request_is_fixed_and_expires(self):
        raw = {"schema": observer.REQUEST_SCHEMA, "account": ACCOUNT,
               "action": "OBSERVE_BILLING", "request_id": REQUEST_ID,
               "requested_at_utc": NOW.isoformat()}
        self.assertEqual(observer.parse_request(raw, ACCOUNT, NOW), REQUEST_ID)
        for bad in (dict(raw, command="arbitrary"), dict(raw, action="EXECUTE"),
                    dict(raw, account="wrong"), dict(raw, request_id="../x")):
            with self.assertRaises(observer.ObservationUnavailable):
                observer.parse_request(bad, ACCOUNT, NOW)
        with self.assertRaises(observer.ObservationUnavailable):
            observer.parse_request(raw, ACCOUNT, NOW+timedelta(minutes=31))

    def test_marker_directory_is_fixed_and_rejects_ambiguity(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertIsNone(observer.parse_marker_directory(root, ACCOUNT, NOW))
            marker = root / "billing-request-idle.request"
            marker.touch()
            self.assertIsNone(observer.parse_marker_directory(root, ACCOUNT, NOW))
            target = root / ("billing-request-20260712T100000Z-" + REQUEST_ID + ".request")
            marker.rename(target)
            # Requests are determined only by the exact filename, never contents.
            target.write_text("arbitrary text is not executed or opened")
            self.assertEqual(observer.parse_marker_directory(root, ACCOUNT, NOW), REQUEST_ID)
            self.assertIsNone(observer.parse_marker_directory(root, ACCOUNT, NOW + timedelta(minutes=31)))
            marker.touch()
            with self.assertRaises(observer.ObservationUnavailable):
                observer.parse_marker_directory(root, ACCOUNT, NOW)

    def test_marker_request_same_id_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "billing.json"
            observed = observer.normalize_ui(fixture(), ACCOUNT, NOW)
            observed["request_id"] = REQUEST_ID
            observer._atomic_write(target, observed)
            with patch.object(observer, "parse_marker_directory", return_value=REQUEST_ID), \
                patch.object(observer, "_collect") as collect:
                rc = observer.main(["--account", ACCOUNT, "--cache", str(target),
                                    "--serve-marker-dir", d, "--request-ledger", str(Path(d) / "ledger.sqlite3"), "--status-only"])
                self.assertEqual(rc, 0)
                collect.assert_not_called()

    def test_default_ledger_directory_created_on_fresh_host(self):
        with tempfile.TemporaryDirectory() as root:
            local_appdata = Path(root) / "fresh-localappdata"
            local_appdata.mkdir()
            with patch.dict(observer.os.environ, {"LOCALAPPDATA": str(local_appdata)}):
                ledger = observer._request_ledger_path(None)
            self.assertTrue(ledger.parent.is_dir())
            self.assertEqual(ledger.parent.name, "devflow-billing-observer")
            self.assertTrue(observer.reserve_request(ledger, ACCOUNT, REQUEST_ID, NOW))
            self.assertFalse(observer.reserve_request(ledger, ACCOUNT, REQUEST_ID, NOW))

    def test_custom_ledger_location_not_created_implicitly(self):
        with tempfile.TemporaryDirectory() as root:
            custom = Path(root) / "not-allowed-parent" / "ledger.sqlite3"
            self.assertEqual(observer._request_ledger_path(custom), custom)
            with self.assertRaises(observer.ObservationUnavailable):
                observer.reserve_request(custom, ACCOUNT, REQUEST_ID, NOW)

    def test_delayed_request_replay_survives_cache_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "billing.json"
            ledger = Path(d) / "ledger.sqlite3"
            args = ["--account", ACCOUNT, "--cache", str(target),
                    "--serve-marker-dir", d, "--request-ledger", str(ledger),
                    "--status-only"]
            a, b = "a" * 32, "b" * 32
            with patch.object(observer, "parse_marker_directory", side_effect=[a, b, a]), \
                patch.object(observer, "_collect", side_effect=lambda account: observer.normalize_ui(fixture(), account, NOW)) as collect:
                self.assertEqual(observer.main(args), 0)
                self.assertEqual(observer.main(args), 0)
                self.assertEqual(observer.main(args), 0)
                self.assertEqual(collect.call_count, 2)
                self.assertEqual(json.loads(target.read_text())["request_id"], b)

    def test_ledger_is_account_scoped_and_durable(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = Path(d) / "requests.sqlite3"
            self.assertTrue(observer.reserve_request(ledger, ACCOUNT, REQUEST_ID, NOW))
            self.assertFalse(observer.reserve_request(ledger, ACCOUNT.upper(), REQUEST_ID, NOW + timedelta(minutes=2)))
            self.assertTrue(observer.reserve_request(ledger, "other-account", REQUEST_ID, NOW))

    def test_cache_write_replaces_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "billing.json"
            data = observer.normalize_ui(fixture(), ACCOUNT, NOW)
            observer._atomic_write(target, data)
            self.assertEqual(json.loads(target.read_text()), data)
            observer._atomic_write(target, {"status":"UNKNOWN"})
            self.assertEqual(json.loads(target.read_text()), {"status":"UNKNOWN"})
            self.assertEqual(len(list(Path(d).iterdir())), 1)

    def test_unavailable_observation_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "billing.json"
            observer._atomic_write(target, observer.normalize_ui(fixture(), ACCOUNT, NOW))
            with patch.object(observer, "_collect", side_effect=observer.ObservationUnavailable("TEST_UNAVAILABLE")):
                self.assertEqual(observer.main(["--account", ACCOUNT, "--cache", str(target), "--status-only"]), 2)
            self.assertEqual(json.loads(target.read_text())["status"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
