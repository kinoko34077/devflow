"""Versioned, in-process mapped-read contract; never a permission grant."""
from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

SCHEMA = "mapped-read.v1"
RESULT_SCHEMA = "mapped-read-result.v1"
BATCH_SCHEMA = "mapped-read-batch.v1"
BATCH_RESULT_SCHEMA = "mapped-read-batch-result.v1"
# Syntax only; the trusted caller owns the exact authorization scope.
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z")


class MappedReadError(ValueError):
    """A finite, non-secret input or adapter contract failure."""


def parse_utc_timestamp(value: Any, *, seconds_only: bool = False) -> datetime:
    if (type(value) is not str or not _UTC.fullmatch(value)
            or (seconds_only and "." in value)):
        raise MappedReadError("INVALID_UTC_TIMESTAMP")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise MappedReadError("INVALID_UTC_TIMESTAMP") from None


@dataclass(frozen=True)
class SourceObservation:
    items: tuple[Mapping[str, Any], ...]
    status: str
    source_status: str
    reason_codes: tuple[str, ...] = ()
    source_revision: str | None = None
    snapshot_atomic: bool = False
    requires_source_revalidation: bool = True
    read_units: int = 0


@dataclass(frozen=True)
class SourceMap:
    """Trusted owner registration; never construct from the query packet."""
    owner: str
    time_field: str | None
    fields: frozenset[str]
    prepare: Callable[[str | None, str | None, dict, dict],
                      Callable[[str], SourceObservation]]
    # Explicit owner opt-in: observations may share a single batch's freshness.
    batch_reusable: bool = False


def _keys(value: Any, required: set[str], optional: set[str] = frozenset()) -> dict:
    if (type(value) is not dict or not required <= value.keys()
            or not value.keys() <= required | optional):
        raise MappedReadError("INVALID_REQUEST_SHAPE")
    return value


@dataclass
class _BatchState:
    observations: dict[str, tuple[SourceObservation, str]]
    source_reads: int = 0
    reused_observations: int = 0


def read_mapped(packet: dict, *, sources: Mapping[str, SourceMap],
                allowed_repositories: Collection[str]) -> dict[str, Any]:
    """Read a fresh independent request; no retained acquisition state."""
    return _read_mapped(packet, sources=sources, allowed_repositories=allowed_repositories)


def read_mapped_batch(packet: dict, *, sources: Mapping[str, SourceMap],
                      allowed_repositories: Collection[str]) -> dict[str, Any]:
    """Share successful compatible source observations only within this call.

    A batch explicitly accepts the same observation for matching acquisition
    parameters. It is not an atomic snapshot or a fresh authority check.
    Never reuse across callers, batches, registries, credentials, or processes.
    """
    envelope = _keys(packet, {"schema_version", "requests"})
    if envelope["schema_version"] != BATCH_SCHEMA:
        raise MappedReadError("UNSUPPORTED_SCHEMA")
    requests = envelope["requests"]
    if type(requests) is not list or not requests:
        raise MappedReadError("INVALID_REQUEST_SHAPE")
    if isinstance(allowed_repositories, (str, bytes, Mapping)):
        raise MappedReadError("INVALID_AUTHORIZED_SCOPE")
    scope = frozenset(allowed_repositories)
    registry = dict(sources)
    batch = _BatchState({})
    results = []
    for request in requests:
        try:
            result = _read_mapped(request, sources=registry,
                                  allowed_repositories=scope, batch=batch)
        except MappedReadError:
            # Adapter-defined exception text is not an external diagnostic.
            results.append({"status": "BLOCKED", "reason_code": "INVALID_MAPPED_REQUEST"})
        else:
            results.append({"status": result["coverage"]["status"], "result": result})
    statuses = {r["status"] for r in results}
    return {
        "schema_version": BATCH_RESULT_SCHEMA,
        "status": ("BLOCKED" if statuses == {"BLOCKED"} else
                   "BOUNDED_READ" if statuses == {"BOUNDED_READ"} else "PARTIAL_UNKNOWN"),
        "results": results,
        "source_reads": batch.source_reads,
        "reused_observations": batch.reused_observations,
        "snapshot_atomic": False,
        "complete_source_universe": False,
        "can_authorize_execution": False,
    }


def _read_mapped(packet: dict, *, sources: Mapping[str, SourceMap],
                 allowed_repositories: Collection[str],
                 batch: _BatchState | None = None) -> dict[str, Any]:
    """Prepare once, then execute only a registered read for authorized repos.

    The caller supplies the registry and scope through trusted application code.
    The packet cannot choose transport, credentials, a URL, or an implementation.
    No persistent state, cache, cursor, public MCP entry, or source authority.
    """
    request = _keys(packet, {"schema_version", "time", "target", "response"}, {"budget"})
    if request["schema_version"] != SCHEMA:
        raise MappedReadError("UNSUPPORTED_SCHEMA")
    target = _keys(request["target"], {"dataset", "repositories"}, {"filters"})
    dataset = target["dataset"]
    if type(dataset) is not str or dataset not in sources:
        raise MappedReadError("UNSUPPORTED_DATASET")
    source = sources[dataset]
    repos = target["repositories"]
    if (type(repos) is not list or not repos or any(
        type(r) is not str or not _REPOSITORY.fullmatch(r)
        or any(part in (".", "..") for part in r.split("/")) for r in repos
    ) or len({r.casefold() for r in repos}) != len(repos)):
        raise MappedReadError("INVALID_REPOSITORY_SCOPE")
    if isinstance(allowed_repositories, (str, bytes, Mapping)):
        raise MappedReadError("INVALID_AUTHORIZED_SCOPE")
    if any(r not in allowed_repositories for r in repos):
        raise MappedReadError("REPOSITORY_OUTSIDE_AUTHORIZED_SCOPE")

    time = request["time"]
    lower = upper = None
    if time is not None:
        time = _keys(time, {"field"}, {"from_inclusive", "to_exclusive"})
        if source.time_field is None or time["field"] != source.time_field:
            raise MappedReadError("UNSUPPORTED_TIME_FIELD")
        lower, upper = time.get("from_inclusive"), time.get("to_exclusive")
        lo = parse_utc_timestamp(lower) if lower is not None else None
        hi = parse_utc_timestamp(upper) if upper is not None else None
        if lo is not None and hi is not None and lo >= hi:
            raise MappedReadError("INVALID_TIME_RANGE")

    response = _keys(request["response"], {"fields"}, {"limit"})
    fields = response["fields"]
    if (type(fields) is not list or not fields or any(
        type(f) is not str or f not in source.fields for f in fields
    ) or len(set(fields)) != len(fields)):
        raise MappedReadError("UNSUPPORTED_RESPONSE_FIELDS")
    limit = response.get("limit")
    if limit is not None and (type(limit) is not int or limit <= 0):
        raise MappedReadError("INVALID_RESPONSE_LIMIT")
    filters, budget = target.get("filters", {}), request.get("budget", {})
    if type(filters) is not dict or type(budget) is not dict:
        raise MappedReadError("INVALID_REQUEST_SHAPE")
    try:
        encoded = json.dumps(request, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise MappedReadError("INVALID_REQUEST_JSON") from None

    # All common input and owner-specific options are validated before any read.
    read = source.prepare(lower, upper, filters, budget)
    items = []
    observations = []
    matched = 0
    for repo in repos:
        key = None
        cached = None
        if batch is not None and source.batch_reusable:
            # response.fields/limit do not affect acquisition. The registry
            # and scope are fixed by the trusted batch caller, not the packet.
            key = json.dumps([dataset, repo, lower, upper, filters, budget],
                             sort_keys=True, separators=(",", ":"), allow_nan=False)
            cached = batch.observations.get(key)
            if cached is not None and not all(
                    f in row for row in cached[0].items for f in fields):
                cached = None
        reused = cached is not None
        if cached is not None:
            observed, source_observed_at = cached
            batch.reused_observations += 1
        else:
            if batch is not None:
                batch.source_reads += 1
            observed = read(repo)
            source_observed_at = datetime.now(timezone.utc).isoformat()
        if (not isinstance(observed, SourceObservation)
                or observed.status not in ("BOUNDED_READ", "PARTIAL_UNKNOWN", "BLOCKED")
                or type(observed.items) is not tuple
                or (observed.status == "BLOCKED" and observed.items)):
            observed = SourceObservation((), "BLOCKED", "INVALID_SOURCE_OBSERVATION",
                                         ("INVALID_SOURCE_OBSERVATION",))
        projected = []
        for row in observed.items:
            if not isinstance(row, Mapping) or any(f not in row for f in fields):
                reason = "MISSING_SOURCE_FIELD"
                break
            try:
                # Copy only the requested attributes into a JSON-safe result.
                # Nested attribute semantics remain the adapter owner's duty.
                record = json.loads(json.dumps({f: row[f] for f in fields}, allow_nan=False))
            except (TypeError, ValueError, OverflowError):
                reason = "INVALID_SOURCE_FIELD_VALUE"
                break
            projected.append({"repository": repo, "record": record})
        else:
            reason = None
        if reason is not None:
            # Do not retain a prefix from an invalid source. Other repositories
            # remain available; the broken source is explicitly BLOCKED.
            observed = SourceObservation((), "BLOCKED", "SOURCE_PROJECTION_INVALID",
                                         (reason,), read_units=observed.read_units)
            projected = []
        if key is not None:
            if observed.status != "BOUNDED_READ":
                batch.observations.pop(key, None)
            elif not reused:
                # Keep only allowed fields; no raw source body or credentials.
                # Copy JSON values so projections cannot mutate cached input.
                try:
                    saved = tuple(json.loads(json.dumps(
                        {f: row[f] for f in source.fields if f in row},
                        allow_nan=False)) for row in observed.items)
                except (TypeError, ValueError, OverflowError, RecursionError):
                    batch.observations.pop(key, None)
                else:
                    batch.observations[key] = (
                        replace(observed, items=saved), source_observed_at)
        matched += len(projected)
        remaining = None if limit is None else max(0, limit - len(items))
        items.extend(projected if remaining is None else projected[:remaining])
        observations.append({
            "repository": repo, "status": observed.status,
            "source_status": observed.source_status,
            "reason_codes": list(observed.reason_codes),
            "source_revision": observed.source_revision,
            "snapshot_atomic": observed.snapshot_atomic,
            "requires_source_revalidation": observed.requires_source_revalidation,
            "read_units": observed.read_units, "matched": len(observed.items),
            **({"reused_observation": reused, "source_observed_at": source_observed_at,
                "observed_new_read_units": 0 if reused else observed.read_units}
               if batch is not None else {}),
        })

    limited = matched > len(items)
    statuses = {o["status"] for o in observations}
    status = ("BLOCKED" if statuses == {"BLOCKED"} else
              "PARTIAL_UNKNOWN" if limited or statuses != {"BOUNDED_READ"} else
              "BOUNDED_READ")
    return {
        "schema_version": RESULT_SCHEMA, "dataset": dataset,
        "query_signature": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "source_owner": source.owner,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "coverage": {"status": status, "repositories": observations,
                     "response_limited": limited, "matched": matched},
        "complete_source_universe": False,
        "can_authorize_execution": False,
        "requires_source_revalidation": any(
            o["requires_source_revalidation"] for o in observations),
    }
