"""Bounded read-only KAEP gh CLI original-source transport timing diagnostic.

Runs only with --live and an already available gh auth context. Results are
non-authoritative; no original Issue/comment text or exception body is logged.
"""
from __future__ import annotations

import argparse
import json
import sys
from time import perf_counter_ns
from typing import Any, Callable

from tools.kaep_inbox_reader import (
    InvalidMessage, fetch_gh_pages, parse_pages,
)
from tools.kaep_issue_search_view import fetch_issue
from tools.kaep_live_delta_view import read_repository_recent

REPOSITORY = "kinoko34077/devflow"
SOURCE_ISSUES = (847, 680)


def profile(
    *, issue_read: Callable[[str, int], dict[str, Any]] = fetch_issue,
    comments_read: Callable[[str, int], str] = fetch_gh_pages,
    recent_read: Callable[[str], list[dict[str, Any]]] = read_repository_recent,
) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []

    def measure(label: str, call: Callable[[], tuple[int, int]]) -> None:
        started = perf_counter_ns()
        try:
            records, payload_bytes = call()
            status = "READ_OK"
        except (InvalidMessage, OSError, ValueError, TypeError, TimeoutError):
            status = "READ_UNAVAILABLE"
            records = None
            payload_bytes = None
        observations.append({
            "endpoint": label,
            "status": status,
            "elapsed_ms": round((perf_counter_ns() - started) / 1_000_000, 3),
            "body_bytes": payload_bytes,
            "items": records,
        })

    for number in SOURCE_ISSUES:
        def read_issue() -> tuple[int, int]:
            issue = issue_read(REPOSITORY, number)
            if type(issue) is not dict or issue.get("number") != number or (
                issue.get("html_url") !=
                f"https://github.com/{REPOSITORY}/issues/{number}"
            ):
                raise InvalidMessage("INVALID_PUBLIC_ISSUE")
            # Serializing decoded data estimates bytes and is not the exact
            # wire size; record it distinctly rather than calling it HTTP bytes.
            return 1, len(json.dumps(issue, ensure_ascii=False).encode("utf-8"))
        measure(f"issue_{number}", read_issue)

        def read_comments() -> tuple[int, int]:
            text = comments_read(REPOSITORY, number)
            comments = parse_pages(text, repository=REPOSITORY, issue=number)
            return len(comments), len(text.encode("utf-8"))
        measure(f"comments_{number}", read_comments)

    def read_recent() -> tuple[int, int]:
        comments = recent_read(REPOSITORY)
        if type(comments) is not list or len(comments) > 100:
            raise InvalidMessage("INVALID_RECENT_COMMENTS")
        return len(comments), len(json.dumps(comments, ensure_ascii=False).encode("utf-8"))
    measure("updated_comment_window", read_recent)

    return {
        "schema_version": "kaep.gh-original-read-profile.v0.1",
        "kind": "READ_ONLY_KAEP_ACTUAL_GH_PATH_DIAGNOSTIC",
        "status": "BOUNDED_READ" if all(
            row["status"] == "READ_OK" for row in observations
        ) else "PARTIAL_UNKNOWN",
        "read_only": True,
        "can_authorize_execution": False,
        "recipient_pickup_proven": False,
        "complete_source_universe": False,
        "timing_scope": "github_actions_gh_api_production_entrypoints",
        "payload_bytes_scope": "serialized_issue_or_recent_estimate;comments_raw_slurp_utf8",
        "invocations": len(observations),
        "observations": observations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="Explicitly run fixed read-only gh api requests")
    args = parser.parse_args(argv)
    if not args.live:
        print("KAEP_GH_READ_PROFILE=OPT_IN_REQUIRED")
        return 2
    result = profile()
    print("KAEP_GH_READ_PROFILE=" + json.dumps(
        result, sort_keys=True, separators=(",", ":"),
    ), flush=True)
    return 0 if result["status"] == "BOUNDED_READ" else 2


if __name__ == "__main__":
    sys.exit(main())
