"""GitHub-native read-only bridge from SMC Ledger comments to coverage rows.

Reuses accepted maintenance GitHub GET transport and catalog parser. Never
mutates Issues, publishes a candidate, creates a claim, or grants current-
scope proof from historical v1 completion records.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping

from tools import maintenance_github as gh
from tools.maintenance_catalog import MaintenanceCatalogError
from tools.maintenance_coverage import LedgerEvidence, derive_coverage
from tools.maintenance_ledger import (
    MaintenanceLedgerError,
    extract_active_run,
    parse_run_comment,
)


COVERAGE_SCHEMA = "maintenance-coverage-shadow.v1"


def _invalid(repository: str, reason: str, detail: str | None = None) -> dict[str, object]:
    response: dict[str, object] = {
        "schema_version": COVERAGE_SCHEMA,
        "repository": repository,
        "status": "NEEDS_EVIDENCE",
        "reason_code": reason,
        "rows": [],
    }
    if detail is not None:
        response["detail"] = detail
    return response


def collect_maintenance_coverage(
    transport: Any,
    repository: str,
    control_ref: str,
    *,
    external_state: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """GET-only trusted Ledger projection; returns rows or a fail-closed diagnostic."""
    control = gh.collect_maintenance_control(transport, repository, control_ref)
    if control.get("status") != "OK":
        return _invalid(repository, "CONTROL_NOT_TRUSTED", str(control.get("reason_code")))

    try:
        _baseline, catalog, slots, digest, head, baseline_file, catalog_file = (
            gh._catalog_bundle(transport, repository)
        )
    except FileNotFoundError:
        return _invalid(repository, "CATALOG_NOT_FOUND")
    except (MaintenanceCatalogError, gh.GitHubReadError, ValueError) as exc:
        return _invalid(repository, "CATALOG_UNAVAILABLE", str(exc))

    try:
        ledger, reason = gh.find_maintenance_ledger(transport, repository)
        if ledger is None:
            return _invalid(repository, reason or "LEDGER_MISSING")
        number = ledger.get("number")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            return _invalid(repository, "LEDGER_IDENTITY_INVALID")
        # Reobserve the exact canonical Issue instead of relying on a search hit.
        actual = transport.get_issue(repository, number)
        expected_url = f"https://github.com/{repository}/issues/{number}"
        if (
            actual.get("title") != gh.MAINTENANCE_LEDGER_TITLE
            or actual.get("state") != "open"
            or actual.get("html_url") != expected_url
            or "pull_request" in actual
            or str(actual.get("author_association") or "").upper()
            not in gh.TRUSTED_ASSOCIATIONS
        ):
            return _invalid(repository, "LEDGER_IDENTITY_INVALID")
        active = extract_active_run(str(actual.get("body") or ""), repository)
        comments = transport.list_issue_comments(repository, number)
        if not isinstance(comments, list):
            return _invalid(repository, "LEDGER_COMMENTS_UNAVAILABLE")
    except (gh.GitHubReadError, MaintenanceLedgerError, ValueError) as exc:
        return _invalid(repository, "LEDGER_UNAVAILABLE", str(exc))

    evidence: list[LedgerEvidence] = []
    ignored_untrusted = 0
    for comment in comments:
        if not isinstance(comment, dict):
            return _invalid(repository, "LEDGER_COMMENT_MALFORMED")
        body = comment.get("body")
        if not isinstance(body, str) or not body.startswith("<!-- devflow-maintenance-run:v1 -->"):
            continue
        association = str(comment.get("author_association") or "").upper()
        if association not in gh.TRUSTED_ASSOCIATIONS:
            ignored_untrusted += 1
            continue
        cid = comment.get("id")
        expected = f"{expected_url}#issuecomment-{cid}"
        if (
            not isinstance(cid, int)
            or isinstance(cid, bool)
            or cid <= 0
            or comment.get("html_url") != expected
        ):
            return _invalid(repository, "LEDGER_COMMENT_IDENTITY_INVALID")
        try:
            record = parse_run_comment(body)
        except MaintenanceLedgerError as exc:
            return _invalid(repository, "LEDGER_COMMENT_INVALID", str(exc))
        if record is None or record.repository != repository:
            return _invalid(repository, "LEDGER_COMMENT_REPOSITORY_MISMATCH")
        evidence.append(LedgerEvidence(
            record=record,
            source_url=expected,
            author_association=association,
        ))

    fingerprint = gh.build_maintenance_fingerprint(head, digest, external_state)
    current_fingerprints = {
        f"{slot.repository}::{slot.slot_id}": (
            fingerprint
            if bool(external_state)
            or (slot.external_freshness_class != "FAST" and slot.scope.kind != "external_system")
            else ""
        )
        for slot in slots
    }
    rows = derive_coverage(slots, evidence, current_fingerprints)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return {
        "schema_version": COVERAGE_SCHEMA,
        "repository": repository,
        "status": "OK",
        "rollout": catalog.rollout,
        "control_ref": control_ref,
        "ledger_ref": f"{repository}#{number}",
        "code_sha": head,
        "catalog_digest": digest,
        "source_blobs": {
            "baseline": baseline_file.get("sha"),
            "catalog": catalog_file.get("sha"),
        },
        "active_run_id": active.run_id if active is not None else None,
        "trusted_run_comments": len(evidence),
        "ignored_untrusted_comments": ignored_untrusted,
        "coverage_status_counts": dict(sorted(counts.items())),
        "rows": [asdict(row) for row in rows],
    }
