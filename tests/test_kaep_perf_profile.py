"""Offline KAEP path profile; not a network latency or authority test.

GitHub Actions unittest discovery emits one KAEP_PROFILE_JSON line. Results
are observations on that runner, not stable performance assertions.
Never skip live original-source revalidation.
"""
from __future__ import annotations

import gc
import json
import statistics
import sys
import time
import tracemalloc
import unittest

from tools import kaep_live_union_cli as union
from tools import kaep_public_incremental_cli as incremental
from tests.test_kaep_live_candidate_cli import (
    REPO, index_with, issue_object, root, source_page,
)
from tests.test_kaep_public_locator_cli import OWNER, comment, repo


def _profile(run, *, samples=5):
    """Time actual production Python pathways with injected offline GETs."""
    elapsed_ms = []
    process_ms = []
    for _ in range(samples):
        gc.collect()
        start_wall = time.perf_counter_ns()
        start_cpu = time.process_time_ns()
        run()
        process_ms.append((time.process_time_ns() - start_cpu) / 1_000_000)
        elapsed_ms.append((time.perf_counter_ns() - start_wall) / 1_000_000)
    gc.collect()
    tracemalloc.start()
    try:
        run()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {
        "samples": samples,
        "elapsed_ms_median": round(statistics.median(elapsed_ms), 3),
        "elapsed_ms_min": round(min(elapsed_ms), 3),
        "elapsed_ms_max": round(max(elapsed_ms), 3),
        "cpu_ms_median": round(statistics.median(process_ms), 3),
        "peak_traced_kib": round(peak / 1024, 1),
    }


class KAEPPathPerformanceEvidence(unittest.TestCase):
    def test_profile_bounded_original_union_and_public_incremental(self):
        # 40 distinct canonical original issues: the actual union source limit.
        roots = [(n, root(number=n, issue=n)) for n in range(501, 541)]
        snapshot = index_with(
            *((n, 1000 + n, msg) for n, msg in roots),
            status="BOUNDED_SEARCH_READ",
        )
        sources = {
            (REPO, n): source_page((1000 + n, msg, "kinoko34077"))
            for n, msg in roots
        }

        def union_run():
            calls = {"recent": 0, "issue": 0, "comments": 0}
            def recent_read(name, since=None):
                self.assertEqual(name, REPO)
                calls["recent"] += 1
                return []
            def issue_read(name, issue):
                self.assertEqual(name, REPO)
                calls["issue"] += 1
                return issue_object(issue)
            def comments_read(name, issue):
                calls["comments"] += 1
                return sources[(name, issue)]
            result = union.read_union(
                snapshot, recipient="claude-code", recent_read=recent_read,
                issue_read=issue_read, comments_read=comments_read,
            )
            self.assertEqual(result["source_issue_count"], 40)
            self.assertEqual(result["live_original_roots"], 40)
            self.assertEqual(calls, {"recent": 1, "issue": 40, "comments": 40})
            self.assertTrue(result["has_unknown_work"])
            self.assertFalse(result["can_authorize_execution"])

        names = ["devflow", "testapp"]
        owner_repos = [repo(name) for name in names]
        full_pages = {}
        for name in names:
            full_pages[name] = {
                1: [comment(name, 800, cid) for cid in range(240, 140, -1)],
                2: [comment(name, 800, cid) for cid in range(140, 120, -1)],
            }

        def public_fetch(pages, call_log):
            def fetch(path):
                call_log.append(path)
                if path.startswith("/users/"):
                    return owner_repos
                for name in names:
                    if path.startswith(f"/repos/{OWNER}/{name}/issues/comments?"):
                        page = int(path.rsplit("&page=", 1)[1])
                        return pages[name][page]
                raise AssertionError("Unrecognized public fixture path")
            return fetch

        def full_run():
            requests = []
            out = incremental.discover_incremental(
                fetch=public_fetch(full_pages, requests),
                max_repo_pages=2, max_comment_pages=3,
            )
            self.assertEqual(out["status"], "BOUNDED_INCREMENTAL_BASELINE")
            self.assertEqual(out["locator_count"], 240)
            self.assertEqual(out["api_requests_used"], 5)
            self.assertEqual(len(requests), 5)
            self.assertEqual(
                out["next_cursor"]["heads"],
                {f"{OWNER}/{name}": 240 for name in names},
            )
            self.assertFalse(out["can_authorize_execution"])

        # Two repositories, three new markers plus a prior exact head each.
        incremental_pages = {
            name: {1: [
                comment(name, 801, 243), comment(name, 801, 242),
                comment(name, 801, 241), comment(name, 800, 240),
            ]} for name in names
        }
        previous = incremental._checkpoint({
            f"{OWNER}/{name}": 240 for name in names
        })

        def incremental_run():
            requests = []
            out = incremental.discover_incremental(
                prior=previous, fetch=public_fetch(incremental_pages, requests),
                max_repo_pages=2, max_comment_pages=3,
            )
            self.assertEqual(out["status"], "BOUNDED_INCREMENTAL_READ")
            self.assertEqual(out["locator_count"], 6)
            self.assertEqual(out["api_requests_used"], 3)
            self.assertEqual(len(requests), 3)
            self.assertEqual(out["next_cursor"]["heads"],
                             {f"{OWNER}/{name}": 243 for name in names})
            self.assertFalse(out["can_authorize_execution"])

        report = {
            "schema_version": "kaep.offline-path-profile.v0.1",
            "environment": "unittest-runner",
            "python": sys.version.split()[0],
            "timing_scope": "injected-offline-GET-actual-production-path",
            "interpretation": "single-run-observation-not-latency-guarantee",
            "cases": {
                "union_40_original_issues": _profile(union_run),
                "public_baseline_2repos_240comments": _profile(full_run),
                "public_incremental_2repos_6new": _profile(incremental_run),
            },
            "expected_get_counts": {
                "union": {"recent": 1, "issue": 40, "comments": 40},
                "baseline": 5,
                "incremental": 3,
            },
        }
        print("KAEP_PROFILE_JSON=" + json.dumps(
            report, sort_keys=True, separators=(",", ":"),
        ), file=sys.stderr, flush=True)


if __name__ == "__main__":
    unittest.main()
