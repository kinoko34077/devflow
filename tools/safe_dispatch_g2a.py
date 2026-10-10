"""Offline G2A preflight for a single read-only GitHub metadata operation.

No GitHub I/O, token, identity authentication, durable distributed claim, or
execution occurs here. An authenticated adapter must construct observations
from trusted GitHub responses and must pin/verify the catalog source.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from tools.safe_dispatch_contract import admit_dispatch

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{8,80}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_HANDLER = "github.repository_metadata"


@dataclass(frozen=True)
class ObservedReadContext:
    """Adapter-supplied evidence; this dataclass does NOT authenticate it."""
    principal_id: int
    actor_login: str
    repository: str
    default_branch: str
    actual_head_sha: str
    visibility: str
    can_read: bool
    handler: str


@dataclass(frozen=True)
class ReadPreflight:
    status: str
    reason: str
    principal_id: int | None = None
    request_id: str | None = None
    repository: str | None = None
    request_digest: str | None = None
    catalog_commit_sha: str | None = None


def _request_digest(request: Any) -> str | None:
    if type(request) is not dict:
        return None
    try:
        raw = json.dumps(request, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, OverflowError, RecursionError):
        return None
    if len(raw) > 8192:
        return None
    return hashlib.sha256(b"devflow-g2a-v1\0" + raw).hexdigest()


def inspect_read_request(
    request: Any,
    trusted_catalog: Any,
    *,
    catalog_commit_sha: str,
    observation: ObservedReadContext,
) -> ReadPreflight:
    """Pure check, not an authorization to execute.

    Callers cannot use user-provided observation/catalog data as trust evidence.
    The future authenticated adapter must obtain actor and repository data from
    connector-returned results, pin catalog bytes, and repeat head checks before
    any real effect. This module never calls a connector.
    """
    def block(reason: str) -> ReadPreflight:
        return ReadPreflight("BLOCKED", reason)

    if type(observation) is not ObservedReadContext:
        return block("INVALID_OBSERVATION")
    if not (
        type(observation.principal_id) is int and observation.principal_id > 0
        and type(observation.actor_login) is str and observation.actor_login
        and type(observation.repository) is str and observation.repository
        and type(observation.default_branch) is str
        and type(observation.actual_head_sha) is str
        and type(observation.visibility) is str
        and type(observation.can_read) is bool
        and type(observation.handler) is str
    ):
        return block("INVALID_OBSERVATION")
    if type(catalog_commit_sha) is not str or not _SHA.fullmatch(catalog_commit_sha):
        return block("CATALOG_COMMIT_NOT_PINNED")
    digest = _request_digest(request)
    if digest is None:
        return block("INVALID_REQUEST_DIGEST")

    # G1 is evaluated here, not merely presumed from a user-supplied
    # Admission-shaped object.
    decision = admit_dispatch(
        request, trusted_catalog, verified_actor=observation.actor_login
    )
    if decision.status != "ADMITTED" or decision.reason != "POLICY_ADMITTED_NOT_EXECUTED":
        return block("G1_DID_NOT_ADMIT")
    if (
        decision.action != "repo.status"
        or decision.backend != "github_api"
        or decision.executor != _HANDLER
        or decision.reviewed_workflow_sha is not None
    ):
        return block("NON_ALLOWLISTED_HANDLER")
    if (
        observation.handler != _HANDLER
        or observation.visibility not in ("public", "private")
        or not observation.can_read
    ):
        return block("CONNECTOR_READ_NOT_PROVEN")
    if (
        decision.repository != observation.repository
        or request["repository"] != observation.repository
    ):
        return block("REPOSITORY_MISMATCH")
    if (
        decision.ref != observation.default_branch
        or request["ref"] != observation.default_branch
    ):
        return block("BRANCH_MISMATCH")
    if (
        not _SHA.fullmatch(observation.actual_head_sha)
        or decision.head_sha != observation.actual_head_sha
        or request["head_sha"] != observation.actual_head_sha
    ):
        return block("HEAD_MISMATCH")
    if type(decision.request_id) is not str or not _REQUEST_ID.fullmatch(decision.request_id):
        return block("INVALID_REQUEST_ID")
    return ReadPreflight(
        status="PREFLIGHT_ONLY",
        reason="READ_CHECKS_MATCH_NOT_EXECUTED",
        principal_id=observation.principal_id,
        request_id=decision.request_id,
        repository=decision.repository,
        request_digest=digest,
        catalog_commit_sha=catalog_commit_sha,
    )


@dataclass(frozen=True)
class ReserveResult:
    status: str
    reason: str


class SQLiteReservationPrototype:
    """Single shared SQLite file only; NOT cross-machine fencing or execution.

    A successful reservation stays permanently held, even after a crash.
    There is no release/retry/dispatch operation in this offline proof.
    """
    def __init__(self, filename: str | Path):
        self.filename = str(filename)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS read_reservations (
                principal_id INTEGER NOT NULL,
                request_id TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                repository TEXT NOT NULL,
                catalog_commit_sha TEXT NOT NULL,
                PRIMARY KEY(principal_id, request_id)
            )""")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.filename, timeout=5, isolation_level=None)

    def reserve(self, check: ReadPreflight) -> ReserveResult:
        if not (
            type(check) is ReadPreflight
            and check.status == "PREFLIGHT_ONLY"
            and check.reason == "READ_CHECKS_MATCH_NOT_EXECUTED"
            and type(check.principal_id) is int and check.principal_id > 0
            and type(check.request_id) is str and _REQUEST_ID.fullmatch(check.request_id)
            and type(check.repository) is str and bool(check.repository)
            and type(check.catalog_commit_sha) is str and _SHA.fullmatch(check.catalog_commit_sha)
            and type(check.request_digest) is str and _DIGEST.fullmatch(check.request_digest)
        ):
            return ReserveResult("DENIED", "NO_ACCEPTED_OFFLINE_PREFLIGHT")

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT request_digest, repository, catalog_commit_sha "
                "FROM read_reservations WHERE principal_id=? AND request_id=?",
                (check.principal_id, check.request_id),
            ).fetchone()
            if prior is not None:
                same = prior == (check.request_digest, check.repository,
                                 check.catalog_commit_sha)
                db.rollback()
                return ReserveResult(
                    "REPLAY_LOCKED" if same else "REQUEST_ID_CONFLICT",
                    "RESERVATION_EXISTS" if same else "KEY_REUSED_FOR_DIFFERENT_REQUEST",
                )
            db.execute(
                "INSERT INTO read_reservations "
                "(principal_id,request_id,request_digest,repository,catalog_commit_sha) "
                "VALUES (?,?,?,?,?)",
                (check.principal_id, check.request_id, check.request_digest,
                 check.repository, check.catalog_commit_sha),
            )
            db.commit()
        return ReserveResult("RESERVED_NOT_EXECUTED", "ONE_LOCAL_ATOMIC_RESERVATION")
