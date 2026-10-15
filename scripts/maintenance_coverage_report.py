#!/usr/bin/env python3
"""GET-only SMC coverage report for explicitly selected accepted PILOT repos."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.maintenance_github import (  # noqa: E402
    GitHubReadTransport, _catalog_bundle, build_maintenance_fingerprint,
)
from tools.maintenance_coverage_github import (  # noqa: E402
    collect_repository_coverage,
)
from tools.maintenance_coverage_report import (  # noqa: E402
    build_coverage_report, render_coverage_markdown,
)
from tools.maintenance_coverage_html import render_coverage_html  # noqa: E402

ACCEPTED_PILOTS = frozenset({
    "kinoko34077/devflow",
    "kinoko34077/execution-coordinator",
    "kinoko34077/kinotch-repository-base",
})


def _target(value: str) -> tuple[str, int]:
    repo, sep, number = value.rpartition("#")
    if not sep or repo not in ACCEPTED_PILOTS or not number.isdecimal() or int(number) < 1:
        raise ValueError("select an explicitly accepted PILOT repository#Ledger-Issue")
    return repo, int(number)


def build_live_report(transport: GitHubReadTransport, targets: list[str]) -> dict[str, object]:
    if not targets:
        raise ValueError("at least one repo#Ledger-Issue is required")
    pairs = [_target(value) for value in targets]
    if len({repo for repo, _ in pairs}) != len(pairs):
        raise ValueError("duplicate PILOT repository")
    snapshots = []
    for repo, issue in pairs:
        # The baseline and both source identities must remain stable across
        # the collector's additional native reads; do not mask source races.
        before = _catalog_bundle(transport, repo)
        _baseline, _catalog, slots, digest, head, baseline_file, repo_file = before
        fingerprint = build_maintenance_fingerprint(head, digest)
        fingerprints = {
            repo + "::" + slot.slot_id: (
                fingerprint if slot.external_freshness_class != "FAST"
                and slot.scope.kind != "external_system" else ""
            )
            for slot in slots
        }
        evidence = collect_repository_coverage(
            transport, repo, issue, current_fingerprints=fingerprints,
        )
        after = _catalog_bundle(transport, repo)
        if (
            head != after[4]
            or digest != after[3]
            or baseline_file.get("sha") != after[5].get("sha")
            or repo_file.get("sha") != after[6].get("sha")
            or evidence.catalog_blob_sha != repo_file.get("sha")
        ):
            raise ValueError("canonical source changed during coverage observation")
        snapshots.append(evidence)
    report = build_coverage_report(snapshots)
    report["observed_at"] = dt.datetime.now(dt.timezone.utc).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SMC PILOT coverage matrix")
    parser.add_argument("--repo-ledger", action="append", required=True,
                        help="Exact accepted owner/name#Issue (repeat, maximum 3)")
    parser.add_argument("--token-env", default="GITHUB_TOKEN",
                        help="Preconfigured native GitHub GET token env name")
    parser.add_argument("--format", choices=("markdown", "json", "html"), default="markdown")
    parser.add_argument("--output", help="Optional local output; no GitHub writes")
    args = parser.parse_args(argv)
    try:
        token = os.environ.get(args.token_env, "")
        if not token:
            raise ValueError("existing authorized token is unavailable")
        report = build_live_report(GitHubReadTransport(token), args.repo_ledger)
        if args.format == "json":
            output = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        elif args.format == "html":
            output = render_coverage_html(report)
        else:
            output = render_coverage_markdown(report)
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
        else:
            print(output, end="")
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        # Do not leak API token, comment bodies or private source in errors.
        print("SMC coverage source unavailable or invalid: "
              + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
