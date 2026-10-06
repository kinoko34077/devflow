from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


BASELINE_SCHEMA = "maintenance-common-baseline.v1"
CATALOG_SCHEMA = "maintenance-catalog.v1"
RISKS = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})
DEPTHS = frozenset({"CONTROL", "STANDARD", "DEEP"})
LIFECYCLES = frozenset({"ACTIVE", "MERGED", "SUPERSEDED", "RETIRED"})
ROLLOUTS = frozenset({"DISABLED", "PILOT", "ENABLED"})
SCOPE_KINDS = frozenset(
    {"repository", "path", "component", "runtime_boundary", "workflow", "external_system"}
)
CADENCE_CLASSES = frozenset({"GENERAL", "SECURITY"})
FRESHNESS_CLASSES = frozenset({"FAST", "NORMAL", "SLOW"})


class MaintenanceCatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Lens:
    id: str
    title: str


@dataclass(frozen=True)
class Scope:
    kind: str
    selector: str


@dataclass(frozen=True)
class SlotSpec:
    slot_id: str
    title: str
    lifecycle: str
    scope: Scope
    lens: str
    coverage_key: str
    cadence_class: str
    minimum_depth: str
    external_freshness_class: str
    description: str


@dataclass(frozen=True)
class CommonSlotOverride:
    slot_id: str
    rationale: str
    lifecycle: str | None = None
    cadence_class: str | None = None
    minimum_depth: str | None = None
    external_freshness_class: str | None = None


@dataclass(frozen=True)
class ScopeRiskOverride:
    scope: Scope
    risk: str


@dataclass(frozen=True)
class CommonBaseline:
    schema_version: str
    catalog_schema_version: str
    lenses: tuple[Lens, ...]
    risk_policy: Mapping[str, Mapping[str, int]]
    freshness_classes: Mapping[str, Mapping[str, int]]
    selector_weights: Mapping[str, int]
    common_slots: tuple[SlotSpec, ...]


@dataclass(frozen=True)
class RepositoryCatalog:
    schema_version: str
    repository: str
    baseline: str
    rollout: str
    risk_profile: str
    scope_risk_overrides: tuple[ScopeRiskOverride, ...]
    repository_lenses: tuple[Lens, ...]
    common_slot_overrides: tuple[CommonSlotOverride, ...]
    repository_slots: tuple[SlotSpec, ...]


@dataclass(frozen=True)
class ResolvedSlot:
    repository: str
    slot_id: str
    title: str
    lifecycle: str
    scope: Scope
    lens: str
    coverage_key: str
    risk: str
    cadence_class: str
    minimum_depth: str
    external_freshness_class: str
    description: str
    source: str


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MaintenanceCatalogError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json_yaml(path: Path | str, label: str) -> dict[str, Any]:
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise MaintenanceCatalogError(f"cannot read {label}: {source}") from exc
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except MaintenanceCatalogError:
        raise
    except (json.JSONDecodeError, TypeError) as exc:
        raise MaintenanceCatalogError(f"{label} must use the JSON-compatible YAML 1.2 subset") from exc
    if not isinstance(value, dict):
        raise MaintenanceCatalogError(f"{label} must be an object")
    return value


def _closed_object(value: object, label: str, allowed: set[str], required: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MaintenanceCatalogError(f"{label} must be an object")
    keys = set(value)
    unknown = sorted(keys - allowed)
    if unknown:
        raise MaintenanceCatalogError(f"{label} has unknown field(s): {', '.join(unknown)}")
    missing = sorted(required - keys)
    if missing:
        raise MaintenanceCatalogError(f"{label} is missing field(s): {', '.join(missing)}")
    return dict(value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MaintenanceCatalogError(f"{label} must be a non-empty string")
    return value.strip()


def _enum(value: object, label: str, allowed: frozenset[str]) -> str:
    text = _string(value, label)
    if text not in allowed:
        raise MaintenanceCatalogError(f"invalid {label}: {text!r}")
    return text


def _integer(value: object, label: str, *, positive: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise MaintenanceCatalogError(f"{label} must be an integer")
    if positive and value <= 0:
        raise MaintenanceCatalogError(f"{label} must be positive")
    return value


def _scope(value: object, label: str) -> Scope:
    item = _closed_object(
        value,
        label,
        {"kind", "selector"},
        {"kind", "selector"},
    )
    return Scope(
        kind=_enum(item["kind"], f"{label}.kind", SCOPE_KINDS),
        selector=_string(item["selector"], f"{label}.selector"),
    )


def _lens(value: object, label: str) -> Lens:
    item = _closed_object(value, label, {"id", "title"}, {"id", "title"})
    return Lens(
        id=_string(item["id"], f"{label}.id"),
        title=_string(item["title"], f"{label}.title"),
    )


def _slot(value: object, label: str, lens_ids: set[str]) -> SlotSpec:
    allowed = {
        "slot_id", "title", "lifecycle", "scope", "lens", "coverage_key",
        "cadence_class", "minimum_depth", "external_freshness_class", "description",
    }
    item = _closed_object(value, label, allowed, allowed)
    lens = _string(item["lens"], f"{label}.lens")
    if lens not in lens_ids:
        raise MaintenanceCatalogError(f"{label}.lens references unknown lens: {lens}")
    return SlotSpec(
        slot_id=_string(item["slot_id"], f"{label}.slot_id"),
        title=_string(item["title"], f"{label}.title"),
        lifecycle=_enum(item["lifecycle"], f"{label}.lifecycle", LIFECYCLES),
        scope=_scope(item["scope"], f"{label}.scope"),
        lens=lens,
        coverage_key=_string(item["coverage_key"], f"{label}.coverage_key"),
        cadence_class=_enum(item["cadence_class"], f"{label}.cadence_class", CADENCE_CLASSES),
        minimum_depth=_enum(item["minimum_depth"], f"{label}.minimum_depth", DEPTHS),
        external_freshness_class=_enum(
            item["external_freshness_class"],
            f"{label}.external_freshness_class",
            FRESHNESS_CLASSES,
        ),
        description=_string(item["description"], f"{label}.description"),
    )


def _unique(values: tuple[object, ...], key, label: str) -> None:
    seen: set[object] = set()
    for value in values:
        identity = key(value)
        if identity in seen:
            raise MaintenanceCatalogError(f"duplicate {label}: {identity}")
        seen.add(identity)


def load_common_baseline(path: Path | str) -> CommonBaseline:
    data = _load_json_yaml(path, "maintenance common baseline")
    allowed = {
        "schema_version", "catalog_schema_version", "lenses", "risk_policy",
        "freshness_classes", "selector_weights", "common_slots",
    }
    data = _closed_object(data, "maintenance common baseline", allowed, allowed)
    if data["schema_version"] != BASELINE_SCHEMA:
        raise MaintenanceCatalogError(f"unsupported baseline schema_version: {data['schema_version']!r}")
    if data["catalog_schema_version"] != CATALOG_SCHEMA:
        raise MaintenanceCatalogError(
            f"unsupported catalog_schema_version: {data['catalog_schema_version']!r}"
        )

    raw_lenses = data["lenses"]
    if not isinstance(raw_lenses, list):
        raise MaintenanceCatalogError("baseline lenses must be an array")
    lenses = tuple(_lens(value, f"lenses[{index}]") for index, value in enumerate(raw_lenses))
    _unique(lenses, lambda item: item.id, "lens id")
    lens_ids = {item.id for item in lenses}
    if "security" not in lens_ids:
        raise MaintenanceCatalogError("baseline must define Security lens")

    raw_risk = data["risk_policy"]
    if not isinstance(raw_risk, dict) or set(raw_risk) != RISKS:
        raise MaintenanceCatalogError("risk_policy must define LOW, MEDIUM, HIGH, CRITICAL")
    risk_policy: dict[str, dict[str, int]] = {}
    risk_fields = {
        "general_standard_days", "security_standard_days", "deep_target_days", "cooldown_hours"
    }
    for risk in sorted(RISKS):
        item = _closed_object(raw_risk[risk], f"risk_policy.{risk}", risk_fields, risk_fields)
        risk_policy[risk] = {
            field: _integer(item[field], f"risk_policy.{risk}.{field}", positive=True)
            for field in sorted(risk_fields)
        }

    raw_freshness = data["freshness_classes"]
    if not isinstance(raw_freshness, dict) or set(raw_freshness) != FRESHNESS_CLASSES:
        raise MaintenanceCatalogError("freshness_classes must define FAST, NORMAL, SLOW")
    freshness: dict[str, dict[str, int]] = {}
    for name in sorted(FRESHNESS_CLASSES):
        item = _closed_object(raw_freshness[name], f"freshness_classes.{name}", {"days"}, {"days"})
        freshness[name] = {"days": _integer(item["days"], f"freshness_classes.{name}.days", positive=True)}

    raw_weights = data["selector_weights"]
    if not isinstance(raw_weights, dict) or not raw_weights:
        raise MaintenanceCatalogError("selector_weights must be a non-empty object")
    selector_weights = {
        _string(key, "selector weight name"): _integer(value, f"selector_weights.{key}")
        for key, value in raw_weights.items()
    }

    raw_slots = data["common_slots"]
    if not isinstance(raw_slots, list):
        raise MaintenanceCatalogError("common_slots must be an array")
    slots = tuple(
        _slot(value, f"common_slots[{index}]", lens_ids)
        for index, value in enumerate(raw_slots)
    )
    _unique(slots, lambda item: item.slot_id, "slot_id")

    return CommonBaseline(
        schema_version=BASELINE_SCHEMA,
        catalog_schema_version=CATALOG_SCHEMA,
        lenses=lenses,
        risk_policy=risk_policy,
        freshness_classes=freshness,
        selector_weights=selector_weights,
        common_slots=slots,
    )


def _common_override(value: object, label: str, known_slot_ids: set[str]) -> CommonSlotOverride:
    allowed = {
        "slot_id", "lifecycle", "cadence_class", "minimum_depth",
        "external_freshness_class", "rationale",
    }
    item = _closed_object(value, label, allowed, {"slot_id", "rationale"})
    slot_id = _string(item["slot_id"], f"{label}.slot_id")
    if slot_id not in known_slot_ids:
        raise MaintenanceCatalogError(f"{label}.slot_id references unknown common slot: {slot_id}")
    return CommonSlotOverride(
        slot_id=slot_id,
        rationale=_string(item["rationale"], f"{label}.rationale"),
        lifecycle=(
            _enum(item["lifecycle"], f"{label}.lifecycle", LIFECYCLES)
            if "lifecycle" in item else None
        ),
        cadence_class=(
            _enum(item["cadence_class"], f"{label}.cadence_class", CADENCE_CLASSES)
            if "cadence_class" in item else None
        ),
        minimum_depth=(
            _enum(item["minimum_depth"], f"{label}.minimum_depth", DEPTHS)
            if "minimum_depth" in item else None
        ),
        external_freshness_class=(
            _enum(
                item["external_freshness_class"],
                f"{label}.external_freshness_class",
                FRESHNESS_CLASSES,
            )
            if "external_freshness_class" in item else None
        ),
    )


def load_repository_catalog(path: Path | str, baseline: CommonBaseline) -> RepositoryCatalog:
    data = _load_json_yaml(path, "maintenance catalog")
    allowed = {
        "schema_version", "repository", "baseline", "rollout", "risk_profile",
        "scope_risk_overrides", "repository_lenses", "common_slot_overrides",
        "repository_slots",
    }
    data = _closed_object(data, "maintenance catalog", allowed, allowed)
    if data["schema_version"] != CATALOG_SCHEMA:
        raise MaintenanceCatalogError(f"unsupported schema_version: {data['schema_version']!r}")
    if data["baseline"] != baseline.schema_version:
        raise MaintenanceCatalogError(
            f"catalog baseline {data['baseline']!r} does not match {baseline.schema_version!r}"
        )

    repository = _string(data["repository"], "repository")
    if repository.count("/") != 1 or any(not part for part in repository.split("/")):
        raise MaintenanceCatalogError("repository must be owner/name")

    raw_repo_lenses = data["repository_lenses"]
    if not isinstance(raw_repo_lenses, list):
        raise MaintenanceCatalogError("repository_lenses must be an array")
    repo_lenses = tuple(
        _lens(value, f"repository_lenses[{index}]")
        for index, value in enumerate(raw_repo_lenses)
    )
    combined_lenses = tuple(baseline.lenses) + repo_lenses
    _unique(combined_lenses, lambda item: item.id, "lens id")
    lens_ids = {item.id for item in combined_lenses}

    raw_scope_risk = data["scope_risk_overrides"]
    if not isinstance(raw_scope_risk, list):
        raise MaintenanceCatalogError("scope_risk_overrides must be an array")
    scope_risk = []
    for index, value in enumerate(raw_scope_risk):
        item = _closed_object(
            value,
            f"scope_risk_overrides[{index}]",
            {"scope", "risk"},
            {"scope", "risk"},
        )
        scope_risk.append(
            ScopeRiskOverride(
                scope=_scope(item["scope"], f"scope_risk_overrides[{index}].scope"),
                risk=_enum(item["risk"], f"scope_risk_overrides[{index}].risk", RISKS),
            )
        )
    scope_risk_tuple = tuple(scope_risk)
    _unique(scope_risk_tuple, lambda item: (item.scope.kind, item.scope.selector), "scope risk override")

    known_common = {slot.slot_id for slot in baseline.common_slots}
    raw_common_overrides = data["common_slot_overrides"]
    if not isinstance(raw_common_overrides, list):
        raise MaintenanceCatalogError("common_slot_overrides must be an array")
    common_overrides = tuple(
        _common_override(value, f"common_slot_overrides[{index}]", known_common)
        for index, value in enumerate(raw_common_overrides)
    )
    _unique(common_overrides, lambda item: item.slot_id, "common slot override")

    raw_repo_slots = data["repository_slots"]
    if not isinstance(raw_repo_slots, list):
        raise MaintenanceCatalogError("repository_slots must be an array")
    repo_slots = tuple(
        _slot(value, f"repository_slots[{index}]", lens_ids)
        for index, value in enumerate(raw_repo_slots)
    )
    _unique(repo_slots, lambda item: item.slot_id, "slot_id")
    collisions = known_common & {slot.slot_id for slot in repo_slots}
    if collisions:
        raise MaintenanceCatalogError(f"repository slot collides with common slot_id: {sorted(collisions)[0]}")

    active_coverage: set[tuple[str, str, str, str]] = set()
    for slot in repo_slots:
        if slot.lifecycle != "ACTIVE":
            continue
        key = (slot.coverage_key, slot.scope.kind, slot.scope.selector, slot.lens)
        if key in active_coverage:
            raise MaintenanceCatalogError(f"duplicate active coverage: {slot.coverage_key}")
        active_coverage.add(key)

    catalog = RepositoryCatalog(
        schema_version=CATALOG_SCHEMA,
        repository=repository,
        baseline=baseline.schema_version,
        rollout=_enum(data["rollout"], "rollout", ROLLOUTS),
        risk_profile=_enum(data["risk_profile"], "risk_profile", RISKS),
        scope_risk_overrides=scope_risk_tuple,
        repository_lenses=repo_lenses,
        common_slot_overrides=common_overrides,
        repository_slots=repo_slots,
    )
    resolved = resolve_catalog(baseline, catalog)
    if not any(slot.lens == "security" and slot.lifecycle == "ACTIVE" for slot in resolved):
        raise MaintenanceCatalogError("Security coverage may not be removed from a repository")
    return catalog


def _resolved_risk(catalog: RepositoryCatalog, scope: Scope) -> str:
    for override in catalog.scope_risk_overrides:
        if override.scope == scope:
            return override.risk
    return catalog.risk_profile


def resolve_catalog(
    baseline: CommonBaseline,
    catalog: RepositoryCatalog,
) -> tuple[ResolvedSlot, ...]:
    overrides = {item.slot_id: item for item in catalog.common_slot_overrides}
    resolved: list[ResolvedSlot] = []

    for source_slot in baseline.common_slots:
        override = overrides.get(source_slot.slot_id)
        lifecycle = (
            override.lifecycle
            if override is not None and override.lifecycle is not None
            else source_slot.lifecycle
        )
        if lifecycle != "ACTIVE":
            continue
        slot = SlotSpec(
            slot_id=source_slot.slot_id,
            title=source_slot.title,
            lifecycle=lifecycle,
            scope=source_slot.scope,
            lens=source_slot.lens,
            coverage_key=source_slot.coverage_key,
            cadence_class=(
                override.cadence_class
                if override is not None and override.cadence_class is not None
                else source_slot.cadence_class
            ),
            minimum_depth=(
                override.minimum_depth
                if override is not None and override.minimum_depth is not None
                else source_slot.minimum_depth
            ),
            external_freshness_class=(
                override.external_freshness_class
                if override is not None and override.external_freshness_class is not None
                else source_slot.external_freshness_class
            ),
            description=source_slot.description,
        )
        resolved.append(
            ResolvedSlot(
                repository=catalog.repository,
                slot_id=slot.slot_id,
                title=slot.title,
                lifecycle=slot.lifecycle,
                scope=slot.scope,
                lens=slot.lens,
                coverage_key=slot.coverage_key,
                risk=_resolved_risk(catalog, slot.scope),
                cadence_class=slot.cadence_class,
                minimum_depth=slot.minimum_depth,
                external_freshness_class=slot.external_freshness_class,
                description=slot.description,
                source="common",
            )
        )

    for slot in catalog.repository_slots:
        if slot.lifecycle != "ACTIVE":
            continue
        resolved.append(
            ResolvedSlot(
                repository=catalog.repository,
                slot_id=slot.slot_id,
                title=slot.title,
                lifecycle=slot.lifecycle,
                scope=slot.scope,
                lens=slot.lens,
                coverage_key=slot.coverage_key,
                risk=_resolved_risk(catalog, slot.scope),
                cadence_class=slot.cadence_class,
                minimum_depth=slot.minimum_depth,
                external_freshness_class=slot.external_freshness_class,
                description=slot.description,
                source="repository",
            )
        )

    active_keys: set[tuple[str, str, str, str]] = set()
    for slot in resolved:
        key = (slot.coverage_key, slot.scope.kind, slot.scope.selector, slot.lens)
        if key in active_keys:
            raise MaintenanceCatalogError(f"duplicate active coverage: {slot.coverage_key}")
        active_keys.add(key)
    return tuple(sorted(resolved, key=lambda item: item.slot_id))


def _canonical_value(baseline: CommonBaseline, catalog: RepositoryCatalog) -> dict[str, object]:
    baseline_value = asdict(baseline)
    catalog_value = asdict(catalog)
    baseline_value["lenses"] = sorted(baseline_value["lenses"], key=lambda item: item["id"])
    baseline_value["common_slots"] = sorted(
        baseline_value["common_slots"], key=lambda item: item["slot_id"]
    )
    catalog_value["repository_lenses"] = sorted(
        catalog_value["repository_lenses"], key=lambda item: item["id"]
    )
    catalog_value["scope_risk_overrides"] = sorted(
        catalog_value["scope_risk_overrides"],
        key=lambda item: (item["scope"]["kind"], item["scope"]["selector"]),
    )
    catalog_value["common_slot_overrides"] = sorted(
        catalog_value["common_slot_overrides"], key=lambda item: item["slot_id"]
    )
    catalog_value["repository_slots"] = sorted(
        catalog_value["repository_slots"], key=lambda item: item["slot_id"]
    )
    return {"baseline": baseline_value, "catalog": catalog_value}


def canonical_catalog_digest(
    baseline: CommonBaseline,
    catalog: RepositoryCatalog,
) -> str:
    payload = json.dumps(
        _canonical_value(baseline, catalog),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()
