"""Opt-in serial vs bounded-concurrency comparison for fixed KAEP source reads.

This is a diagnostic only. It never emits Issue/comment text, changes production
fetching, authorizes work, or treats a finite source set as complete.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import sys
import tracemalloc
from time import perf_counter_ns
from typing import Any, Callable

from tools.kaep_inbox_reader import InvalidMessage, parse_pages
from tools.kaep_issue_search_view import fetch_issue
from tools.kaep_inbox_reader import fetch_gh_pages
from tools.kaep_live_delta_view import read_repository_recent


REPOSITORY = "kinoko34077/devflow"
SOURCE_ISSUES = (847, 680)
MAX_CONCURRENCY = 2
RECENT_WINDOW_LIMIT = 100


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _read_jobs(
    *,
    issue_read: Callable[[str, int], dict[str, Any]],
    comments_read: Callable[[str, int], str],
    recent_read: Callable[[str], list[dict[str, Any]]],
) -> list[tuple[str, Callable[[], tuple[Any, int, int, str]]]]:
    jobs: list[tuple[str, Callable[[], tuple[Any, int, int]]]] = []
    for number in SOURCE_ISSUES:
        def read_issue(number: int = number) -> tuple[Any, int, int, str]:
            issue = issue_read(REPOSITORY, number)
            if (type(issue) is not dict or issue.get("number") != number
                    or issue.get("html_url")
                    != f"https://github.com/{REPOSITORY}/issues/{number}"):
                raise InvalidMessage("SOURCE_ISSUE_MISMATCH")
            payload = _canonical_bytes(issue)
            return issue, len(payload), 1, "canonical_json_estimate"

        def read_comments(number: int = number) -> tuple[Any, int, int, str]:
            raw = comments_read(REPOSITORY, number)
            comments = parse_pages(raw, repository=REPOSITORY, issue=number)
            canonical = [
                {
                    "id": item["id"],
                    "body": item["body"],
                    "actor_login": item["actor_login"],
                    "actor_id": item["actor_id"],
                }
                for item in comments
            ]
            return canonical, len(raw.encode("utf-8")), len(comments), "raw_gh_slurp_utf8"

        jobs.append((f"issue_{number}", read_issue))
        jobs.append((f"comments_{number}", read_comments))

    def read_recent() -> tuple[Any, int, int, str]:
        comments = recent_read(REPOSITORY)
        if type(comments) is not list or len(comments) > RECENT_WINDOW_LIMIT:
            raise InvalidMessage("INVALID_RECENT_COMMENTS")
        payload = _canonical_bytes(comments)
        return comments, len(payload), len(comments), "canonical_json_estimate"

    jobs.append(("updated_comment_window", read_recent))
    return jobs


def _read_one(label: str, call: Callable[[], tuple[Any, int, int, str]]) -> dict[str, Any]:
    started = perf_counter_ns()
    try:
        payload, payload_bytes, items, payload_bytes_scope = call()
        fingerprint = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
        status = "READ_OK"
    except Exception:
        # Do not leak raw gh stderr, source text, or exception values.
        status = "READ_UNAVAILABLE"
        fingerprint = None
        payload_bytes = None
        payload_bytes_scope = None
        items = None
    return {
        "source": label,
        "status": status,
        "elapsed_ms": round((perf_counter_ns() - started) / 1_000_000, 3),
        "payload_bytes": payload_bytes,
        "payload_bytes_scope": payload_bytes_scope,
        "items": items,
        "fingerprint_sha256": fingerprint,
    }


def _run_batch(
    jobs: list[tuple[str, Callable[[], tuple[Any, int, int]]]],
    *,
    workers: int,
) -> dict[str, Any]:
    tracemalloc.start()
    started = perf_counter_ns()
    if workers == 1:
        reads = [_read_one(label, call) for label, call in jobs]
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="kaep-read") as pool:
            # executor.map preserves declaration order in the sanitized output.
            reads = list(pool.map(lambda job: _read_one(*job), jobs))
    elapsed_ms = round((perf_counter_ns() - started) / 1_000_000, 3)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "elapsed_ms": elapsed_ms,
        "peak_traced_bytes": peak_bytes,
        "reads": reads,
    }


def compare_transport(
    *,
    issue_read: Callable[[str, int], dict[str, Any]] = fetch_issue,
    comments_read: Callable[[str, int], str] = fetch_gh_pages,
    recent_read: Callable[[str], list[dict[str, Any]]] = read_repository_recent,
) -> dict[str, Any]:
    """Read a fixed source set twice and compare complete sanitized fingerprints."""
    jobs = _read_jobs(
        issue_read=issue_read,
        comments_read=comments_read,
        recent_read=recent_read,
    )
    serial = _run_batch(jobs, workers=1)
    parallel = _run_batch(jobs, workers=MAX_CONCURRENCY)
    serial_by_source = {row["source"]: row for row in serial["reads"]}
    parallel_by_source = {row["source"]: row for row in parallel["reads"]}
    all_ok = all(
        row["status"] == "READ_OK"
        for row in serial["reads"] + parallel["reads"]
    )
    equivalent = all_ok and all(
        serial_by_source[source]["fingerprint_sha256"]
        == parallel_by_source[source]["fingerprint_sha256"]
        for source, _call in jobs
    )
    if not all_ok:
        status = "INCONCLUSIVE_READ_FAILURE"
    elif equivalent:
        status = "BOUNDED_EQUIVALENT"
    else:
        status = "INCONCLUSIVE_SOURCE_CHANGED"
    return {
        "schema_version": "kaep.transport-compare.v0.1",
        "kind": "READ_ONLY_FIXED_SOURCE_TRANSPORT_COMPARISON",
        "status": status,
        "read_only": True,
        "can_authorize_execution": False,
        "complete_source_universe": False,
        "source_equivalent": equivalent,
        "source_set": [label for label, _call in jobs],
        "invocations": len(jobs) * 2,
        "max_concurrency": MAX_CONCURRENCY,
        "serial": serial,
        "bounded_parallel": parallel,
        "speedup_claim": "NOT_ESTABLISHED_SINGLE_PAIRED_RUN",
    }


def main(
    argv: list[str] | None = None,
    *,
    issue_read: Callable[[str, int], dict[str, Any]] = fetch_issue,
    comments_read: Callable[[str, int], str] = fetch_gh_pages,
    recent_read: Callable[[str], list[dict[str, Any]]] = read_repository_recent,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Explicitly run the fixed read-only source comparison",
    )
    args = parser.parse_args(argv)
    if not args.live:
        print("KAEP_TRANSPORT_COMPARE=OPT_IN_REQUIRED")
        return 2
    result = compare_transport(
        issue_read=issue_read,
        comments_read=comments_read,
        recent_read=recent_read,
    )
    print("KAEP_TRANSPORT_COMPARE=" + json.dumps(
        result, sort_keys=True, separators=(",", ":"),
    ), flush=True)
    return 0 if result["status"] == "BOUNDED_EQUIVALENT" else 2


if __name__ == "__main__":
    sys.exit(main())
