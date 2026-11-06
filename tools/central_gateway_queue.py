"""F2B local SQLite ledger for SIMULATED job records only.

This is durable *job-progress bookkeeping*, not Claim/lease/fencing authority,
not authenticated ingress and not an independent runner. No network, GitHub
API, scripts, secret storage or real execution path. Only the F2A fake backend
may produce the Receipt accepted here; receipts remain explicitly simulated.
The database path is trusted local configuration, never a caller job field.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from types import MappingProxyType

from tools.central_execution_gateway import Job, Record, Receipt, request_digest

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_REPO = re.compile(r"[a-z0-9][a-z0-9_.-]*/[a-z0-9][a-z0-9_.-]*\Z")
_BACKENDS = frozenset({"github_actions", "external_isolated"})
_MAX_STORED = 64


class LedgerDenied(ValueError):
    """Fixed classification; never embed path, request, token or source data."""


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise LedgerDenied(reason)


@dataclass(frozen=True)
class StoredJob:
    digest: str
    repository: str
    task_ref: str
    source_sha: str
    recipe_sha256: str
    attempt_id: str
    actor: str
    nonce: str
    epoch: int
    state: str
    backend: str | None
    output_sha256: str | None


_COLS = (
    "digest", "repository", "task_ref", "source_sha",
    "recipe_sha256", "attempt_id", "actor", "nonce", "epoch",
    "state", "backend", "output_sha256",
)
_COLUMNS = ", ".join(_COLS)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS gateway_sim_jobs (
 digest TEXT PRIMARY KEY,
 repository TEXT NOT NULL,
 task_ref TEXT NOT NULL,
 source_sha TEXT NOT NULL,
 recipe_sha256 TEXT NOT NULL,
 attempt_id TEXT NOT NULL,
 actor TEXT NOT NULL,
 nonce TEXT NOT NULL,
 epoch INTEGER NOT NULL CHECK (epoch > 0),
 state TEXT NOT NULL CHECK (
     state IN ('QUEUED','IN_FLIGHT','UNCERTAIN','SIMULATED_RESULT')
 ),
 backend TEXT,
 output_sha256 TEXT,
 UNIQUE (actor, nonce)
);
"""


class SQLiteFakeJobLedger:
    """Transactional CAS on fake job progress; never creates a Claim.

    Supports one or multiple handles pointing to the same trusted local
    SQLite file; BEGIN IMMEDIATE serializes state transitions. Real authority
    and auth must be verified externally before future production integration.
    """

    def __init__(self, database_path: str) -> None:
        _require(type(database_path) is str and 0 < len(database_path) <= 4096
                 and "\x00" not in database_path and "\n" not in database_path,
                 "INVALID_TRUSTED_DB_PATH")
        try:
            self._db = sqlite3.connect(database_path, timeout=5,
                                       isolation_level=None)
            self._db.execute("PRAGMA busy_timeout=5000")
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute(_SCHEMA)
        except sqlite3.Error as exc:
            raise LedgerDenied("LEDGER_STORAGE_UNAVAILABLE") from exc

    def close(self) -> None:
        self._db.close()

    def _get(self, digest: str) -> StoredJob | None:
        raw = self._db.execute(
            "SELECT " + _COLUMNS + " FROM gateway_sim_jobs WHERE digest=?",
            (digest,),
        ).fetchone()
        return StoredJob(*raw) if raw else None

    def observe(self, digest: str) -> StoredJob | None:
        _require(type(digest) is str and _SHA.fullmatch(digest) is not None,
                 "INVALID_DIGEST")
        try:
            return self._get(digest)
        except sqlite3.Error as exc:
            raise LedgerDenied("LEDGER_STORAGE_UNAVAILABLE") from exc

    def _transaction(self, fn):
        try:
            self._db.execute("BEGIN IMMEDIATE")
            value = fn()
            self._db.execute("COMMIT")
            return value
        except Exception:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise

    def admit_fake(self, rec: Record) -> StoredJob:
        """Persist ONLY a previously simulated QUEUED proposal, not authority."""
        _require(type(rec) is Record and rec.state == "QUEUED"
                 and rec.backend is None and rec.receipt is None
                 and rec.reason is None, "NOT_A_FAKE_QUEUED_RECORD")
        job = rec.job
        _require(type(job) is Job and type(job.inputs) in
                 (dict, MappingProxyType), "INVALID_FAKE_RECORD")
        try:
            computed_digest = request_digest(job)
        except (TypeError, ValueError, UnicodeError, OverflowError, AttributeError) as exc:
            raise LedgerDenied("INVALID_FAKE_RECORD") from exc
        _require(type(rec.digest) is str and _SHA.fullmatch(rec.digest) is not None
                 and rec.digest == computed_digest
                 and type(rec.epoch) is int and rec.epoch > 0
                 and type(rec.actor) is str and _TOKEN.fullmatch(rec.actor) is not None
                 and type(rec.nonce) is str and _TOKEN.fullmatch(rec.nonce) is not None
                 and type(job.repository) is str and _REPO.fullmatch(job.repository)
                 and type(job.task_ref) is str and len(job.task_ref) <= 160
                 and type(job.source_sha) is str and _SHA1.fullmatch(job.source_sha)
                 and type(job.recipe_sha256) is str
                 and _SHA.fullmatch(job.recipe_sha256)
                 and type(job.attempt_id) is str and _TOKEN.fullmatch(job.attempt_id),
                 "INVALID_FAKE_RECORD")
        expected = StoredJob(
            rec.digest, job.repository, job.task_ref, job.source_sha,
            job.recipe_sha256, job.attempt_id, rec.actor, rec.nonce,
            rec.epoch, "QUEUED", None, None,
        )

        def act():
            old = self._get(rec.digest)
            if old is not None:
                _require(
                    tuple(getattr(old, key) for key in _COLS[:9])
                    == tuple(getattr(expected, key) for key in _COLS[:9]),
                    "ATTEMPT_COLLISION",
                )
                return old  # Never reset IN_FLIGHT / UNCERTAIN / completed.
            count = self._db.execute(
                "SELECT COUNT(*) FROM gateway_sim_jobs"
            ).fetchone()[0]
            _require(count < _MAX_STORED, "LEDGER_CAPACITY")
            other = self._db.execute(
                "SELECT digest FROM gateway_sim_jobs WHERE actor=? AND nonce=?",
                (rec.actor, rec.nonce),
            ).fetchone()
            _require(other is None, "NONCE_REPLAY")
            self._db.execute(
                "INSERT INTO gateway_sim_jobs (" + _COLUMNS + ") VALUES (" +
                ",".join("?" for _ in _COLS) + ")",
                tuple(getattr(expected, name) for name in _COLS),
            )
            return expected
        return self._transaction(act)

    def begin_fake(self, digest: str, *, epoch: int, backend: str) -> StoredJob:
        """Exactly one queue->in-flight transition; never a real dispatch."""
        _require(type(digest) is str and _SHA.fullmatch(digest) is not None
                 and type(epoch) is int and epoch > 0
                 and type(backend) is str and backend in _BACKENDS,
                 "INVALID_BEGIN")

        def act():
            row = self._get(digest)
            _require(row is not None, "UNKNOWN_ATTEMPT")
            _require(row.epoch == epoch, "STALE_FENCE_EPOCH")
            _require(row.state == "QUEUED", "ALREADY_DISPATCHED")
            cur = self._db.execute(
                "UPDATE gateway_sim_jobs SET state='IN_FLIGHT', backend=? "
                "WHERE digest=? AND epoch=? AND state='QUEUED'",
                (backend, digest, epoch),
            )
            _require(cur.rowcount == 1, "CAS_CONFLICT")
            return self._get(digest)
        return self._transaction(act)

    def complete_fake(self, receipt: Receipt) -> StoredJob:
        _require(type(receipt) is Receipt and receipt.simulated is True
                 and type(receipt.request_digest) is str
                 and _SHA.fullmatch(receipt.request_digest) is not None
                 and type(receipt.backend) is str and receipt.backend in _BACKENDS
                 and type(receipt.fence_epoch) is int and receipt.fence_epoch > 0
                 and type(receipt.output_sha256) is str
                 and _SHA.fullmatch(receipt.output_sha256) is not None,
                 "INVALID_FAKE_RECEIPT")

        def act():
            row = self._get(receipt.request_digest)
            _require(row is not None, "UNKNOWN_ATTEMPT")
            _require(row.epoch == receipt.fence_epoch, "STALE_FENCE_EPOCH")
            _require(row.state in {"IN_FLIGHT", "SIMULATED_RESULT"},
                     "NOT_IN_FLIGHT")
            _require(row.backend == receipt.backend, "BACKEND_MISMATCH")
            if row.state == "SIMULATED_RESULT":
                _require(row.output_sha256 == receipt.output_sha256,
                         "RESULT_COLLISION")
                return row
            _require(row.state == "IN_FLIGHT", "NOT_IN_FLIGHT")
            cur = self._db.execute(
                "UPDATE gateway_sim_jobs SET state='SIMULATED_RESULT', "
                "output_sha256=? WHERE digest=? AND epoch=? AND "
                "state='IN_FLIGHT'",
                (receipt.output_sha256, receipt.request_digest, receipt.fence_epoch),
            )
            _require(cur.rowcount == 1, "CAS_CONFLICT")
            return self._get(receipt.request_digest)
        return self._transaction(act)

    def mark_uncertain(self, digest: str, *, epoch: int) -> StoredJob:
        """Crash/ambiguity can only tighten state, never grant a second run."""
        _require(type(digest) is str and _SHA.fullmatch(digest) is not None
                 and type(epoch) is int and epoch > 0, "INVALID_UNCERTAIN")

        def act():
            row = self._get(digest)
            _require(row is not None, "UNKNOWN_ATTEMPT")
            _require(row.epoch == epoch, "STALE_FENCE_EPOCH")
            _require(row.state in {"IN_FLIGHT", "UNCERTAIN"}, "NOT_IN_FLIGHT")
            if row.state == "UNCERTAIN":
                return row
            self._db.execute(
                "UPDATE gateway_sim_jobs SET state='UNCERTAIN' "
                "WHERE digest=? AND epoch=? AND state='IN_FLIGHT'",
                (digest, epoch),
            )
            return self._get(digest)
        return self._transaction(act)
