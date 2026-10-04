#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import repository_projection_cache_producer as producer  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a bounded Repository Projection cache for one managed repository."
    )
    parser.add_argument("--repository", required=True)
    parser.add_argument("--control", required=True, type=int)
    parser.add_argument("--read-token-env", default="MAINTENANCE_AUDIT_TOKEN")
    parser.add_argument("--write-token-env", default="GITHUB_TOKEN")
    parser.add_argument("--output", default="repository-projection-cache-result.json")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    del args, producer
    raise SystemExit("repository projection cache producer not implemented")


if __name__ == "__main__":
    raise SystemExit(main())
