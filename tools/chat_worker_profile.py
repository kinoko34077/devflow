"""Per-session worker profile builder (devflow#190 Phase B, #195).

Pure and deterministic.  A manually-started chat records what it could
actually verify about itself as a closed list of probe results; this module
turns those observations into the identity/profile fields of a
``chat-worker-bootstrap-request.v1`` request.  Tags come only from probes
that passed.  The provider or model name never grants a tag.

Normative spec: ``docs/spec/CHAT_WORKER_PROFILES.md``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from tools import chat_worker_bootstrap as contract

OBSERVATION_SCHEMA = "chat-worker-observation.v1"
PROFILE_TTL = timedelta(minutes=60)

# Closed probe registry: probe -> (field, tag).  A probe is a concrete check
# the session performed itself (see the spec for how each one is verified).
PROBES: dict[str, tuple[str, str]] = {
    # capabilities: things the session can execute
    "exec.python3": ("capabilities", "python"),
    "exec.git": ("capabilities", "git"),
    "exec.node": ("capabilities", "node"),
    "exec.unittest": ("capabilities", "tests"),
    "fs.repository_checkout": ("capabilities", "repo-checkout"),
    # environment: where the session runs
    "os.linux": ("environment", "linux"),
    "os.macos": ("environment", "macos"),
    "os.windows": ("environment", "windows"),
    "net.github_api": ("environment", "github-network"),
    "lane.github_actions": ("environment", "github-actions-lane"),
    # tool surfaces: availability facts, never capabilities
    "surface.github_read": ("tool_surfaces", "github:read"),
    "surface.github_write": ("tool_surfaces", "github:write"),
    "surface.coordinator_claim": ("tool_surfaces", "coordinator:claim"),
}

# Initial per-provider probe checklists.  They say WHICH probes a session of
# that provider must attempt and report (true or false).  They grant nothing:
# every tag still requires its probe to have passed.
PROVIDER_CHECKLISTS: dict[str, tuple[str, ...]] = {
    "codex": tuple(sorted(PROBES)),
    "claude": tuple(sorted(PROBES)),
    # An ordinary ChatGPT chat usually has no shell; it must still report the
    # shell probes (normally false) so the absence is explicit evidence.
    "chatgpt": tuple(sorted(PROBES)),
}

_SESSION_ID = re.compile(r"^(codex|claude|chatgpt)-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}$")


class ProfileError(ValueError):
    pass


def _check(condition: bool, detail: str) -> None:
    if not condition:
        raise ProfileError(detail)


def _utc(value: object, field: str) -> datetime:
    _check(isinstance(value, str) and value.endswith("Z"), f"{field} must be RFC3339 UTC")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ProfileError(f"{field} must be RFC3339 UTC") from exc


def new_session_id(worker_system: str, started_at: datetime, entropy_hex: str) -> str:
    """Session id generated ONCE when the chat first bootstraps.

    ``<system>-<YYYYMMDDTHHMMSSZ>-<6 hex>``; the chat reuses it for its whole
    lifetime and records it as ``Execution-Session-ID`` in its Session Record.
    """

    _check(worker_system in contract.WORKER_SYSTEMS, "unknown worker_system")
    _check(started_at.tzinfo is not None and started_at.utcoffset() == timedelta(0), "started_at must be UTC")
    _check(re.fullmatch(r"[0-9a-f]{6}", entropy_hex or "") is not None, "entropy_hex must be 6 lowercase hex characters")
    return f"{worker_system}-{started_at.strftime('%Y%m%dT%H%M%SZ')}-{entropy_hex}"


def attempt_id(worker_session_id: str, cycle: int) -> str:
    """Discovery-cycle identity: ``<worker_session_id>:c<N>``, N >= 1."""

    _check(type(cycle) is int and cycle >= 1, "cycle must be a positive integer")
    return f"{worker_session_id}:c{cycle}"


def build_request(
    observation: object,
    *,
    target_repository: str | None,
    work_intent: str | None,
    now: datetime,
) -> dict[str, Any]:
    """Observation -> validated ``chat-worker-bootstrap-request.v1``."""

    _check(isinstance(observation, dict), "observation must be an object")
    _check(observation.get("schema_version") == OBSERVATION_SCHEMA, "unsupported observation schema_version")
    allowed = {"schema_version", "worker_system", "worker_session_id", "cycle", "observed_at", "probes"}
    _check(not (set(observation) - allowed), "unknown observation fields")
    system = observation.get("worker_system")
    _check(system in contract.WORKER_SYSTEMS, "unknown worker_system")
    session = observation.get("worker_session_id")
    _check(isinstance(session, str) and _SESSION_ID.fullmatch(session) is not None, "worker_session_id is malformed")
    _check(session.startswith(system + "-"), "worker_session_id does not belong to worker_system")
    observed = _utc(observation.get("observed_at"), "observed_at")
    _check(now.tzinfo is not None and now.utcoffset() == timedelta(0), "now must be UTC")
    _check(observed <= now, "observation is from the future")
    _check(now - observed <= PROFILE_TTL, "observation is stale; re-run the probes")

    probes = observation.get("probes")
    _check(isinstance(probes, dict), "probes must be an object of probe -> boolean")
    unknown = set(probes) - set(PROBES)
    _check(not unknown, f"unknown probes: {sorted(unknown)}")
    missing = set(PROVIDER_CHECKLISTS[system]) - set(probes)
    _check(not missing, f"checklist probes not reported: {sorted(missing)}")
    _check(all(type(value) is bool for value in probes.values()), "probe results must be booleans")

    fields: dict[str, list[str]] = {"capabilities": [], "environment": [], "tool_surfaces": []}
    for probe in sorted(probes):
        if probes[probe]:
            field, tag = PROBES[probe]
            fields[field].append(tag)
    os_tags = [tag for tag in fields["environment"] if tag in ("linux", "macos", "windows")]
    _check(len(os_tags) <= 1, "contradictory operating-system probes")

    request = {
        "schema_version": contract.REQUEST_SCHEMA,
        "target_repository": target_repository,
        "work_intent": work_intent,
        "worker_system": system,
        "worker_session_id": session,
        "execution_attempt_id": attempt_id(session, observation.get("cycle")),
        "capabilities": sorted(fields["capabilities"]),
        "environment": sorted(fields["environment"]),
        "tool_surfaces": sorted(fields["tool_surfaces"]),
        "observed_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    try:
        contract.normalize_request(request)
    except contract.ContractError as error:
        raise ProfileError(f"profile does not form a valid request: {error.detail}") from error
    return request
