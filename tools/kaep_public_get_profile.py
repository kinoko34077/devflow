"""Bounded public GitHub GET latency/size probe; evidence, NOT source authority.

Never prints issue/comment payloads, credentials or untrusted exception text.
Network is explicit (--live), endpoints are fixed public devflow resources.
A successful probe does not establish source-universe completeness or pickup.
"""
from __future__ import annotations

import argparse
import json
import sys
from time import perf_counter_ns
from typing import Callable, Any
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPRedirectHandler, Request, build_opener,
)

MAX_BYTES = 4_000_000
ENDPOINTS = (
    ("issue_metadata", "/repos/kinoko34077/devflow/issues/847"),
    ("issue_comments", "/repos/kinoko34077/devflow/issues/847/comments?per_page=100&page=1"),
    ("recent_comments", "/repos/kinoko34077/devflow/issues/comments?sort=updated&direction=desc&per_page=100&page=1"),
)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_public(path: str) -> tuple[int, bytes, int | None]:
    """GET only hard-coded paths; no token, redirect, retry or arbitrary host."""
    if path not in dict(ENDPOINTS).values():
        raise ValueError("INVALID_PROBE_PATH")
    req = Request(
        "https://api.github.com" + path,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "kinotch-kaep-readonly-diagnostic"},
        method="GET",
    )
    opener = build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=12) as response:
            body = response.read(MAX_BYTES + 1)
            header = response.headers.get("X-RateLimit-Remaining")
            remaining = int(header) if header is not None and header.isdecimal() else None
            return response.status, body, remaining
    except HTTPError as exc:
        header = exc.headers.get("X-RateLimit-Remaining")
        remaining = int(header) if header is not None and header.isdecimal() else None
        return exc.code, b"", remaining


def profile(
    *, fetch: Callable[[str], tuple[int, bytes, int | None]] = _read_public,
) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for name, path in ENDPOINTS:
        started = perf_counter_ns()
        try:
            status, body, remaining = fetch(path)
        except (OSError, ValueError, TimeoutError, URLError):
            observations.append({
                "endpoint": name, "status": "READ_UNAVAILABLE",
                "http_status": None, "elapsed_ms": round((perf_counter_ns() - started) / 1e6, 3),
                "body_bytes": None, "items": None,
                "rate_limit_remaining": None,
            })
            continue
        elapsed = round((perf_counter_ns() - started) / 1e6, 3)
        reason = "READ_OK" if status == 200 else (
            "RATE_LIMITED" if status in (403, 429) else "HTTP_UNAVAILABLE"
        )
        count: int | None = None
        if reason == "READ_OK":
            if len(body) > MAX_BYTES:
                reason = "RESPONSE_LIMIT"
            else:
                try:
                    parsed = json.loads(body)
                    if name == "issue_metadata":
                        if type(parsed) is not dict or parsed.get("number") != 847:
                            reason = "INVALID_PUBLIC_RESPONSE"
                        else:
                            count = 1
                    elif type(parsed) is not list or len(parsed) > 100:
                        reason = "INVALID_PUBLIC_RESPONSE"
                    else:
                        count = len(parsed)
                except (ValueError, TypeError, UnicodeError):
                    reason = "INVALID_PUBLIC_RESPONSE"
        observations.append({
            "endpoint": name, "status": reason, "http_status": status,
            "elapsed_ms": elapsed, "body_bytes": len(body),
            "items": count,
            "rate_limit_remaining": remaining,
        })
    return {
        "schema_version": "kaep.public-get-profile.v0.1",
        "kind": "PUBLIC_GET_ONLY_NETWORK_OBSERVATION",
        "status": "BOUNDED_PUBLIC_READ" if all(
            x["status"] == "READ_OK" for x in observations
        ) else "PARTIAL_UNKNOWN",
        "no_source_authority": True,
        "recipient_pickup_proven": False,
        "read_only": True,
        "endpoint_count": len(observations),
        "observations": observations,
        "timing_scope": "github_hosted_runner_unauthenticated_public_GET",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="Explicitly allow three public unauthenticated GETs")
    args = parser.parse_args(argv)
    if not args.live:
        print("KAEP_PUBLIC_GET_PROFILE=OPT_IN_REQUIRED")
        return 2
    result = profile()
    print("KAEP_PUBLIC_GET_PROFILE=" + json.dumps(
        result, sort_keys=True, separators=(",", ":"),
    ), flush=True)
    return 0 if result["status"] == "BOUNDED_PUBLIC_READ" else 2


if __name__ == "__main__":
    sys.exit(main())
