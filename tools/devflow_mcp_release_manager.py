"""Verified, rollbackable local Codex Devflow MCP releases (Issue #1111).

The command runs only by explicit invocation or the shared local AutoRunner.
The MCP launcher itself never fetches Git or runs validation.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import asyncio
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import tomllib
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


def validate_digest(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ReleaseError("invalid release tree digest")
    return value


def release_tree_digest(directory: Path) -> str:
    """全相対パスと全ファイルのバイトを検査する。リダイレクトは拒否。"""
    if (not directory.is_dir() or directory.is_symlink()
            or directory.resolve() != directory.parent.resolve() / directory.name):
        raise ReleaseError("release directory is missing or redirected")
    base = directory.resolve()
    digest = hashlib.sha256()
    entries = sorted(directory.rglob("*"), key=lambda p: p.relative_to(directory).as_posix())
    if not entries:
        raise ReleaseError("empty release directory")
    try:
        for entry in entries:
            relative = entry.relative_to(directory)
            name = relative.as_posix().encode("utf-8")
            if entry.is_symlink() or entry.resolve() != base.joinpath(*relative.parts):
                raise ReleaseError("release entry is redirected")
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
                    raise ReleaseError("release changed during integrity check")
            else:
                raise ReleaseError("unsupported release entry")
    except OSError as error:
        raise ReleaseError("release tree could not be checked") from error
    return digest.hexdigest()


def require_integrity(root: Path, sha: str, expected_digest: str) -> None:
    validate_digest(expected_digest)
    if release_tree_digest(root / "releases" / sha) != expected_digest:
        raise ReleaseError("release contents differ from verified bytes")


def read_marker(root: Path) -> dict | None:
    marker = root / "active.json"
    if not marker.exists():
        return None
    try:
        if marker.stat().st_size > 4096:
            raise ReleaseError("invalid active release marker")
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ReleaseError("invalid active release marker") from error
    if not isinstance(data, dict) or data.get("schema_version") != 2:
        raise ReleaseError("invalid active release marker")
    validate_sha(data.get("sha"))
    validate_digest(data.get("tree_sha256"))
    previous = data.get("previous_sha")
    previous_digest = data.get("previous_tree_sha256")
    if previous is None:
        if previous_digest is not None:
            raise ReleaseError("invalid previous release marker")
    else:
        validate_sha(previous)
        validate_digest(previous_digest)
    return data


def write_marker(
    root: Path, sha: str, previous_sha: str | None, *,
    tree_sha256: str, previous_tree_sha256: str | None = None,
) -> None:
    """検証済みのdigestだけを原子的に書き込む。秘密情報は含まない。"""
    validate_sha(sha)
    validate_digest(tree_sha256)
    if previous_sha is not None:
        validate_sha(previous_sha)
        validate_digest(previous_tree_sha256)
    elif previous_tree_sha256 is not None:
        raise ReleaseError("unexpected previous release digest")
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "active.json"
    fd, name = tempfile.mkstemp(prefix=".active-", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(
                {"schema_version": 2, "sha": sha, "previous_sha": previous_sha,
                 "tree_sha256": tree_sha256,
                 "previous_tree_sha256": previous_tree_sha256},
                out, sort_keys=True,
            )
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, marker)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def updates_held(root: Path) -> bool:
    """停止ファイルの存在だけで判定。読めない状態を再開扱いしない。"""
    try:
        (root / "updates.hold").lstat()
    except FileNotFoundError:
        return False
    return True


def hold_updates(root: Path) -> None:
    # rollbackより先に永続化する。途中停止した空ファイルも停止扱い。
    try:
        with (root / "updates.hold").open("xb") as stream:
            stream.write(b"rollback hold\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        pass


def selection_label(state: dict | None) -> str:
    return "ACTIVE " + state["sha"] if state else "LEGACY"


@contextmanager
def release_lock(root: Path):
    """OS側の短命な排他ロック。クラッシュ後のstale lockを残さない。"""
    root.mkdir(parents=True, exist_ok=True)
    try:
        with (root / ".manager.lock").open("a+b") as handle:
            if os.name == "nt":
                import msvcrt
                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as error:
                    raise ReleaseError("another release manager is active") from error
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as error:
                    raise ReleaseError("another release manager is active") from error
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as error:
        raise ReleaseError("release manager lock unavailable") from error


def install_verified_release(root: Path, sha: str, stage: Path, digest: str) -> None:
    """Reuse identical bytes in place; never move an existing release directory."""
    validate_sha(sha)
    validate_digest(digest)
    target = root / "releases" / sha
    try:
        target.lstat()
    except FileNotFoundError:
        try:
            os.replace(stage, target)
        except OSError as error:
            raise ReleaseError("verified release could not be installed") from error
    else:
        # A previously selected SHA can still serve an in-flight process after
        # rollback, even when active.json is absent. Never rename/overwrite it.
        # Only the newly staged source was executed; compare the retained bytes.
        require_integrity(root, sha, digest)


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
    """Verify the existing Required PR gate's exact main push and its jobs."""
    validate_sha(sha)
    workflow = ".github/workflows/project-sync-tests.yml"
    packet = gh_json(
        gh, f"repos/{REPOSITORY}/actions/workflows/project-sync-tests.yml/runs"
        f"?head_sha={sha}&event=push&branch=main&per_page=100",
    )
    if (not isinstance(packet, dict) or type(packet.get("total_count")) is not int
            or packet["total_count"] != 1
            or not isinstance(packet.get("workflow_runs"), list)
            or len(packet["workflow_runs"]) != 1):
        raise ReleaseError("unique required main-push workflow evidence unavailable")
    record = packet["workflow_runs"][0]
    if (not isinstance(record, dict)
            or record.get("path") != workflow
            or record.get("head_sha") != sha
            or record.get("head_branch") != "main"
            or record.get("event") != "push"
            or record.get("status") != "completed"
            or record.get("conclusion") != "success"
            or type(record.get("id")) is not int or record["id"] <= 0
            or type(record.get("run_attempt")) is not int or record["run_attempt"] <= 0):
        raise ReleaseError("required main-push workflow has not succeeded")
    run_id = record["id"]
    packet = gh_json(
        gh, f"repos/{REPOSITORY}/actions/runs/{run_id}/jobs"
        "?filter=latest&per_page=100",
    )
    if (not isinstance(packet, dict) or type(packet.get("total_count")) is not int
            or not isinstance(packet.get("jobs"), list)
            or len(packet["jobs"]) != packet["total_count"]):
        raise ReleaseError("required workflow job evidence incomplete")
    seen = set()
    for job in packet["jobs"]:
        if not isinstance(job, dict) or not isinstance(job.get("name"), str):
            raise ReleaseError("invalid required workflow job evidence")
        name = job["name"]
        if name not in REQUIRED_CHECKS:
            continue
        if (name in seen or job.get("head_sha") != sha
                or type(job.get("run_id")) is not int or job["run_id"] != run_id
                or type(job.get("run_attempt")) is not int
                or not 1 <= job["run_attempt"] <= record["run_attempt"]
                or job.get("status") != "completed"
                or job.get("conclusion") != "success"):
            raise ReleaseError("required main-commit verification has not succeeded")
        seen.add(name)
    if seen != REQUIRED_CHECKS:
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
    # Required GitHub CI already runs the entire suite at this exact SHA.
    # A Windows git-archive-only full-suite attempt exceeded 120 seconds;
    # keep the local preflight bounded to changed/consumer contract surfaces.
    suites = (
        "tests.test_devflow_mcp_release_manager",
        "tests.test_human_portfolio",
        "tests.test_devflow_mcp_core",
    )
    try:
        p = subprocess.run(
            [str(python), "-m", "unittest", *suites],
            cwd=source, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=100, check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ReleaseError("local Python unit suite could not run") from error
    if p.returncode != 0:
        raise ReleaseError("local Python unit suite failed; release not activated")


_SCHEMA_MAPS = frozenset({
    "properties", "patternProperties", "$defs", "definitions", "dependentSchemas",
})
_SCHEMA_LISTS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_SCHEMA_CHILDREN = frozenset({
    "items", "additionalProperties", "unevaluatedProperties", "contains",
    "not", "if", "then", "else", "propertyNames",
})


def _compatible_schema(schema: object) -> object:
    """Ignore only schema-node annotations, not property names/literal values.

    Do not descend into const, enum, default, examples, or unknown extension
    values: those may contain data keys named "title" or "description".
    """
    if not isinstance(schema, dict):
        return schema
    normalized = {}
    for key, value in schema.items():
        if key in {"title", "description", "examples"}:
            continue
        if key in _SCHEMA_MAPS and isinstance(value, dict):
            normalized[key] = {
                name: _compatible_schema(child)
                for name, child in value.items()
            }
        elif key in _SCHEMA_LISTS and isinstance(value, list):
            normalized[key] = [_compatible_schema(child) for child in value]
        elif key in _SCHEMA_CHILDREN and isinstance(value, (dict, list)):
            normalized[key] = (
                [_compatible_schema(child) for child in value]
                if isinstance(value, list)
                else _compatible_schema(value)
            )
        else:
            normalized[key] = value
    return normalized


def registered_mcp_env(python: Path, fallback: Path) -> dict[str, str]:
    """Reproduce exactly the existing registered Codex MCP runtime env."""
    config = Path.home() / ".codex" / "config.toml"
    try:
        raw = tomllib.loads(config.read_text(encoding="utf-8-sig"))
        server = raw["mcp_servers"]["kinotch_devflow"]
        values = server.get("env", {})
        argv = server["args"]
        if (type(argv) is not list or len(argv) != 3
                or Path(argv[2]).resolve() != fallback.resolve()
                or Path(server["command"]).resolve() != python.resolve()):
            raise ReleaseError("registered Codex MCP launch paths have changed")
        if not isinstance(values, dict) or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in values.items()
        ):
            raise ReleaseError("invalid registered MCP environment")
    except (OSError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError) as error:
        raise ReleaseError("registered Codex MCP settings unavailable") from error
    return values


async def _stdio_test(
    python: Path, script: Path, token: str, *,
    full: bool, mcp_env: dict[str, str],
) -> dict[str, object]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = os.environ.copy()
    env.update(mcp_env)
    env["DEVFLOW_GITHUB_TOKEN"] = token
    env["PYTHONDONTWRITEBYTECODE"] = "1"
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


def smoke(
    python: Path, gh: Path, script: Path, *,
    full: bool, mcp_env: dict[str, str],
) -> dict:
    token = run([str(gh), "auth", "token", "--hostname", "github.com"], timeout=12)
    if not token or any(ch.isspace() for ch in token):
        raise ReleaseError("existing GitHub CLI authentication is unavailable")
    try:
        return asyncio.run(_stdio_test(
            python, script, token, full=full, mcp_env=mcp_env,
        ))
    except (ReleaseError, KeyboardInterrupt):
        raise
    except Exception as error:
        raise ReleaseError("MCP initialize, catalog, or smoke test failed") from error
    finally:
        token = ""


def release_script(root: Path, sha: str) -> Path:
    validate_sha(sha)
    script = root / "releases" / sha / "tools" / "devflow_mcp.py"
    expected = root.resolve() / "releases" / sha / "tools" / "devflow_mcp.py"
    if not script.is_file() or script.resolve() != expected:
        raise ReleaseError("selected release is missing or redirected")
    return script


def _promote_unlocked(
    *, repo: Path, python: Path, gh: Path, root: Path, fallback: Path,
) -> str:
    state = read_marker(root)
    if state is not None:
        # 停止中・最新版のいずれでも改変済み実体を正常扱いしない。
        require_integrity(root, state["sha"], state["tree_sha256"])
    if updates_held(root):
        return "HELD " + selection_label(state)
    latest = trusted_latest(repo, gh)
    if state is not None and state["sha"] == latest:
        return "UP_TO_DATE " + latest
    if state is not None:
        run(["git", "-C", str(repo), "merge-base", "--is-ancestor",
             state["sha"], latest], timeout=15)
    old_script = release_script(root, state["sha"]) if state else fallback
    if not old_script.is_file():
        raise ReleaseError("current MCP fallback is missing")
    mcp_env = registered_mcp_env(python, fallback)
    previous_catalog = smoke(python, gh, old_script, full=False, mcp_env=mcp_env)
    target = root / "releases" / latest
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".candidate-", dir=root) as tmp:
        stage = Path(tmp) / latest
        stage.mkdir()
        source_archive(repo, latest, stage)
        run_unittests(python, stage)
        candidate = stage / "tools" / "devflow_mcp.py"
        if not candidate.is_file():
            raise ReleaseError("candidate MCP entrypoint is missing")
        if candidate.resolve() != stage.resolve() / "tools" / "devflow_mcp.py":
            raise ReleaseError("candidate release is redirected")
        new_catalog = smoke(python, gh, candidate, full=True, mcp_env=mcp_env)
        if new_catalog != previous_catalog:
            raise ReleaseError("MCP callable schema changed; manual review required")
        verified_digest = release_tree_digest(stage)
        install_verified_release(root, latest, stage, verified_digest)
    try:
        # active.jsonには検証済みstageと一致した実バイトのdigestのみ記録。
        require_integrity(root, latest, verified_digest)
        write_marker(
            root, latest, state["sha"] if state else None,
            tree_sha256=verified_digest,
            previous_tree_sha256=state["tree_sha256"] if state else None,
        )
    except (OSError, ReleaseError) as error:
        # 稼働中の旧版を含め既存releaseは動かさない。次回はfresh stageと
        # digestを比較し、完全一致する場合に限って同じ場所を再利用する。
        raise ReleaseError(
            "release activation incomplete; inspect status before next check"
        ) from error
    return "ACTIVATED " + latest


def promote(
    *, repo: Path, python: Path, gh: Path, root: Path, fallback: Path,
) -> str:
    with release_lock(root):
        return _promote_unlocked(
            repo=repo, python=python, gh=gh, root=root, fallback=fallback,
        )


def rollback(root: Path, fallback: Path) -> str:
    with release_lock(root):
        # 切替失敗やlegacy復帰でも次回の自動昇格を許可しない。
        hold_updates(root)
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
        # 旧版のdigestを作り直して「未検証の改変」を再承認しない。
        require_integrity(root, previous, state["previous_tree_sha256"])
        write_marker(
            root, previous, state["sha"],
            tree_sha256=state["previous_tree_sha256"],
            previous_tree_sha256=state["tree_sha256"],
        )
        return "ROLLED_BACK " + previous


def resume_updates(root: Path, fallback: Path) -> str:
    """明示再開だけが停止を解除する。ここでは候補を実行・昇格しない。"""
    with release_lock(root):
        state = read_marker(root)
        if state is not None:
            require_integrity(root, state["sha"], state["tree_sha256"])
        elif not fallback.is_file():
            raise ReleaseError("original fallback MCP is unavailable")
        if not updates_held(root):
            return "ALREADY_ENABLED " + selection_label(state)
        (root / "updates.hold").unlink()
        return "RESUMED " + selection_label(state)


def status(root: Path) -> str:
    with release_lock(root):
        state = read_marker(root)
        if state is not None:
            require_integrity(root, state["sha"], state["tree_sha256"])
        return ("HELD " if updates_held(root) else "") + selection_label(state)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "status", "rollback", "resume"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--gh", type=Path, required=True)
    parser.add_argument("--fallback", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root or release_root()
    try:
        if args.action == "status":
            outcome = status(root)
        elif args.action == "rollback":
            outcome = rollback(root, args.fallback)
        elif args.action == "resume":
            outcome = resume_updates(root, args.fallback)
        else:
            outcome = promote(
                repo=args.repo, python=args.python, gh=args.gh,
                root=root, fallback=args.fallback,
            )
        print(outcome, flush=True)
        return 0
    except (ReleaseError, OSError) as error:
        print("BLOCKED release operation failed: " + (str(error) if isinstance(error, ReleaseError) else "local filesystem error"), file=sys.stderr, flush=True)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
