"""Lossless bounded KAEP source prefetch and strict source-validation parity."""
from __future__ import annotations

import copy
import json
import threading
import time
import unittest

from tools.kaep_issue_search_view import build_search_list
from tools.kaep_inbox_reader import InvalidMessage
from tests.test_kaep_issue_search_view import (
    DEV, OWNER, comment, issue, pages, root, searched,
)


class ParallelOriginalSourceTests(unittest.TestCase):
    def _fixture(self):
        ids = (575, 576, 577)
        originals = {
            (DEV, n): issue(n=n) for n in ids
        }
        comments = {
            (DEV, n): pages([comment(2000 + n, root(n=n, number=n))])
            for n in ids
        }
        return ids, originals, comments

    def _run(self, ids, originals, comments, workers, *, delay=0):
        active = 0
        maximum = 0
        lock = threading.Lock()
        calls = []
        def observe(name, n):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(active, maximum)
                calls.append((name, n))
            if delay:
                time.sleep(delay)
            with lock:
                active -= 1
        def read_issue(r, n):
            observe("issue", n)
            return copy.deepcopy(originals[(r, n)])
        def read_comments(r, n):
            observe("comments", n)
            return comments[(r, n)]
        output = build_search_list(
            [DEV], {DEV: searched(DEV, ids)},
            fetch_original_issue=read_issue, fetch_comments=read_comments,
            expected_actor=OWNER, recipient="claude-code",
            source_workers=workers,
        )
        output.pop("observed_at")
        return output, calls, maximum

    def test_parallel_two_is_same_strict_output_with_at_most_two_reads(self):
        ids, originals, comments = self._fixture()
        serial, serial_calls, serial_max = self._run(
            ids, originals, comments, 1, delay=0.012,
        )
        parallel, concurrent_calls, parallel_max = self._run(
            ids, originals, comments, 2, delay=0.012,
        )
        self.assertEqual(serial, parallel)
        self.assertEqual(serial["validated_source_issues"], 3)
        self.assertEqual(len(serial["rows"]), 3)
        self.assertEqual(serial["status"], "BOUNDED_SEARCH_READ")
        self.assertEqual(serial_max, 1)
        self.assertEqual(parallel_max, 2)
        self.assertEqual(len(serial_calls), 6)
        self.assertEqual(len(concurrent_calls), 6)
        self.assertEqual(sorted(serial_calls), sorted(concurrent_calls))
        self.assertFalse(parallel["can_authorize_execution"])
        self.assertFalse(parallel["complete_source_universe"])

    def test_invalid_issue_skips_its_comments_and_both_modes_stay_unknown(self):
        ids, originals, comments = self._fixture()
        originals[(DEV, 576)]["html_url"] = "https://invalid.example/issue"
        serial, serial_calls, _ = self._run(ids, originals, comments, 1)
        parallel, concurrent_calls, _ = self._run(ids, originals, comments, 2)
        self.assertEqual(serial, parallel)
        self.assertEqual(parallel["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(parallel["validated_source_issues"], 2)
        self.assertEqual(parallel["errors"][0]["reason_code"],
                         "SOURCE_ISSUE_MISMATCH")
        self.assertNotIn(("comments", 576), serial_calls)
        self.assertNotIn(("comments", 576), concurrent_calls)
        self.assertEqual(len(concurrent_calls), 5)
        self.assertFalse(parallel["can_authorize_execution"])

    def test_bounded_worker_parameter_is_strict(self):
        ids, originals, comments = self._fixture()
        for bad in (0, -1, 3, True, "2"):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                InvalidMessage, "INVALID_SOURCE_WORKERS"
            ):
                self._run(ids, originals, comments, bad)


if __name__ == "__main__":
    unittest.main()
