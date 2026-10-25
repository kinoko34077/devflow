#!/usr/bin/env python3
"""Run existing trusted cache validators against every managed Control (GET only)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import devflow_mcp_core  # noqa: E402
from tools import projection_fleet_health  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--read-token-env", default="MAINTENANCE_AUDIT_TOKEN")
    args = parser.parse_args(argv)
    token = os.environ.get(args.read_token_env, "")
    if not token:
        print(json.dumps({"status": "UNKNOWN", "reason": "READ_TOKEN_UNAVAILABLE"}))
        return 1
    service = devflow_mcp_core.DevflowService(
        devflow_mcp_core.GitHubReader(token=token)
    )
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result = projection_fleet_health.assess_fleet(service, now=now)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result["status"] == "CURRENT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
