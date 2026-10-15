"""F2A *offline simulator* for devflow's central account-wide execution gateway.

No GitHub transport, host, real executor, credential minting, durable authority or
second Claim ledger exists here. HMAC authenticates only a centrally configured
test issuer; it does NOT authenticate GitHub user/App identity. FakeClaims and
FakeBackend are deliberately the only supported execution surfaces.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REPO = re.compile(r"[a-z0-9][a-z0-9_.-]*/[a-z0-9][a-z0-9_.-]*\Z")
_TASK = re.compile(r"([a-z0-9][a-z0-9_.-]*/[a-z0-9][a-z0-9_.-]*)#[1-9][0-9]*\Z")
_ID = re.compile(r"[a-z][a-z0-9_.-]{0,79}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_BACKENDS = frozenset({"github_actions", "external_isolated"})
_MAX_JOBS = 64


class Denied(ValueError):
    """Fixed denial code only; no untrusted input or private material."""


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise Denied(reason)


def _valid_repo(value: object) -> bool:
    return type(value) is str and _REPO.fullmatch(value) is not None and all(
        not segment.startswith((".", "-")) and not segment.endswith(".git")
        for segment in value.split("/")
    )


def _bytes(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


@dataclass(frozen=True)
class RecipePolicy:
    repository: str
    recipe_id: str
    recipe_sha256: str
    task_owners: frozenset[str]
    actors: frozenset[str]
    input_schema: Mapping[str, str]
    backends: frozenset[str]


@dataclass(frozen=True)
class Job:
    repository: str
    task_ref: str
    source_sha: str
    recipe_id: str
    recipe_sha256: str
    attempt_id: str
    inputs: Mapping[str, object]


@dataclass(frozen=True)
class SignedIngress:
    actor: str
    nonce: str
    issued_at: int
    expires_at: int
    signature: str


@dataclass(frozen=True)
class ClaimView:
    """Test-only observation; never an authorization token in real execution."""
    request_digest: str
    repository: str
    source_sha: str
    attempt_id: str
    fence_epoch: int
    lease_until: int


@dataclass(frozen=True)
class HealthView:
    actions: str
    external: str
    github_api: str


@dataclass(frozen=True)
class Receipt:
    """SIMULATED receipt, not verified GitHub status or published artifact."""
    request_digest: str
    backend: str
    fence_epoch: int
    output_sha256: str
    simulated: bool = True


@dataclass(frozen=True)
class Record:
    job: Job
    actor: str
    nonce: str
    ingress_expires: int
    digest: str
    epoch: int
    state: str
    backend: str | None = None
    receipt: Receipt | None = None
    reason: str | None = None


class MemoryStore:
    """Shared across simulated gateway restarts. NOT a durable transactional DB."""

    def __init__(self) -> None:
        self.records: dict[str, Record] = {}
        self.nonces: dict[tuple[str, str], str] = {}


class FakeClaims:
    """Test replacement for the future single-writer verified Claim adapter."""

    def __init__(self) -> None:
        self.views: dict[str, ClaimView] = {}

    def observe(self, digest: str) -> ClaimView | None:
        return self.views.get(digest)


class FakeHealth:
    def __init__(self, *, actions: str = "READY", external: str = "READY",
                 github_api: str = "VERIFIED") -> None:
        self.view = HealthView(actions, external, github_api)

    def observe(self) -> HealthView:
        return self.view


class FakeBackend:
    """Deterministic fake output, without process/network/filesystem execution."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self.fail_next = False

    def run(self, job: Job, digest: str, backend: str, epoch: int) -> Receipt:
        _require(backend in _BACKENDS, "INVALID_BACKEND")
        self.calls.append((digest, backend, epoch))
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("SIMULATED_UNKNOWN_OUTCOME")
        # Both candidate backends produce equivalent fixed-contract fake output.
        result = _bytes({"recipe": job.recipe_sha256, "source": job.source_sha,
                         "inputs": dict(job.inputs)})
        return Receipt(digest, backend, epoch, hashlib.sha256(result).hexdigest())


def _job_shape(job: Job, policy: RecipePolicy) -> bool:
    if type(job) is not Job or type(policy) is not RecipePolicy:
        return False
    if not (_valid_repo(job.repository) and _valid_repo(policy.repository)
            and job.repository == policy.repository
            and type(job.task_ref) is str):
        return False
    task = _TASK.fullmatch(job.task_ref)
    if task is None or not _valid_repo(task.group(1)):
        return False
    if task.group(1) != job.repository and task.group(1) not in policy.task_owners:
        return False
    if not (type(job.source_sha) is str and _SHA1.fullmatch(job.source_sha)
            and type(job.recipe_sha256) is str and _SHA256.fullmatch(job.recipe_sha256)
            and job.recipe_sha256 == policy.recipe_sha256
            and type(job.recipe_id) is str and job.recipe_id == policy.recipe_id
            and type(policy.recipe_id) is str and _ID.fullmatch(policy.recipe_id)
            and type(job.attempt_id) is str and _TOKEN.fullmatch(job.attempt_id)):
        return False
    if not (type(policy.task_owners) is frozenset and len(policy.task_owners) <= 16
            and all(_valid_repo(x) for x in policy.task_owners)
            and type(policy.actors) is frozenset and 0 < len(policy.actors) <= 16
            and all(type(x) is str and _TOKEN.fullmatch(x) for x in policy.actors)
            and type(policy.backends) is frozenset
            and bool(policy.backends) and policy.backends <= _BACKENDS
            and type(policy.input_schema) in (dict, MappingProxyType)
            and len(policy.input_schema) <= 16
            and all(type(k) is str and _ID.fullmatch(k) and
                    type(t) is str and t in {"str", "int", "bool"}
                    for k, t in policy.input_schema.items())):
        return False
    if type(job.inputs) not in (dict, MappingProxyType) or job.inputs.keys() != policy.input_schema.keys():
        return False
    for k, t in policy.input_schema.items():
        x = job.inputs[k]
        if type(x) is not {"str": str, "int": int, "bool": bool}[t]:
            return False
        if t == "str" and (len(x) > 1024 or any(
            ord(c) < 32 or 127 <= ord(c) <= 159 or 0x202a <= ord(c) <= 0x202e
            or 0xd800 <= ord(c) <= 0xdfff for c in x
        )):
            return False
        if t == "int" and not -(2 ** 53) < x < 2 ** 53:
            return False
    return True


def request_digest(job: Job) -> str:
    """Attempt identity, not a Claim, permission or backend credential."""
    return hashlib.sha256(_bytes({
        "repository": job.repository, "task_ref": job.task_ref,
        "source_sha": job.source_sha, "recipe_id": job.recipe_id,
        "recipe_sha256": job.recipe_sha256, "attempt_id": job.attempt_id,
        "inputs": dict(job.inputs),
    })).hexdigest()


def signing_payload(job: Job, *, actor: str, nonce: str,
                    issued_at: int, expires_at: int) -> bytes:
    """Canonical bytes for a central trusted HMAC issuer; no signer installed."""
    return _bytes({"domain": "devflow-f2a-offline-v1", "job_digest": request_digest(job),
                   "actor": actor, "nonce": nonce,
                   "issued_at": issued_at, "expires_at": expires_at})


def _route(policy: RecipePolicy, health: HealthView) -> str | None:
    if (type(health) is not HealthView or health.github_api != "VERIFIED"
            or health.actions in {"UNKNOWN", "POLICY_DISABLED"}
            or health.actions not in {"READY", "CAPACITY_BLOCKED", "CONTROL_OUTAGE",
                                      "UNKNOWN", "POLICY_DISABLED"}):
        return None
    if health.actions == "READY" and "github_actions" in policy.backends:
        return "github_actions"
    if (health.actions in {"CAPACITY_BLOCKED", "CONTROL_OUTAGE"}
            and health.external == "READY"
            and "external_isolated" in policy.backends):
        return "external_isolated"
    if ("github_actions" not in policy.backends and
            health.external == "READY" and "external_isolated" in policy.backends):
        return "external_isolated"
    return None


class OfflineGateway:
    """Purely simulated F2A state machine, NOT production dispatch machinery."""

    def __init__(self, *, policies: tuple[RecipePolicy, ...], hmac_key: bytes,
                 store: MemoryStore, claims: FakeClaims, health: FakeHealth,
                 backend: FakeBackend) -> None:
        _require(type(hmac_key) is bytes and len(hmac_key) >= 32, "INVALID_VERIFIER_KEY")
        _require(type(policies) is tuple and all(type(p) is RecipePolicy for p in policies),
                 "INVALID_CATALOG")
        _require(all(type(x) is t for x, t in (
            (store, MemoryStore), (claims, FakeClaims),
            (health, FakeHealth), (backend, FakeBackend))), "NOT_OFFLINE_FAKE_ADAPTER")
        self.catalog: dict[tuple[str, str], RecipePolicy] = {}
        for p in policies:
            _require(_valid_repo(p.repository) and type(p.recipe_id) is str
                     and _ID.fullmatch(p.recipe_id), "INVALID_CATALOG")
            key = (p.repository, p.recipe_id)
            _require(key not in self.catalog, "DUPLICATE_CATALOG_ENTRY")
            # Defensive snapshots: frozen dataclasses can still contain mutable dicts.
            self.catalog[key] = replace(p, input_schema=MappingProxyType(dict(p.input_schema)))
        self._key = hmac_key
        self.store, self.claims, self.health, self.backend = (
            store, claims, health, backend
        )

    def _claim(self, job: Job, digest: str, now: int) -> ClaimView:
        view = self.claims.observe(digest)
        _require(type(view) is ClaimView, "AUTHORITY_UNAVAILABLE")
        _require(view.request_digest == digest
                 and view.repository == job.repository
                 and view.source_sha == job.source_sha
                 and view.attempt_id == job.attempt_id
                 and type(view.fence_epoch) is int and view.fence_epoch > 0
                 and type(view.lease_until) is int and now < view.lease_until,
                 "CLAIM_STALE_OR_MISMATCHED")
        return view

    def submit(self, job: Job, proof: SignedIngress, *, now: int) -> Record:
        _require(type(now) is int and now >= 0, "INVALID_TIME")
        _require(type(job) is Job, "INVALID_REQUEST")
        _require(type(job.repository) is str and type(job.recipe_id) is str,
                 "INVALID_REQUEST")
        policy = self.catalog.get((job.repository, job.recipe_id))
        _require(policy is not None and _job_shape(job, policy), "CATALOG_DENIED")
        # Snapshot validated scalar inputs before digest and persistence. Caller
        # mutations after enqueue cannot alter the signed/claimed job payload.
        job = replace(job, inputs=MappingProxyType(dict(job.inputs)))
        _require(type(proof) is SignedIngress and type(proof.actor) is str
                 and proof.actor in policy.actors and type(proof.nonce) is str
                 and _TOKEN.fullmatch(proof.nonce)
                 and type(proof.issued_at) is int and type(proof.expires_at) is int
                 and proof.issued_at <= now < proof.expires_at
                 and proof.issued_at >= now - 300
                 and proof.expires_at - proof.issued_at <= 300
                 and type(proof.signature) is str
                 and _SHA256.fullmatch(proof.signature), "INVALID_INGRESS")
        canonical = signing_payload(
            job, actor=proof.actor, nonce=proof.nonce,
            issued_at=proof.issued_at, expires_at=proof.expires_at)
        signature = hmac.new(self._key, canonical, hashlib.sha256).hexdigest()
        _require(hmac.compare_digest(signature, proof.signature), "INVALID_SIGNATURE")
        digest = request_digest(job)
        nonce_key = (proof.actor, proof.nonce)
        recorded_digest = self.store.nonces.get(nonce_key)
        _require(recorded_digest is None or recorded_digest == digest, "NONCE_REPLAY")
        old = self.store.records.get(digest)
        if old is not None:
            _require(old.actor == proof.actor and old.nonce == proof.nonce and old.job == job, "ATTEMPT_COLLISION")
            return old  # Idempotent read, never requeue a completed/unknown attempt.
        _require(len(self.store.records) < _MAX_JOBS, "SIMULATOR_CAPACITY")
        view = self._claim(job, digest, now)
        _require(_route(policy, self.health.observe()) is not None, "BACKEND_UNAVAILABLE")
        rec = Record(job, proof.actor, proof.nonce, proof.expires_at, digest,
                     view.fence_epoch, "QUEUED")
        self.store.nonces[nonce_key] = digest
        self.store.records[digest] = rec
        return rec

    def run_next(self, *, now: int) -> Record | None:
        _require(type(now) is int and now >= 0, "INVALID_TIME")
        for digest, rec in self.store.records.items():
            if rec.state != "QUEUED":
                continue
            try:
                view = self._claim(rec.job, digest, now)
                _require(view.fence_epoch == rec.epoch, "STALE_FENCE_EPOCH")
                policy = self.catalog.get((rec.job.repository, rec.job.recipe_id))
                _require(policy is not None and _job_shape(rec.job, policy),
                         "CATALOG_DENIED")
                backend = _route(policy, self.health.observe())
                _require(backend is not None, "BACKEND_UNAVAILABLE")
            except Denied as exc:
                blocked = replace(rec, state="HELD", reason=str(exc))
                self.store.records[digest] = blocked
                return blocked
            # Mark before fake dispatch; uncertain results are never auto-replayed.
            started = replace(rec, state="IN_FLIGHT", backend=backend)
            self.store.records[digest] = started
            try:
                result = self.backend.run(rec.job, digest, backend, rec.epoch)
            except Exception:
                unknown = replace(started, state="UNCERTAIN", reason="UNKNOWN_OUTCOME")
                self.store.records[digest] = unknown
                return unknown
            try:
                post = self._claim(rec.job, digest, now)
                _require(post.fence_epoch == rec.epoch, "STALE_FENCE_EPOCH")
                _require(type(result) is Receipt and result.simulated is True
                         and result.request_digest == digest
                         and result.backend == backend
                         and result.fence_epoch == rec.epoch
                         and type(result.output_sha256) is str
                         and _SHA256.fullmatch(result.output_sha256),
                         "UNVERIFIED_FAKE_RECEIPT")
            except Denied:
                ambiguous = replace(started, state="UNCERTAIN",
                                    reason="POSTRUN_AUTHORITY_OR_RESULT_UNKNOWN")
                self.store.records[digest] = ambiguous
                return ambiguous
            complete = replace(started, state="SIMULATED_RESULT", receipt=result)
            self.store.records[digest] = complete
            return complete
        return None
