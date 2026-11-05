"""Offline contract tests for the opt-in bounded KAEP transport comparison."""
from __future__ import annotations

import json
import threading
import time
import unittest

from tools import kaep_transport_compare as compare
from tools.kaep_inbox_reader import InvalidMessage


REPOSITORY = "kinoko34077/devflow"


def issue_payload(number: int, title: str = "fixture") -> dict:
    return {
        "number": number,
        "html_url": f"https://github.com/{REPOSITORY}/issues/{number}",
        "title": title,
    }


def comments_payload(number: int, body: str = "fixture comment") -> str:
    return json.dumps([[
        {
            "id": number * 100,
            "body": body,
            "user": {"id": 7, "login": "fixture-user"},
        }
    ]])


class TransportComparisonTests(unittest.TestCase):
    def test_identical_complete_sources_are_equivalent_and_redacted(self) -> None:
        active = 0
        max_active = 0
        lock = threading.Lock()

        def enter():
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.01)

        def leave():
            nonlocal active
            with lock:
                active -= 1

        def issue_read(repository, number):
            enter()
            try:
                return issue_payload(number, "sensitive issue title")
            finally:
                leave()

        def comments_read(repository, number):
            enter()
            try:
                return comments_payload(number, "sensitive comment body")
            finally:
                leave()

        def recent_read(repository):
            enter()
            try:
                return [{"id": 99, "body": "sensitive recent body"}]
            finally:
                leave()

        result = compare.compare_transport(
            issue_read=issue_read,
            comments_read=comments_read,
            recent_read=recent_read,
        )

        self.assertEqual(result["status"], "BOUNDED_EQUIVALENT")
        self.assertTrue(result["source_equivalent"])
        self.assertEqual(result["invocations"], 10)
        self.assertEqual(result["max_concurrency"], 2)
        self.assertGreaterEqual(max_active, 2)
        self.assertLessEqual(max_active, 2)
        self.assertNotIn("sensitive", json.dumps(result))
        self.assertTrue(all(
            row["status"] == "READ_OK"
            for mode in ("serial", "bounded_parallel")
            for row in result[mode]["reads"]
        ))

    def test_changed_source_is_inconclusive(self) -> None:
        calls = {}
        lock = threading.Lock()

        def next_version(key):
            with lock:
                calls[key] = calls.get(key, 0) + 1
                return calls[key]

        def issue_read(repository, number):
            version = next_version(("issue", number))
            return issue_payload(number, f"version-{version}")

        def comments_read(repository, number):
            version = next_version(("comments", number))
            return comments_payload(number, f"version-{version}")

        def recent_read(repository):
            version = next_version(("recent", repository))
            return [{"id": 99, "body": f"version-{version}"}]

        result = compare.compare_transport(
            issue_read=issue_read,
            comments_read=comments_read,
            recent_read=recent_read,
        )

        self.assertEqual(result["status"], "INCONCLUSIVE_SOURCE_CHANGED")
        self.assertFalse(result["source_equivalent"])

    def test_read_failure_is_inconclusive_without_error_text(self) -> None:
        def fail_comments(repository, number):
            raise InvalidMessage("SENSITIVE_RAW_ERROR")

        result = compare.compare_transport(
            issue_read=lambda repository, number: issue_payload(number),
            comments_read=fail_comments,
            recent_read=lambda repository: [],
        )

        self.assertEqual(result["status"], "INCONCLUSIVE_READ_FAILURE")
        self.assertFalse(result["source_equivalent"])
        self.assertNotIn("SENSITIVE_RAW_ERROR", json.dumps(result))

    def test_non_live_invocation_does_not_read_sources(self) -> None:
        calls = []
        status = compare.main(
            [],
            issue_read=lambda *args: calls.append(args),
            comments_read=lambda *args: calls.append(args),
            recent_read=lambda *args: calls.append(args),
        )
        self.assertEqual(status, 2)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
