"""Native GitHub GET-only collector for SMC's conservative audit coverage view.

Not a task publisher, audit executor, credential manager, Project writer or
claim authority. The caller supplies already-authorized GET transport and
source fingerprints; missing provenance is never inferred.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from tools.maintenance_catalog import (
    parse_common_baseline_text, parse_repository_catalog_text, resolve_catalog,
)
from tools.maintenance_coverage import (CoverageRow, LedgerEvidence, TRUSTED_ASSOCIATIONS, derive_coverage)
from tools.maintenance_ledger import (
    MaintenanceLedgerError, extract_active_run, parse_run_comment,
)

BASELINE_REPOSITORY = "kinoko34077/devflow"
BASELINE_PATH = "docs/spec/maintenance/common-baseline.v1.yaml"
CATALOG_PATH = ".devflow/maintenance.yaml"
RUN_SENTINEL = "<!-- devflow-maintenance-run:v1 -->"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class CoverageCollectionError(ValueError):
    """Unable to produce a trustworthy coverage observation."""


@dataclass(frozen=True)
class CoverageObservation:
    repository: str
    ledger_issue_number: int
    catalog_blob_sha: str
    comments_scanned: int
    machine_records: int
    substantive_legacy_records: int
    noncredit_records: int
    untrusted_records: int
    active_run_id: str | None
    rows: tuple[CoverageRow, ...]


def _repo(value: str) -> str:
    if not isinstance(value, str) or REPO_RE.fullmatch(value) is None:
        raise CoverageCollectionError("repository must be an exact owner/name")
    return value


def _file(transport: object, repository: str, path: str, ref: str | None = None) -> dict:
    observed = transport.get_file(repository, path, ref=ref)
    if not isinstance(observed, dict):
        raise CoverageCollectionError(f"missing required canonical file: {repository}/{path}")
    if not isinstance(observed.get("content"), str):
        raise CoverageCollectionError(f"invalid UTF-8 source file: {repository}/{path}")
    sha = observed.get("sha")
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise CoverageCollectionError(f"unverified GitHub source blob: {repository}/{path}")
    return observed


def _ledger_identity(issue: dict, repository: str, issue_number: int) -> None:
    if not isinstance(issue, dict) or issue.get("number") != issue_number:
        raise CoverageCollectionError("untrusted Ledger Issue number")
    if issue.get("title") != "[MAINTENANCE] Audit Ledger" or issue.get("state") != "open":
        raise CoverageCollectionError("wrong or closed Ledger owner")
    expected = f"https://github.com/{repository}/issues/{issue_number}"
    if issue.get("html_url") != expected:
        raise CoverageCollectionError("Ledger origin is not the requested repository")
    body = issue.get("body")
    if not isinstance(body, str):
        raise CoverageCollectionError("Ledger body unavailable")
    matches = re.findall(r"(?m)^## Repository\s*\n\s*`([^\n`]+)`", body)
    if matches != [repository]:
        raise CoverageCollectionError("Ledger repository heading missing or ambiguous")


def _comment_origin(comment: dict, repository: str, issue_number: int) -> str:
    cid = comment.get("id")
    if not isinstance(cid, int) or isinstance(cid, bool) or cid <= 0:
        raise CoverageCollectionError("Ledger comment ID missing")
    expected_html = f"https://github.com/{repository}/issues/{issue_number}#issuecomment-{cid}"
    expected_api = f"https://api.github.com/repos/{repository}/issues/{issue_number}"
    if comment.get("html_url") != expected_html or comment.get("issue_url") != expected_api:
        raise CoverageCollectionError("Ledger comment does not belong to its Issue")
    if not isinstance(comment.get("author_association"), str):
        raise CoverageCollectionError("Ledger comment author association missing")
    return expected_html


def collect_repository_coverage(
    transport: object,
    repository: str,
    ledger_issue_number: int,
    current_fingerprints: Mapping[str, str] | None = None,
    *,
    catalog_ref: str | None = None,
) -> CoverageObservation:
    """Collect genuine source/Issue/comments then derive unprivileged rows.

    All comments must be fetched with the existing transport's paginated GET;
    a partial/failed page is an exception, not an empty history. A fingerprint
    from an unverified caller creates no audit credit; v1 substantive runs
    remain LEGACY_SCOPE_UNBOUND regardless of supplied fingerprint equality.
    """
    repository = _repo(repository)
    if type(ledger_issue_number) is not int or ledger_issue_number <= 0:
        raise CoverageCollectionError("ledger issue number must be positive")
    baseline = _file(transport, BASELINE_REPOSITORY, BASELINE_PATH)
    local = _file(transport, repository, CATALOG_PATH, ref=catalog_ref)
    shared = parse_common_baseline_text(baseline["content"])
    catalog = parse_repository_catalog_text(local["content"], shared)
    if catalog.repository != repository:
        raise CoverageCollectionError("repository catalog identity mismatch")
    if catalog.rollout == "DISABLED":
        raise CoverageCollectionError("disabled catalog cannot claim audit coverage")
    slots = resolve_catalog(shared, catalog)

    issue = transport.get_issue(repository, ledger_issue_number)
    _ledger_identity(issue, repository, ledger_issue_number)
    try:
        active = extract_active_run(issue["body"], repository)
    except MaintenanceLedgerError as exc:
        raise CoverageCollectionError("invalid Ledger active-run state") from exc
    comments = transport.list_issue_comments(repository, ledger_issue_number)
    if not isinstance(comments, list):
        raise CoverageCollectionError("Ledger comments pagination result invalid")

    history: list[LedgerEvidence] = []
    for item in comments:
        if not isinstance(item, dict):
            raise CoverageCollectionError("Ledger comment row is invalid")
        body = item.get("body")
        if not isinstance(body, str):
            raise CoverageCollectionError("Ledger comment body unavailable")
        if RUN_SENTINEL not in body:
            continue
        url = _comment_origin(item, repository, ledger_issue_number)
        try:
            record = parse_run_comment(body)
        except MaintenanceLedgerError as exc:
            raise CoverageCollectionError("malformed machine audit run comment") from exc
        if record is None or record.repository != repository:
            raise CoverageCollectionError("machine record identity invalid")
        history.append(LedgerEvidence(record, url, item["author_association"]))

    complete = {"CLEAN", "FINDINGS", "RECONCILED"}
    trusted_history = [e for e in history if e.author_association in TRUSTED_ASSOCIATIONS]
    rows = derive_coverage(slots, history, current_fingerprints or {})
    return CoverageObservation(
        repository=repository,
        ledger_issue_number=ledger_issue_number,
        catalog_blob_sha=local["sha"],
        comments_scanned=len(comments),
        machine_records=len(history),
        substantive_legacy_records=sum(e.record.result in complete for e in trusted_history),
        noncredit_records=sum(e.record.result not in complete for e in trusted_history),
        untrusted_records=len(history) - len(trusted_history),
        active_run_id=active.run_id if active else None,
        rows=rows,
    )
