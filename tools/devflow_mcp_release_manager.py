"""Verified, rollbackable local Codex Devflow MCP releases (Issue #1111).

The command runs only by explicit invocation or a separate scheduled task.
The MCP launcher itself never fetches Git or runs validation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


REPOSITORY = "kinoko34077/devflow"
ORIGIN_URLS = {
    "https://github.com/kinoko34077/devflow",
    "https://github.com/kinoko34077/devflow.git",
    "git@github.com:kinoko34077/devflow.git",
}
_SHA = re.compile(r"[0-9a-f]{40}\Z")
REQUIRED_CHECKS = frozenset({"verify", "mcp-stdio-python311"})
EXPECTED_TOOLS = 16


class ReleaseError(Exception):
    """Safe, credential-free error for the operator or scheduler."""


def release_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "KiNoTch" / "devflow-mcp-releases"


def validate_sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ReleaseError("invalid release SHA")
    return value


def read_marker(root: Path) -> dict | None:
    marker = root / "active.json"
    if not marker.exists():
        return None
    if marker.stat().st_size > 4096:
        raise ReleaseError("invalid active release marker")
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ReleaseError("invalid active release marker") from error
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ReleaseError("invalid active release marker")
    validate_sha(data.get("sha"))
    previous = data.get("previous_sha")
    if previous is not None:
        validate_sha(previous)
    return data


def write_marker(root: Path, sha: str, previous_sha: str | None) -> None:
    """Atomic same-directory state change; marker contains no credentials."""
    validate_sha(sha)
    if previous_sha is not None:
        validate_sha(previous_sha)
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "active.json"
    fd, name = tempfile.mkstemp(prefix=".active-", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(
                {"schema_version": 1, "sha": sha, "previous_sha": previous_sha},
                out, sort_keys=True,
            )
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, marker)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def run(args: list[str], *, timeout: int = 60, cwd: Path | None = None) -> str:
    try:
        p = subprocess.run(
            args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReleaseError("required local Git or GitHub operation unavailable") from exc
    if p.returncode != 0:
        raise ReleaseError("required local Git or GitHub operation failed")
    return p.stdout.strip()


def gh_json(gh: Path, endpoint: str) -> object:
    raw = run([str(gh), "api", endpoint], timeout=30)
    try:
        return json.loads(raw)
    except ValueError as error:
        raise ReleaseError("invalid GitHub API response") from error


def github_gate(gh: Path, sha: str) -> None:
    """Require actual successful main-SHA PR-gate jobs, not a vague CI label."""
    validate_sha(sha)
    packet = gh_json(gh, f"repos/{REPOSITORY}/commits/{sha}/check-runs?per_page=100")
    if not isinstance(packet, dict) or type(packet.get("total_count")) is not int:
        raise ReleaseError("GitHub check evidence missing")
    checks = packet.get("check_runs")
    if not isinstance(checks, list) or len(checks) < packet["total_count"]:
        raise ReleaseError("GitHub check evidence incomplete")
    succeeded = {
        c["name"] for c in checks
        if isinstance(c, dict)
        and c.get("name") in REQUIRED_CHECKS
        and c.get("status") == "completed"
        and c.get("conclusion") == "success"
        and isinstance(c.get("app"), dict)
        and c["app"].get("slug") == "github-actions"
        and isinstance(c.get("head_sha"), str)
        and c["head_sha"] == sha
    }
    if succeeded != REQUIRED_CHECKS:
        raise ReleaseError("required main-commit verification has not succeeded")


def trusted_latest(repo: Path, gh: Path) -> str:
    remote = run(["git", "-C", str(repo), "config", "--get", "remote.origin.url"])
    if remote not in ORIGIN_URLS:
        raise ReleaseError("Git source is not the trusted Devflow origin")
    branch = gh_json(gh, f"repos/{REPOSITORY}/branches/main")
    try:
        github_sha = validate_sha(branch["commit"]["sha"])
    except (KeyError, TypeError) as error:
        raise ReleaseError("GitHub main SHA unavailable") from error
    # Never update the working tree (or its .venv). Only move origin/main.
    run(
        ["git", "-C", str(repo), "fetch", "--no-tags",
         "origin", "+refs/heads/main:refs/remotes/origin/main"],
        timeout=80,
    )
    local_sha = run(["git", "-C", str(repo), "rev-parse", "refs/remotes/origin/main"])
    if local_sha != github_sha:
        raise ReleaseError("GitHub main changed during source fetch; retry later")
    github_gate(gh, github_sha)
    return github_sha


def source_archive(repo: Path, sha: str, destination: Path) -> None:
    """Export a commit without mutating any checked-out source or .venv."""
    validate_sha(sha)
    package = destination.parent / "source.zip"
    run(
        ["git", "-C", str(repo), "archive", "--format=zip",
         "--output=" + str(package), sha], timeout=90,
    )
    with zipfile.ZipFile(package) as archive:
        for entry in archive.infolist():
            posix = PurePosixPath(entry.filename)
            if posix.is_absolute() or ".." in posix.parts:
                raise ReleaseError("invalid source archive path")
            if ((entry.external_attr >> 16) & 0o170000) == 0o120000:
                raise ReleaseError("source archive contains unsupported symbolic link")
        archive.extractall(destination)


def run_unittests(python: Path, source: Path) -> None:
    # The archive has no Git metadata. Run all repository Python unittest tests.
    try:
        p = subprocess.run(
            [str(python), "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
            cwd=source, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=240, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ReleaseError("local Python unit suite could not run") from error
    if p.returncode != 0:
        raise ReleaseError("local Python unit suite failed; release not activated")


def _compatible_schema(schema: object) -> object:
    """Descriptions/titles may change; tool names and callable contracts may not."""
    if isinstance(schema, dict):
        return {
            k: _compatible_schema(v)
            for k, v in schema.items()
            if k not in {"title", "description", "examples"}
        }
    if isinstance(schema, list):
        return [_compatible_schema(v) for v in schema]
    return schema


async def _stdio_test(
    python: Path, script: Path, token: str, *,
    full: bool,
) -> dict[str, object]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = os.environ.copy()
    env["DEVFLOW_GITHUB_TOKEN"] = token
    server = StdioServerParameters(command=str(python), args=[str(script)], env=env)
    with open(os.devnull, "w") as log:
        async with stdio_client(server, errlog=log) as (rd, wr):
            async with ClientSession(rd, wr) as client:
                await asyncio.wait_for(client.initialize(), timeout=35)
                listing = await asyncio.wait_for(client.list_tools(), timeout=15)
                catalog = {
                    t.name: _compatible_schema(t.input_schema)
                    for t in listing.tools
                }
                if len(catalog) != EXPECTED_TOOLS:
                    raise ReleaseError("MCP tool count changed; manual compatibility review required")
                if full:
                    for name in ("bootstrap_repository", "get_human_portfolio"):
                        if name not in catalog:
                            raise ReleaseError("required read-only MCP tool missing")
                        result = await asyncio.wait_for(
                            client.call_tool(name, {"repository": REPOSITORY}),
                            timeout=75,
                        )
                        if result.is_error:
                            raise ReleaseError("read-only MCP smoke call failed")
                return catalog


def smoke(python: Path, gh: Path, script: Path, *, full: bool) -> dict:
    token = run([str(gh), "auth", "token", "--hostname", "github.com"], timeout=12)
    if not token or any(ch.isspace() for ch in token):
        raise ReleaseError("existing GitHub CLI authentication is unavailable")
    try:
        return asyncio.run(_stdio_test(python, script, token, full=full))
    except (ReleaseError, KeyboardInterrupt):
        raise
    except Exception as error:
        raise ReleaseError("MCP initialize, catalog, or smoke test failed") from error
    finally:
        token = ""


def release_script(root: Path, sha: str) -> Path:
    validate_sha(sha)
    script = root / "releases" / sha / "tools" / "devflow_mcp.py"
    if not script.is_file() or not script.resolve().is_relative_to(root.resolve()):
        raise ReleaseError("selected release is missing or invalid")
    return script


def promote(
    *,
    repo: Path, python: Path, gh: Path, root: Path, fallback: Path,
) -> str:
    root.mkdir(parents=True, exist_ok=True)
    state = read_marker(root)
    latest = trusted_latest(repo, gh)
    if state is not None and state["sha"] == latest:
        return "UP_TO_DATE " + latest
    if state is not None:
        # Refuse to promote history rewrites or unrelated commits.
        run(["git", "-C", str(repo), "merge-base", "--is-ancestor",
             state["sha"], latest], timeout=15)
    # For a first activation, compare against the existing configured catalog.
    old_script = release_script(root, state["sha"]) if state else fallback
    if not old_script.is_file():
        raise ReleaseError("current MCP fallback is missing")
    previous_catalog = smoke(python, gh, old_script, full=False)
    target = root / "releases" / latest
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with tempfile.TemporaryDirectory(prefix=".candidate-", dir=root) as tmp:
            stage = Path(tmp) / latest
            stage.mkdir()
            source_archive(repo, latest, stage)
            run_unittests(python, stage)
            candidate = stage / "tools" / "devflow_mcp.py"
            if not candidate.is_file():
                raise ReleaseError("candidate MCP entrypoint is missing")
            new_catalog = smoke(python, gh, candidate, full=True)
            if new_catalog != previous_catalog:
                raise ReleaseError("MCP callable schema changed; manual review required")
            os.replace(stage, target)
    else:
        new_catalog = smoke(python, gh, release_script(root, latest), full=True)
        if new_catalog != previous_catalog:
            raise ReleaseError("MCP callable schema changed; manual review required")
    write_marker(root, latest, state["sha"] if state else None)
    return "ACTIVATED " + latest


def rollback(root: Path, fallback: Path) -> str:
    state = read_marker(root)
    if state is None:
        return "ALREADY_LEGACY"
    previous = state["previous_sha"]
    if previous is None:
        if not fallback.is_file():
            raise ReleaseError("original fallback MCP is unavailable")
        (root / "active.json").unlink()
        return "ROLLED_BACK_TO_LEGACY"
    release_script(root, previous)
    write_marker(root, previous, state["sha"])
    return "ROLLED_BACK " + previous


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "status", "rollback"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--gh", type=Path, required=True)
    parser.add_argument("--fallback", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root or release_root()
    try:
        if args.action == "status":
            state = read_marker(root)
            outcome = "ACTIVE " + state["sha"] if state else "LEGACY"
        elif args.action == "rollback":
            outcome = rollback(root, args.fallback)
        else:
            outcome = promote(
                repo=args.repo, python=args.python, gh=args.gh,
                root=root, fallback=args.fallback,
            )
        print(outcome, flush=True)
        return 0
    except ReleaseError as error:
        print("BLOCKED " + str(error), file=sys.stderr, flush=True)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
