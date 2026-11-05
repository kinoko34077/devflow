"""One-shot outbound GitHub Issue command GET -> approved fixed WSL2 Public job.

No daemon, inbound listener, arbitrary command, Private code, new credential or
claim. GitHub-authored comment metadata is NOT a cryptographic job issuer.
"""
from __future__ import annotations

from contextlib import closing

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from tools.safe_dispatch_contract import parse_json_object
from tools.github_issue_trust import is_trusted_principal
from tools.shared_execution_safety_contract import project_f3c_candidate
from tools.wsl_fixed_public_bridge import run_once as run_fixed_public

_ISSUE_URL = "https://api.github.com/repos/kinoko34077/devflow/issues/610"
_ENDPOINT = "repos/kinoko34077/devflow/issues/comments/"
_PREFIX = "F3C-WSL-PUBLIC-ONCE-V1\n"
_MAX_RESPONSE = 16384


@dataclass(frozen=True)
class PullResult:
    status: str
    reason: str | None = None
    comment_id: int | None = None
    nonce_sha256: str | None = None
    github_author_observed: bool = False
    authenticated: bool = False
    isolated_host_verified: bool = False
    claim_authority: bool = False
    github_check_authority: bool = False


def _fetch_comment(comment_id: int) -> dict | None:
    # Existing Windows gh credential is used by gh ONLY; never forwarded to WSL.
    try:
        proc = subprocess.run(
            ["gh", "api", "-H", "Accept: application/vnd.github+json",
             _ENDPOINT + str(comment_id)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=False, shell=False, timeout=15,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or len(proc.stdout) > _MAX_RESPONSE:
        return None
    try:
        result = json.loads(proc.stdout)
    except (ValueError, TypeError):
        return None
    return result if type(result) is dict else None


def _validate(comment: dict | None, comment_id: int) -> str | None:
    if type(comment) is not dict:
        return None
    author = comment.get("user")
    if (type(comment.get("id")) is not int or comment["id"] != comment_id
            or comment.get("issue_url") != _ISSUE_URL or type(author) is not dict
            or not is_trusted_principal(comment)
            or author.get("login") != "kinoko34077" or author.get("type") != "User"
            or comment.get("created_at") is None
            or comment.get("created_at") != comment.get("updated_at")):
        return None
    body = comment.get("body")
    if type(body) is not str or len(body) > 1024 or not body.startswith(_PREFIX):
        return None
    # M2 projection is pure CANDIDATE_ONLY. GitHub author metadata above
    # provides attribution only, never an authenticated execution principal.
    projection = project_f3c_candidate(
        body, comment_id=comment_id, observed_login=author["login"]
    )
    if projection.status != "CANDIDATE_ONLY":
        return None
    # Preserve legacy sha256(nonce) SQLite identity across upgrade: use the
    # existing reviewed strict JSON decoder, never rehash old reservations.
    try:
        job = parse_json_object(body[len(_PREFIX):], max_bytes=1024)
    except ValueError:
        return None
    return job["nonce"]

def _ledger_path() -> Path | None:
    if os.name != "nt":
        return None
    home = os.environ.get("LOCALAPPDATA")
    if not home:
        return None
    return Path(home) / "KiNoTch" / "devflow" / "f3c_wsl_public_attempts.sqlite3"


def _reserve(path: Path, comment_id: int, nonce_sha256: str) -> str:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(str(path), timeout=5, isolation_level=None)) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS public_job_attempts "
                "(comment_id INTEGER PRIMARY KEY, nonce_sha256 TEXT NOT NULL UNIQUE, "
                "status TEXT NOT NULL)"
            )
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "INSERT INTO public_job_attempts (comment_id, nonce_sha256, status) "
                    "VALUES (?, ?, 'RESERVED')", (comment_id, nonce_sha256)
                )
            except sqlite3.IntegrityError:
                conn.execute("ROLLBACK")
                return "REPLAY_DENIED"
            conn.execute("COMMIT")
        return "RESERVED"
    except (OSError, sqlite3.Error, ValueError):
        return "LEDGER_UNAVAILABLE"


def _complete(path: Path, comment_id: int, status: str) -> None:
    try:
        with closing(sqlite3.connect(str(path), timeout=5)) as conn:
            conn.execute(
                "UPDATE public_job_attempts SET status=? "
                "WHERE comment_id=? AND status='RESERVED'", (status, comment_id)
            )
            conn.commit()
    except (OSError, sqlite3.Error):
        # Fail closed: original reservation remains; never auto-retry.
        return


def execute_comment(comment_id: int, *, execute: bool = False,
                    ledger_path: Path | None = None) -> PullResult:
    """Default validates only. Execution additionally requires --execute."""
    if type(comment_id) is not int or not 1 <= comment_id < 10**17:
        return PullResult("HOLD", "INVALID_COMMENT_ID")
    comment = _fetch_comment(comment_id)
    nonce = _validate(comment, comment_id)
    if nonce is None:
        return PullResult("HOLD", "REQUEST_UNTRUSTED_OR_UNAVAILABLE", comment_id)
    digest = hashlib.sha256(nonce.encode("ascii")).hexdigest()
    if not execute:
        return PullResult("CANDIDATE_ONLY", comment_id=comment_id,
                          nonce_sha256=digest, github_author_observed=True)
    path = ledger_path if ledger_path is not None else _ledger_path()
    if not isinstance(path, Path):
        return PullResult("HOLD", "LEDGER_PATH_UNAVAILABLE", comment_id)
    state = _reserve(path, comment_id, digest)
    if state != "RESERVED":
        return PullResult("HOLD", state, comment_id, digest,
                          github_author_observed=True)
    try:
        result = run_fixed_public(timeout_seconds=40)
        good = result.status == "WSL_FIXED_PUBLIC_PROOF" and (
            result.public_source_blob_verified is True
            and result.authenticated is False
            and result.isolated_host_verified is False
            and result.claim_authority is False
            and result.github_check_authority is False
        )
    except Exception:
        good = False
    _complete(path, comment_id, "SUCCEEDED" if good else "UNCERTAIN")
    return PullResult("PUBLIC_READONLY_EXECUTED" if good else "HOLD",
                      None if good else "WORKER_NOT_VERIFIED",
                      comment_id, digest, github_author_observed=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GET one exact GitHub owner-comment and optionally run fixed WSL2 Public probe"
    )
    parser.add_argument("--comment-id", type=int, required=True)
    parser.add_argument("--execute", action="store_true",
                        help="Runs one fixed PUBLIC read-only job and reserves nonce durably")
    args = parser.parse_args()
    result = execute_comment(args.comment_id, execute=args.execute)
    print(json.dumps(asdict(result), sort_keys=True))
    return 0 if result.status in {"CANDIDATE_ONLY", "PUBLIC_READONLY_EXECUTED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
