"""Offline checks for the explicitly opted-in public GET timing probe."""
from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from tools import kaep_public_get_profile as probe


class PublicGetProfileTests(unittest.TestCase):
    def test_no_opt_in_makes_no_network_request(self):
        with patch.object(probe, "_read_public",
                          side_effect=AssertionError("unexpected network")):
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                self.assertEqual(probe.main([]), 2)
        self.assertEqual(stdout.getvalue().strip(),
                         "KAEP_PUBLIC_GET_PROFILE=OPT_IN_REQUIRED")

    def test_bounded_valid_responses_emit_only_metrics(self):
        called = []
        def fake(path):
            called.append(path)
            if path.endswith("/issues/847"):
                body = json.dumps({"number": 847, "body": "secret fixture"}).encode()
            else:
                body = json.dumps([{"id": 1, "body": "secret fixture"}]).encode()
            return 200, body, 55
        result = probe.profile(fetch=fake)
        self.assertEqual(called, [path for _, path in probe.ENDPOINTS])
        self.assertEqual(result["status"], "BOUNDED_PUBLIC_READ")
        self.assertTrue(result["no_source_authority"])
        self.assertFalse(result["recipient_pickup_proven"])
        self.assertEqual([row["items"] for row in result["observations"]],
                         [1, 1, 1])
        self.assertEqual([row["rate_limit_remaining"]
                          for row in result["observations"]], [55, 55, 55])
        self.assertNotIn("secret fixture", json.dumps(result))

    def test_rate_limit_and_malformed_public_responses_remain_unknown(self):
        def fake(path):
            if path.endswith("/issues/847"):
                return 403, b"token must never leak", 0
            if "/issues/847/comments?" in path:
                return 200, b"{}", 32
            return 200, b"[" + b"x" * probe.MAX_BYTES + b"]", 31
        result = probe.profile(fetch=fake)
        self.assertEqual(result["status"], "PARTIAL_UNKNOWN")
        self.assertEqual([x["status"] for x in result["observations"]],
                         ["RATE_LIMITED", "INVALID_PUBLIC_RESPONSE", "RESPONSE_LIMIT"])
        self.assertNotIn("token must never leak", json.dumps(result))
        self.assertFalse(result["no_source_authority"] is False)

    def test_network_error_only_emits_fixed_reason(self):
        def fake(path):
            raise OSError("private access token error")
        report = probe.profile(fetch=fake)
        self.assertEqual([x["status"] for x in report["observations"]],
                         ["READ_UNAVAILABLE"] * 3)
        self.assertEqual(report["status"], "PARTIAL_UNKNOWN")
        self.assertNotIn("private access token", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
