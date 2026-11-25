"""Stable, read-only Codex Devflow MCP launcher.

Installed once at ~/.codex/bin/devflow_mcp_launcher.py; existing Codex
command and arguments remain unchanged. Never fetch or promote on launch.\nThe protected connection adapter replaces only verified local workers.
"""

from __future__ import annotations

import asyncio
import hashlib
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


def release_tree_digest(directory: Path) -> str:
    """全相対パスと全ファイルのバイトを検査する。リダイレクトは拒否。"""
    if (not directory.is_dir() or directory.is_symlink()
            or directory.resolve() != directory.parent.resolve() / directory.name):
        raise ValueError("release directory is missing or redirected")
    base = directory.resolve()
    digest = hashlib.sha256()
    entries = sorted(directory.rglob("*"), key=lambda p: p.relative_to(directory).as_posix())
    if not entries:
        raise ValueError("empty release directory")
    try:
        for entry in entries:
            relative = entry.relative_to(directory)
            name = relative.as_posix().encode("utf-8")
            if entry.is_symlink() or entry.resolve() != base.joinpath(*relative.parts):
                raise ValueError("release entry is redirected")
            if entry.is_dir():
                digest.update(b"D\0" + name + b"\0")
            elif entry.is_file():
                digest.update(b"F\0" + name + b"\0")
                size = entry.stat().st_size
                digest.update(size.to_bytes(8, "big"))
                read_size = 0
                with entry.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                        read_size += len(chunk)
                if read_size != size:
                    raise ValueError("release changed during integrity check")
            else:
                raise ValueError("unsupported release entry")
    except OSError as error:
        raise ValueError("release tree could not be checked") from error
    return digest.hexdigest()



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
    if not isinstance(state, dict) or state.get("schema_version") != 2:
        raise ValueError("invalid MCP release marker")
    sha = state.get("sha")
    if type(sha) is not str or not _SHA.fullmatch(sha):
        raise ValueError("invalid MCP release identifier")
    candidate = root / "releases" / sha / "tools" / "devflow_mcp.py"
    if not candidate.is_file():
        raise ValueError("selected MCP release is missing")
    expected = root.resolve() / "releases" / sha / "tools" / "devflow_mcp.py"
    if candidate.resolve() != expected:
        raise ValueError("selected MCP release is redirected")
    verified_digest = state.get("tree_sha256")
    if type(verified_digest) is not str or re.fullmatch(r"[0-9a-f]{64}", verified_digest) is None:
        raise ValueError("invalid verified release digest")
    if release_tree_digest(root / "releases" / sha) != verified_digest:
        raise ValueError("active release contents changed")
    return candidate


class AuthenticationUnavailable(RuntimeError):
    """Safe diagnostic; never include the gh response or environment."""


def selection_revision(root: Path) -> str:
    """Observe selection only, not the release contents, on ordinary calls."""
    marker = root / "active.json"
    try:
        with marker.open("rb") as stream:
            data = stream.read(4097)
    except FileNotFoundError:
        return "LEGACY"
    if len(data) > 4096:
        raise ValueError("invalid MCP release marker size")
    return hashlib.sha256(data).hexdigest()


def launch_parameters(gh_executable: str, fallback_script: str, *, root: Path):
    """Fixed host selector and original gh authentication, per worker launch."""
    # Import the protected, co-installed adapter, never code from the candidate.
    if __package__:
        from .devflow_mcp_connection import Launch
    else:
        from devflow_mcp_connection import Launch
    from mcp import StdioServerParameters

    before = selection_revision(root)
    script = selected_script(fallback_script, root=root)
    if selection_revision(root) != before:
        raise ValueError("release selection changed")
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
        raise AuthenticationUnavailable(AUTH_FAILURE) from None
    token = (result.stdout or "").strip()
    if result.returncode != 0 or not token or any(c.isspace() for c in token):
        raise AuthenticationUnavailable(AUTH_FAILURE)
    if selection_revision(root) != before:
        raise ValueError("release selection changed")
    child_env = os.environ.copy()
    # Do not use the old registered checkout as the candidate import root.
    child_env["PYTHONPATH"] = str(script.resolve().parent.parent)
    child_env["DEVFLOW_GITHUB_TOKEN"] = token
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    version = "LEGACY" if before == "LEGACY" else script.parent.parent.name
    return Launch(version, StdioServerParameters(
        command=sys.executable, args=[str(script)], env=child_env,
    ))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        _diagnose("devflow MCP launcher: invalid local configuration; server not started.")
        return 78
    gh_executable, fallback_script = args
    root = release_root()
    try:
        # The installer must co-install these fixed modules before replacing
        # the launcher. Never import the connection adapter from a release.
        if __package__:
            from .devflow_mcp_connection import serve_connection
            from .devflow_mcp_catalog import REQUIRED_CALLS
        else:
            # A registered legacy PYTHONPATH must not influence the protected
            # front or SDK. The one-time installer adds -I before this script.
            if not sys.flags.isolated:
                raise ValueError("protected launcher requires isolated Python")
            directory = Path(__file__).resolve().parent
            for name in ("devflow_mcp_connection.py", "devflow_mcp_catalog.py",
                         "devflow_mcp_release_manager.py"):
                module = directory / name
                if not module.is_file() or module.resolve() != module:
                    raise ValueError("missing or redirected protected adapter")
            sys.path.insert(0, str(directory))
            from devflow_mcp_connection import serve_connection
            from devflow_mcp_catalog import REQUIRED_CALLS
        asyncio.run(serve_connection(
            lambda: selection_revision(root),
            lambda: launch_parameters(gh_executable, fallback_script, root=root),
            smoke_name="bootstrap_repository",
            smoke_arguments=dict(REQUIRED_CALLS["bootstrap_repository"]),
        ))
        return 0
    except AuthenticationUnavailable:
        _diagnose(AUTH_FAILURE)
        return 78
    except Exception:
        _diagnose("devflow MCP launcher: protected connection could not be established.")
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
