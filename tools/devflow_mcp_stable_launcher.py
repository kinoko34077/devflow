"""Stable, read-only Codex Devflow MCP launcher.

Installed once at ~/.codex/bin/devflow_mcp_launcher.py; existing Codex
command and arguments remain unchanged. Never fetch, update, or test on launch.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys


AUTH_TIMEOUT_SECONDS = 8
_SHA = re.compile(r"[0-9a-f]{40}\Z")
AUTH_FAILURE = (
    "devflow MCP launcher: GitHub CLI authentication unavailable; "
    "the MCP server was not started."
)


def _diagnose(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def release_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "KiNoTch" / "devflow-mcp-releases"


def selected_script(fallback_script: str, *, root: Path | None = None) -> Path:
    """Select exactly one complete immutable release or the original fallback.

    Missing marker means "not enabled"; corrupt marker fails closed, rather
    than silently executing an unexpected source or following an unsafe path.
    """
    root = root or release_root()
    marker = root / "active.json"
    if not marker.exists():
        fallback = Path(fallback_script)
        if not fallback.is_file():
            raise ValueError("legacy MCP server path not found")
        return fallback
    if marker.stat().st_size > 4096:
        raise ValueError("invalid MCP release marker size")
    state = json.loads(marker.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise ValueError("invalid MCP release marker")
    sha = state.get("sha")
    if type(sha) is not str or not _SHA.fullmatch(sha):
        raise ValueError("invalid MCP release identifier")
    candidate = root / "releases" / sha / "tools" / "devflow_mcp.py"
    if not candidate.is_file():
        raise ValueError("selected MCP release is missing")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("selected MCP release escapes trusted directory")
    return candidate


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        _diagnose("devflow MCP launcher: invalid local configuration; server not started.")
        return 78
    gh_executable, fallback_script = args
    try:
        script = selected_script(fallback_script)
    except (OSError, ValueError, json.JSONDecodeError, UnicodeError):
        _diagnose("devflow MCP launcher: invalid active release; server not started.")
        return 78
    try:
        result = subprocess.run(
            [gh_executable, "auth", "token", "--hostname", "github.com"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=AUTH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        _diagnose(AUTH_FAILURE)
        return 78
    token = (result.stdout or "").strip()
    if result.returncode != 0 or not token or any(c.isspace() for c in token):
        _diagnose(AUTH_FAILURE)
        return 78
    child_env = os.environ.copy()
    child_env["DEVFLOW_GITHUB_TOKEN"] = token
    token = None
    try:
        child = subprocess.Popen([sys.executable, str(script)], env=child_env)
        child_env.pop("DEVFLOW_GITHUB_TOKEN", None)
        return child.wait()
    except OSError:
        _diagnose("devflow MCP launcher: MCP server process could not be started.")
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
