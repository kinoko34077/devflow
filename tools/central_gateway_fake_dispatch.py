"""F2C C2 bounded *fake-only* ingress -> durable progress -> backend integration.

This is a deterministic test harness, NOT a real identity issuer, scheduler,
GitHub API client, independent executor or Claim authority. It explicitly
depends on F2A FakeClaims/FakeHealth/FakeBackend and F2B SQLiteFakeJobLedger.
The signing key is injected for local tests only; it does not prove GitHub
user, OIDC, App installation or Human permission. No subprocess/network.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass

from tools.central_execution_gateway import (
    Denied, FakeBackend, Job, OfflineGateway, Receipt, SignedIngress,
    _route, request_digest,
)
from tools.central_gateway_queue import LedgerDenied, SQLiteFakeJobLedger, StoredJob

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ACTOR = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class FakeDispatchDenied(ValueError):
    """Finite fixed reason code; no user/job/key/source text."""


def _check(ok: bool, reason: str) -> None:
    if not ok:
        raise FakeDispatchDenied(reason)


@dataclass(frozen=True)
class SignedTestPrincipal:
    actor: str
    repository: str
    job_digest: str
    effect: str
    issued_at: int
    expires_at: int
    signature: str


@dataclass(frozen=True)
class FakeBudget:
    max_duration_seconds: int
    max_cost_units: int


def _identity_data(
    actor: str, repository: str, digest: str, effect: str,
    issued_at: int, expires_at: int,
) -> bytes:
    return json.dumps(
        {"domain": "devflow-f2c-fake-principal-v1",
         "actor": actor, "repository": repository, "digest": digest,
         "effect": effect, "iat": issued_at, "exp": expires_at},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")


class TestPrincipalIssuer:
    """Test-only issuer, not GitHub App/OIDC or a production identity provider."""

    def __init__(self, test_key: bytes):
        _check(type(test_key) is bytes and len(test_key) >= 32,
               "INVALID_TEST_ISSUER")
        self._key = test_key

    def sign(self, *, actor: str, repository: str, job: Job,
             issued_at: int, expires_at: int) -> SignedTestPrincipal:
        _check(type(job) is Job and type(actor) is str
               and _ACTOR.fullmatch(actor) is not None
               and type(repository) is str
               and type(issued_at) is int and type(expires_at) is int,
               "INVALID_TEST_ISSUER_INPUT")
        try:
            digest = request_digest(job)
            raw = _identity_data(actor, repository, digest, "READ_ONLY",
                                 issued_at, expires_at)
        except (TypeError, ValueError, UnicodeError, OverflowError,
                AttributeError, RecursionError) as exc:
            raise FakeDispatchDenied("INVALID_TEST_ISSUER_INPUT") from exc
        return SignedTestPrincipal(
            actor, repository, digest, "READ_ONLY", issued_at, expires_at,
            hmac.new(self._key, raw, hashlib.sha256).hexdigest(),
        )

    def verify(self, token: SignedTestPrincipal, *, job: Job,
               actor: str, now: int) -> None:
        _check(type(token) is SignedTestPrincipal and type(job) is Job
               and type(actor) is str and type(now) is int and now >= 0,
               "INVALID_TEST_PRINCIPAL")
        try:
            digest = request_digest(job)
        except (TypeError, ValueError, UnicodeError, OverflowError,
                AttributeError, RecursionError) as exc:
            raise FakeDispatchDenied("INVALID_TEST_PRINCIPAL") from exc
        _check(
            type(token.actor) is str and token.actor == actor
            and type(token.repository) is str
            and type(job.repository) is str
            and token.repository == job.repository
            and type(token.job_digest) is str
            and _DIGEST.fullmatch(token.job_digest) is not None
            and token.job_digest == digest
            and token.effect == "READ_ONLY"
            and type(token.issued_at) is int and type(token.expires_at) is int
            and token.issued_at <= now < token.expires_at
            and token.expires_at - token.issued_at <= 300
            and token.issued_at >= now - 300
            and type(token.signature) is str
            and _DIGEST.fullmatch(token.signature) is not None,
            "INVALID_TEST_PRINCIPAL",
        )
        data = _identity_data(
            token.actor, token.repository, token.job_digest,
            token.effect, token.issued_at, token.expires_at,
        )
        actual = hmac.new(self._key, data, hashlib.sha256).hexdigest()
        _check(hmac.compare_digest(actual, token.signature),
               "INVALID_TEST_PRINCIPAL")


class FakeIntegratedDispatch:
    """No callbacks except accepted F2A fake authority and F2B fake job ledger.

    At most one fake run for each durable digest+epoch; a crash after durable
    IN_FLIGHT never permits redispatch, even after Python process restart.
    No public production run method is implemented.
    """

    def __init__(self, *, issuer: TestPrincipalIssuer,
                 gateway: OfflineGateway, ledger: SQLiteFakeJobLedger):
        _check(type(issuer) is TestPrincipalIssuer
               and type(gateway) is OfflineGateway
               and type(gateway.backend) is FakeBackend
               and type(ledger) is SQLiteFakeJobLedger,
               "NOT_FAKE_ONLY_BOUNDARY")
        self.issuer, self.gateway, self.ledger = issuer, gateway, ledger

    def execute_fake(
        self, job: Job, ingress: SignedIngress,
        principal: SignedTestPrincipal, budget: FakeBudget, *, now: int,
    ) -> StoredJob:
        _check(type(budget) is FakeBudget
               and type(budget.max_duration_seconds) is int
               and 0 < budget.max_duration_seconds <= 60
               and type(budget.max_cost_units) is int
               and 0 < budget.max_cost_units <= 100,
               "FAKE_BUDGET_DENIED")
        _check(type(ingress) is SignedIngress,
               "INVALID_INGRESS")
        self.issuer.verify(principal, job=job, actor=ingress.actor, now=now)
        try:
            record = self.gateway.submit(job, ingress, now=now)
            persisted = self.ledger.admit_fake(record)
        except (Denied, LedgerDenied) as exc:
            raise FakeDispatchDenied("ADMISSION_OR_LEDGER_DENIED") from exc

        if persisted.state != "QUEUED":
            return persisted  # Persisted in-flight/unknown/completed: NEVER re-run.
        digest = record.digest
        try:
            claim = self.gateway._claim(record.job, digest, now)
            _check(claim.fence_epoch == record.epoch,
                   "FAKE_AUTHORITY_EPOCH_CHANGED")
            policy = self.gateway.catalog.get(
                (record.job.repository, record.job.recipe_id)
            )
            _check(policy is not None, "CATALOG_DENIED")
            backend = _route(policy, self.gateway.health.observe())
            _check(backend is not None, "BACKEND_UNAVAILABLE")
        except (Denied, FakeDispatchDenied) as exc:
            raise FakeDispatchDenied("FAKE_PRE_DISPATCH_HOLD") from exc

        # The SQLite CAS is durable before the first fake backend call.
        # It is not Claim grant or actual isolation, and does not emit a task.
        try:
            self.ledger.begin_fake(digest, epoch=record.epoch, backend=backend)
        except LedgerDenied as exc:
            raise FakeDispatchDenied("ALREADY_OR_NOT_DISPATCHABLE") from exc
        try:
            # SQLite CAS is not a Claim: re-observe the fake authority before
            # the simulated effect. Real runners must ALSO fence at the resource.
            pre_effect = self.gateway._claim(record.job, digest, now)
            _check(pre_effect.fence_epoch == record.epoch,
                   "FAKE_AUTHORITY_EPOCH_CHANGED")
            receipt = self.gateway.backend.run(
                record.job, digest, backend, record.epoch,
            )
            checked = self.gateway._claim(record.job, digest, now)
            _check(checked.fence_epoch == record.epoch,
                   "FAKE_AUTHORITY_EPOCH_CHANGED")
            _check(type(receipt) is Receipt and receipt.simulated is True
                   and receipt.request_digest == digest
                   and receipt.backend == backend
                   and receipt.fence_epoch == record.epoch,
                   "UNBOUND_FAKE_RECEIPT")
            return self.ledger.complete_fake(receipt)
        except Exception:
            # The remote outcome could be unknown in a future implementation;
            # never change it back to QUEUED or automatically re-run.
            try:
                return self.ledger.mark_uncertain(digest, epoch=record.epoch)
            except LedgerDenied as exc:
                raise FakeDispatchDenied("POSTRUN_STORAGE_UNKNOWN") from exc
