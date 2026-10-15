"""Read-only owner-PC Codex CLI route-A capability probe.

No task submission, GitHub mutations, credential inspection, task body output,
or Cloud environment availability claim. Run only on an authorized owner host.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

_VERSION = re.compile(r"codex-cli [0-9]+\.[0-9]+\.[0-9]+(?:[-+][a-zA-Z0-9.-]+)?\Z")
_MAX_OUTPUT = 65536


@dataclass(frozen=True)
class ReadOnlyProbe:
    status: str
    cli_version: str | None
    task_list_accessible: bool
    task_count: int | None
    environment_verified: bool = False
    dispatch_verified: bool = False


def _call(command: list[str], cwd: Path, timeout_seconds: float) -> tuple[str, str]:
    """Only locally constructed fixed argv; no shell or remote task side effect."""
    try:
        outcome = subprocess.run(
            command, cwd=str(cwd), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_seconds,
            shell=False, check=False,
        )
    except subprocess.TimeoutExpired:
        return "TIMEOUT", ""
    except (OSError, ValueError):
        return "UNAVAILABLE", ""
    if outcome.returncode != 0:
        return "CLI_FAILURE", ""
    if len(outcome.stdout) > _MAX_OUTPUT:
        return "OVERSIZED_OUTPUT", ""
    return "OK", outcome.stdout


def probe(cli_path: str, checkout_path: str, *, timeout_seconds: float = 15) -> ReadOnlyProbe:
    """Version + task *listing* proof; never an environment or dispatch proof.

    cli_path and checkout_path must be operator-supplied trusted local paths,
    not Issue-body or PR input. No arbitrary commands or credentials printed.
    """
    cli = Path(cli_path)
    checkout = Path(checkout_path)
    if not cli.is_file() or not checkout.is_dir() or not (0 < timeout_seconds <= 30):
        return ReadOnlyProbe("INVALID_LOCAL_TARGET", None, False, None)
    version_status, raw_version = _call([str(cli), "--version"], checkout, timeout_seconds)
    if version_status != "OK":
        return ReadOnlyProbe(version_status, None, False, None)
    ver = raw_version.strip()
    if not _VERSION.fullmatch(ver):
        return ReadOnlyProbe("UNRECOGNIZED_VERSION", None, False, None)
    list_status, raw_list = _call(
        [str(cli), "cloud", "list", "--json"], checkout, timeout_seconds,
    )
    if list_status != "OK":
        return ReadOnlyProbe(list_status, ver, False, None)
    try:
        data = json.loads(raw_list)
    except (ValueError, TypeError):
        return ReadOnlyProbe("INVALID_TASK_LIST", ver, False, None)
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        return ReadOnlyProbe("INVALID_TASK_LIST", ver, False, None)
    return ReadOnlyProbe("TASK_LIST_ACCESSIBLE_ONLY", ver, True, len(data["tasks"]))


def main() -> int:
    parser = argparse.ArgumentParser(description="No-task-submit Codex Cloud route-A preflight")
    parser.add_argument("--cli", required=True, help="Operator-verified local codex CLI path")
    parser.add_argument("--checkout", required=True, help="Operator-verified local repository path")
    args = parser.parse_args()
    result = probe(args.cli, args.checkout)
    print(json.dumps(asdict(result), sort_keys=True))
    return 0 if result.task_list_accessible else 1


if __name__ == "__main__":
    raise SystemExit(main())
