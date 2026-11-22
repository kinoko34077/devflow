"""固定GitHub Private CIジョブの実行元照合（読取専用）。

Invocation with a pre-existing read-capable token in the environment:
    python -m tools.private_ci_authenticated_job_cli \
      --repository OWNER/REPO --run-id N --job-id N --head 40-hex

No token, credential, billing setting, local storage or job is created.
Results can *never* authorize a fallback, month flag or Check conclusion.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os

from tools.private_ci_authenticated_job_read import observe_github_job_launch_once


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--job-id", required=True, type=int)
    parser.add_argument("--head", required=True)
    options = parser.parse_args(argv)
    # The owner is fixed for this managed-account installation; allowing
    # arbitrary GitHub usernames here would expand the read scope.
    account = "kinoko34077"
    token = os.environ.get("DEVFLOW_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print(json.dumps({
            "status": "HOLD",
            "action": "HOLD",
            "reason": "EXISTING_GITHUB_AUTH_UNAVAILABLE",
            "verified_for_dispatch": False,
        }))
        return 2

    observation = observe_github_job_launch_once(
        account, options.repository, options.run_id, options.job_id,
        options.head, datetime.now(timezone.utc), token,
    )
    # Never expose the receipt (contains the annotation) or the token.
    print(json.dumps({
        "status": observation.status,
        "action": observation.action,
        "reason": observation.reason,
        "requests_attempted": observation.requests_attempted,
        "verified_for_dispatch": observation.verified_for_dispatch,
    }, sort_keys=True))
    return 0 if observation.status == "PLAN_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
