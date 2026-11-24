"""Versioned, in-process mapped-read contract; never a permission grant."""
from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from tools.kaep_repository_validation import REPOSITORY

SCHEMA = "mapped-read.v1"
RESULT_SCHEMA = "mapped-read-result.v1"
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


def _keys(value: Any, required: set[str], optional: set[str] = frozenset()) -> dict:
    if (type(value) is not dict or not required <= value.keys()
            or not value.keys() <= required | optional):
        raise MappedReadError("INVALID_REQUEST_SHAPE")
    return value


def read_mapped(packet: dict, *, sources: Mapping[str, SourceMap],
                allowed_repositories: Collection[str]) -> dict[str, Any]:
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
        type(r) is not str or not REPOSITORY.fullmatch(r)
        or r.rsplit("/", 1)[1] in (".", "..") for r in repos
    ) or len({r.casefold() for r in repos}) != len(repos)):
        raise MappedReadError("INVALID_REPOSITORY_SCOPE")
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
    except (TypeError, ValueError):
        raise MappedReadError("INVALID_REQUEST_JSON") from None

    # All common input and owner-specific options are validated before any read.
    read = source.prepare(lower, upper, filters, budget)
    items = []
    observations = []
    matched = 0
    for repo in repos:
        observed = read(repo)
        if (not isinstance(observed, SourceObservation)
                or observed.status not in ("BOUNDED_READ", "PARTIAL_UNKNOWN", "BLOCKED")
                or (observed.status == "BLOCKED" and observed.items)):
            raise MappedReadError("INVALID_SOURCE_OBSERVATION")
        for row in observed.items:
            if not isinstance(row, Mapping) or any(f not in row for f in fields):
                raise MappedReadError("MISSING_SOURCE_FIELD")
            matched += 1
            if limit is None or len(items) < limit:
                items.append({"repository": repo, "record": {f: row[f] for f in fields}})
        observations.append({
            "repository": repo, "status": observed.status,
            "source_status": observed.source_status,
            "reason_codes": list(observed.reason_codes),
            "source_revision": observed.source_revision,
            "snapshot_atomic": observed.snapshot_atomic,
            "requires_source_revalidation": observed.requires_source_revalidation,
            "read_units": observed.read_units, "matched": len(observed.items),
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
