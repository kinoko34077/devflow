#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import devflow_mcp_core  # noqa: E402
from tools import maintenance_github  # noqa: E402
from tools import repository_projection_cache_producer as producer  # noqa: E402


class _IssueWriter(maintenance_github.GitHubReadTransport):
    def update_issue_body(
        self,
        repository: str,
        number: int,
        body: str,
    ) -> bool:
        payload = json.dumps({"body": body}).encode("utf-8")
        request = urllib.request.Request(
            self._url(f"/repos/{repository}/issues/{number}"),
            data=payload,
            method="PATCH",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "kinotch-devflow-repository-projection-cache",
            },
        )
        try:
            with self._opener(
                request,
                timeout=self._timeout,
            ) as response:
                raw = response.read()
                if not raw:
                    return True
                value = json.loads(raw.decode("utf-8"))
                return isinstance(value, dict)
        except urllib.error.HTTPError as exc:
            raise maintenance_github.GitHubReadError(
                f"GitHub bounded cache update failed with HTTP {exc.code}"
            ) from None
        except urllib.error.URLError as exc:
            reason = str(exc.reason).replace(self._token, "[REDACTED]")
            raise maintenance_github.GitHubReadError(
                f"GitHub bounded cache update failed: {reason}"
            ) from None


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _token(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise producer.RepositoryProjectionCacheProducerError(
            f"required token environment variable is missing: {name}"
        )
    return value


def _write_result(value: dict[str, object], path: str) -> None:
    Path(path).write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a bounded Repository Projection cache for one managed repository."
    )
    parser.add_argument("--repository")
    parser.add_argument("--control", type=int)
    parser.add_argument("--fleet", action="store_true")
    parser.add_argument("--read-token-env", default="MAINTENANCE_AUDIT_TOKEN")
    parser.add_argument("--write-token-env", default="GITHUB_TOKEN")
    parser.add_argument("--output", default="repository-projection-cache-result.json")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    try:
        read_token = _token(args.read_token_env)
        service = devflow_mcp_core.DevflowService(
            devflow_mcp_core.GitHubReader(token=read_token)
        )
        generated_at = _utc_now()
        writer = None
        if args.apply:
            write_token = _token(args.write_token_env)
            writer = _IssueWriter(write_token)

        if args.fleet:
            if args.repository is not None or args.control is not None:
                raise producer.RepositoryProjectionCacheProducerError(
                    "--fleet cannot be combined with --repository/--control"
                )
            result = producer.run_fleet(
                service,
                writer,
                generated_at=generated_at,
                apply=args.apply,
            )
        else:
            if not args.repository or args.control is None:
                raise producer.RepositoryProjectionCacheProducerError(
                    "targeted mode requires --repository and --control"
                )
            plan = producer.prepare_target(
                service,
                args.repository,
                args.control,
                generated_at=generated_at,
            )

            if args.apply:
                result = producer.apply_plan(
                    writer,
                    plan,
                )
            else:
                result = {
                    "status": "PREVIEW",
                    "repository": plan.repository,
                    "control_issue_number": plan.control_issue_number,
                    "generation_id": plan.generation_id,
                    "human_portfolio_generation_id": plan.human_portfolio_generation_id,
                    "human_portfolio_complete": plan.human_portfolio_complete,
                    "source_status": plan.source_status,
                    "coverage_status": plan.coverage_status,
                    "changed": plan.changed,
                    "expected_body_sha256": plan.expected_body_sha256,
                }

        _write_result(result, args.output)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (
        producer.RepositoryProjectionCacheProducerError,
        devflow_mcp_core.DevflowMCPError,
        maintenance_github.GitHubReadError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
