"""G2B offline-only connector seam proof; NOT an authenticated dispatch service.

This module never obtains credentials, chooses an HTTP endpoint or contacts
GitHub. A caller can fabricate the fixture provider and pins. All returned
states are SIMULATION/BLOCKED, never authorization or execution receipts.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Protocol

from tools.safe_dispatch_contract import parse_json_object
from tools.safe_dispatch_g2a import ObservedReadContext, inspect_read_request

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


@dataclass(frozen=True)
class StartupPins:
    """Synthetic trusted-startup configuration, NOT request-controlled."""
    operator_id: int
    operator_login: str
    repository_id: str
    repository: str
    ref: str
    catalog_commit_sha: str
    catalog_sha256: str


@dataclass(frozen=True)
class ActorObservation:
    """Must originate from ONE authenticated response in future runtime."""
    id: int
    login: str


@dataclass(frozen=True)
class RepositoryObservation:
    id: str
    full_name: str
    visibility: str
    default_branch: str
    can_read: bool


class MetadataFixture(Protocol):
    """A test-injected provider, not a production connector or credential."""

    def current_actor(self) -> ActorObservation: ...
    def repository_metadata(self, fixed_repository: str) -> RepositoryObservation: ...
    def branch_head(self, fixed_repository: str, fixed_ref: str) -> str: ...


@dataclass(frozen=True)
class FixtureOutcome:
    status: str
    reason: str
    # Only a minimal, non-content receipt after successful fixture checks.
    request_id: str | None = None
    repository_id: str | None = None
    observed_head: str | None = None
    catalog_sha256: str | None = None


def _pins_wellformed(pins: object) -> bool:
    return (
        type(pins) is StartupPins
        and type(pins.operator_id) is int and pins.operator_id > 0
        and type(pins.operator_login) is str and bool(pins.operator_login)
        and type(pins.repository_id) is str and pins.repository_id.isdecimal()
        and type(pins.repository) is str and _REPO.fullmatch(pins.repository) is not None
        and type(pins.ref) is str and bool(pins.ref)
        and type(pins.catalog_commit_sha) is str and _SHA.fullmatch(pins.catalog_commit_sha) is not None
        and type(pins.catalog_sha256) is str and _HASH.fullmatch(pins.catalog_sha256) is not None
    )


def _metadata_matches(meta: object, pins: StartupPins) -> bool:
    return (
        type(meta) is RepositoryObservation
        and type(meta.id) is str and meta.id == pins.repository_id
        and type(meta.full_name) is str and meta.full_name == pins.repository
        and type(meta.visibility) is str and meta.visibility in ("public", "private")
        and type(meta.default_branch) is str and meta.default_branch == pins.ref
        and type(meta.can_read) is bool and meta.can_read is True
    )


def verify_offline_metadata_fixture(
    raw_request: str,
    raw_catalog: str,
    pins: StartupPins,
    fixture: MetadataFixture,
) -> FixtureOutcome:
    """Simulate one fixed read-only metadata handler and freshness checks.

    The injected fixture and pinned config are FAKE/externally supplied; this
    function cannot assert real authenticated identity, GitHub permissions,
    catalog-to-commit blob proof, shared idempotency or live execution.
    """
    def deny(reason: str) -> FixtureOutcome:
        return FixtureOutcome("BLOCKED", reason)

    if not _pins_wellformed(pins):
        return deny("INVALID_STARTUP_PINS")
    if type(raw_catalog) is not str:
        return deny("CATALOG_BYTES_INVALID")
    try:
        catalog_bytes = raw_catalog.encode("utf-8")
    except UnicodeError:
        return deny("CATALOG_BYTES_INVALID")
    if len(catalog_bytes) > 8192 or sha256(catalog_bytes).hexdigest() != pins.catalog_sha256:
        return deny("CATALOG_DIGEST_MISMATCH")
    try:
        request = parse_json_object(raw_request)
        catalog = parse_json_object(raw_catalog)
    except ValueError:
        return deny("INVALID_OR_DUPLICATE_JSON")

    # The provider is test-only and supplied by the caller. Replacing it with
    # a live connector REQUIRES separately admitted security work.
    try:
        actor = fixture.current_actor()
        metadata_before = fixture.repository_metadata(pins.repository)
        head_before = fixture.branch_head(pins.repository, pins.ref)
    except Exception:
        return deny("FIXTURE_OBSERVATION_FAILED")

    if (
        type(actor) is not ActorObservation
        or type(actor.id) is not int or actor.id != pins.operator_id
        or type(actor.login) is not str or actor.login != pins.operator_login
    ):
        return deny("ACTOR_MISMATCH")
    if not _metadata_matches(metadata_before, pins):
        return deny("TARGET_OR_PERMISSION_MISMATCH")
    if type(head_before) is not str or _SHA.fullmatch(head_before) is None:
        return deny("INVALID_HEAD_OBSERVATION")

    observation = ObservedReadContext(
        principal_id=actor.id,
        actor_login=actor.login,
        repository=metadata_before.full_name,
        default_branch=metadata_before.default_branch,
        actual_head_sha=head_before,
        visibility=metadata_before.visibility,
        can_read=metadata_before.can_read,
        handler="github.repository_metadata",
    )
    admission = inspect_read_request(
        request,
        catalog,
        catalog_commit_sha=pins.catalog_commit_sha,
        observation=observation,
    )
    if admission.status != "PREFLIGHT_ONLY":
        return deny("G1_G2A_DID_NOT_ADMIT")

    try:
        metadata_after = fixture.repository_metadata(pins.repository)
        head_after = fixture.branch_head(pins.repository, pins.ref)
    except Exception:
        return deny("SECOND_OBSERVATION_UNKNOWN")

    if not _metadata_matches(metadata_after, pins):
        return deny("TARGET_CHANGED")
    if (
        type(head_after) is not str
        or _SHA.fullmatch(head_after) is None
        or head_after != head_before
    ):
        return deny("STALE_HEAD")

    # Deliberately never returns ADMITTED, RUNNING or SUCCEEDED.
    return FixtureOutcome(
        "SIMULATION_ONLY",
        "FAKE_PROVIDER_MATCHED_NOT_EXECUTED",
        request_id=admission.request_id,
        repository_id=metadata_after.id,
        observed_head=head_after,
        catalog_sha256=pins.catalog_sha256,
    )
