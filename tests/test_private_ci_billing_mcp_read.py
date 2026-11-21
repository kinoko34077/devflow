"""個人料金MCP読取アダプタ：本人が既に配置した合成キャッシュのみテストする。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from tools.private_ci_billing_mcp_read import (
    CACHE_ENV, get_configured_billing_observation,
)
from tools.private_ci_billing_ui import normalize_ui

ACCOUNT = "kinoko34077"
NOW = datetime(2026, 7, 12, 10, tzinfo=timezone.utc)


def fake_observation():
    return normalize_ui({
        "account": ACCOUNT,
        "period": "Gross metered usage for July 1 - July 31, 2026.",
        "discount_period": "Included usage discounts for July 1 - July 31, 2026.",
        "gross": "$22.00",
        "included_discount": "$22.00",
        "consumed": "$22.00",
        "actions_discount": "$22.00",
        "billable": "$0",
        "compute": "$13 used / $12 included",
        "storage": "0 GB used / 0.5 GB included",
        "budget_amount": "$0.00 / $0.00 spent",
        "budget_state": "100% of budget limit used 100% Usage blocked",
    }, ACCOUNT, NOW)


class BillingMcpReadTests(unittest.TestCase):
    def test_unconfigured_or_untrusted_path_is_unknown(self):
        for env in ({}, {CACHE_ENV: ""}, {CACHE_ENV: "relative.json"},
                    {CACHE_ENV: "../billing.json"}):
            with self.subTest(env=env):
                result = get_configured_billing_observation(environ=env, now_utc=NOW)
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertIs(result["verified_for_dispatch"], False)
                self.assertNotIn("account", result)
                self.assertFalse(any(k.endswith("_usd") for k in result))

    def test_pinned_cache_status_and_explicit_private_details(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "billing-observation.json"
            observation = fake_observation()
            cache.write_text(json.dumps(observation), encoding="utf-8")
            env = {CACHE_ENV: str(cache)}
            status = get_configured_billing_observation(
                environ=env, now_utc=NOW + timedelta(minutes=2))
            self.assertEqual(
                status["status"], "INCLUDED_COMPUTE_AT_OR_ABOVE_LIMIT_AND_BUDGET_BLOCKED")
            self.assertNotIn("compute_used_usd", status)
            self.assertNotIn("account", status)
            self.assertIs(status["verified_for_dispatch"], False)
            detail = get_configured_billing_observation(
                True, environ=env, now_utc=NOW + timedelta(minutes=2))
            self.assertEqual(detail["compute_used_usd"], "13.00")
            self.assertEqual(detail["account"], ACCOUNT)
            self.assertIs(detail["verified_for_dispatch"], False)

    def test_cache_stale_future_corrupt_or_wrong_account_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "billing.json"
            env = {CACHE_ENV: str(cache)}
            observed = fake_observation()
            for variant, date in (
                (observed, NOW + timedelta(hours=13)),
                (observed, NOW - timedelta(seconds=1)),
                ({**observed, "account": "someone-else"}, NOW),
                ({**observed, "verified_for_dispatch": True}, NOW),
                ({**observed, "status": "WITHIN_INCLUDED_COMPUTE"}, NOW),
            ):
                with self.subTest(variant=variant, date=date):
                    cache.write_text(json.dumps(variant), encoding="utf-8")
                    result = get_configured_billing_observation(
                        True, environ=env, now_utc=date)
                    self.assertEqual(result["status"], "UNKNOWN")
                    self.assertNotIn("compute_used_usd", result)
                    self.assertIs(result["verified_for_dispatch"], False)

    def test_unknown_never_leaks_path_or_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private.json"
            path.write_text("not json\nTOP_SECRET_LITERAL", encoding="utf-8")
            result = get_configured_billing_observation(
                environ={CACHE_ENV: str(path)}, now_utc=NOW)
            self.assertEqual(result["status"], "UNKNOWN")
            self.assertNotIn("TOP_SECRET_LITERAL", repr(result))
            self.assertNotIn(directory, repr(result))


if __name__ == "__main__":
    unittest.main()
