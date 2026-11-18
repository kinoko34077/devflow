#!/usr/bin/env python3
"""Advisory Review Provenance readiness evaluator.

This validates declared metadata consistency only. It does not prove reviewer
identity or replace semantic code review.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any
import urllib.parse
import urllib.request


_STATE_TO_DECISION = {
    "COMMENTED": "COMMENT",
    "APPROVED": "APPROVE",
    "CHANGES_REQUESTED": "REQUEST_CHANGES",
}
_READY_REVIEW_STATES = {"COMMENTED", "APPROVED"}
_FORBIDDEN_DERIVED_FIELDS = {"Review-Role", "Independence"}
_UNKNOWN_IDENTITY = {"", "unknown"}


@dataclass(frozen=True)
class ReadinessResult:
    ready: bool
    reason: str
    matched_review_id: int | None = None


def _single_field(body: str, name: str) -> tuple[str | None, bool]:
    pattern = re.compile(rf"(?mi)^[ \t]*-[ \t]*{re.escape(name)}[ \t]*:[ \t]*(.*?)[ \t]*$")
    values = [match.group(1).strip() for match in pattern.finditer(body or "")]
    if len(values) != 1:
        return None, False
    return values[0], True


def _field_present(body: str, name: str) -> bool:
    pattern = re.compile(rf"(?mi)^[ \t]*-[ \t]*{re.escape(name)}[ \t]*:")
    return pattern.search(body or "") is not None


_COMPOSITE_IDENTITY = re.compile(r"[+,&/]|\band\b", re.IGNORECASE)


def _last_implementer_error(body: str) -> str | None:
    """Validate Last-Implementer metadata regardless of the formal review gate."""
    implementer_system, _ = _single_field(body, "Implementer-System")
    is_mixed = (
        implementer_system is not None
        and _normalize_identity_part(implementer_system) == "mixed"
    )
    has_last = _field_present(body, "Last-Implementer-System") or _field_present(
        body, "Last-Implementer-Model"
    )
    if not is_mixed:
        if has_last:
            return "Last-Implementer fields are only valid with Implementer-System: mixed"
        return None
    last_system, last_system_unique = _single_field(body, "Last-Implementer-System")
    last_model, last_model_unique = _single_field(body, "Last-Implementer-Model")
    if (
        not last_system_unique
        or not last_model_unique
        or not last_system
        or not last_model
        or _normalize_identity_part(last_system) in _UNKNOWN_IDENTITY | {"mixed"}
        or _COMPOSITE_IDENTITY.search(last_system)
        or _COMPOSITE_IDENTITY.search(last_model)
    ):
        return "Mixed implementer requires one explicit single Last-Implementer-System/Model"
    return None


def _yes_no_field(body: str, name: str) -> tuple[bool | None, bool]:
    value, unique = _single_field(body, name)
    if not unique or value is None:
        return None, False
    normalized = value.casefold()
    if normalized == "yes":
        return True, True
    if normalized == "no":
        return False, True
    return None, False


_PROVENANCE_HEADING = re.compile(r"(?mi)^###\s+Review Provenance\s*$")


def _provenance_fields(body: str) -> dict[str, str] | None:
    matches = list(_PROVENANCE_HEADING.finditer(body or ""))
    if len(matches) != 1:
        return None
    match = matches[0]
    tail = (body or "")[match.end() :]
    next_heading = re.search(r"(?m)^#{1,6}\s+", tail)
    section = tail[: next_heading.start()] if next_heading else tail
    fields: dict[str, str] = {}
    for key, value in re.findall(
        r"(?m)^\s*-\s*([A-Za-z][A-Za-z0-9-]*)\s*:\s*(.*?)\s*$",
        section,
    ):
        if key in fields:
            return None
        fields[key] = value.strip()
    required = {
        "Reviewer-System",
        "Reviewer-Model",
        "Implementer-System",
        "Implementer-Model",
        "Reviewed-Commit",
        "Review-Scope",
        "Decision",
        "Review-Provenance-Version",
    }
    if not required.issubset(fields):
        return None
    return fields


def _blocking_findings(body: str) -> str | None:
    value, unique = _single_field(body, "Blocking findings")
    return value if unique else None


def _normalize_identity_part(value: str) -> str:
    return " ".join(value.split()).casefold()


def _signature(system: str, model: str) -> tuple[str, str]:
    return _normalize_identity_part(system), _normalize_identity_part(model)


def _qualifies_as_different_reviewer(
    reviewer_signature: tuple[str, str],
    implementer_signature: tuple[str, str],
) -> bool:
    reviewer_system, reviewer_model = reviewer_signature
    implementer_system, implementer_model = implementer_signature

    if reviewer_system in _UNKNOWN_IDENTITY:
        return False
    if reviewer_system != implementer_system:
        return True
    if reviewer_model in _UNKNOWN_IDENTITY or implementer_model in _UNKNOWN_IDENTITY:
        return False
    return reviewer_model != implementer_model


def _commit_value(value: str) -> str:
    value = value.strip()
    inline = re.fullmatch(r"`([0-9a-fA-F]{40})`", value)
    return inline.group(1) if inline else value


def _review_rejection(
    review: dict[str, Any],
    *,
    implementer_signature: tuple[str, str],
    head_sha: str,
) -> str | None:
    body = str(review.get("body") or "")
    fields = _provenance_fields(body)
    if fields is None:
        return "No valid formal review provenance found"

    if fields["Review-Provenance-Version"] != "2":
        return "Unsupported formal review provenance version"
    if _FORBIDDEN_DERIVED_FIELDS.intersection(fields):
        return "Review Provenance v2 must not persist derived reviewer-relation fields"
    if _commit_value(fields["Reviewed-Commit"]) != head_sha:
        return "Formal review does not target current head"

    commit_id = review.get("commit_id")
    if commit_id and str(commit_id) != head_sha:
        return "Formal review API commit does not match current head"

    declared_implementer = _signature(
        fields["Implementer-System"], fields["Implementer-Model"]
    )
    if declared_implementer != implementer_signature:
        return "Formal review implementer provenance does not match PR"

    blocking = _blocking_findings(body)
    if blocking is None or blocking.casefold() != "none":
        return "Formal review declares blocking findings or lacks a clear none result"

    state = str(review.get("state") or "").upper()
    expected_decision = _STATE_TO_DECISION.get(state)
    if expected_decision is None:
        return "Formal review is not in a recognized submitted state"
    if fields["Decision"] != expected_decision:
        return "Formal review API state and declared decision do not match"
    if state not in _READY_REVIEW_STATES:
        return "Formal review requests changes and remains blocking"

    return None


def _managed_reviews(
    reviews: list[dict[str, Any]],
) -> list[tuple[int, dict[str, Any], dict[str, str]]]:
    managed: list[tuple[int, dict[str, Any], dict[str, str]]] = []
    for index, candidate in enumerate(reviews):
        fields = _provenance_fields(str(candidate.get("body") or ""))
        if fields is not None:
            managed.append((index, candidate, fields))
    return managed



# GitHub API user identity for the repository-installed Codex PR review integration.
# This is not the GitHub identity of the normal implementing Codex session.
_CODEX_BOT_ID = 199175422
_CODEX_BOT_LOGIN = "chatgpt-codex-connector[bot]"
_CODEX_STATE = re.compile(
    r"<!-- codex-review-state:v1 ([^\r\n]{1,2048}) -->"
)


def _verified_codex_summary(comment: dict[str, Any], head_sha: str) -> bool:
    """Admit only the actual bot's exact-head, completed code review summary."""
    user = comment.get("user")
    if not isinstance(user, dict) or (
        user.get("id") != _CODEX_BOT_ID
        or user.get("login") != _CODEX_BOT_LOGIN
        or user.get("type") != "Bot"
    ):
        return False
    body = comment.get("body")
    if not isinstance(body, str) or body.count(
        "<!-- codex-pull-request-review-summary -->"
    ) != 1:
        return False
    matches = _CODEX_STATE.findall(body)
    if len(matches) != 1:
        return False
    try:
        packet = json.loads(matches[0])
    except (ValueError, TypeError):
        return False
    if not isinstance(packet, dict):
        return False
    review = packet.get("code_review")
    return (
        isinstance(review, dict)
        and review.get("commit_sha") == head_sha
        and review.get("status") == "completed"
        and type(review.get("has_any_findings")) is bool
        and review.get("has_unresolved_findings") is False
    )


def _latest_codex_summary(comments: list[dict[str, Any]]) -> dict[str, Any] | None:
    # A newer, pending or stale bot summary must not be overruled by an older
    # clean review. GitHub issue_comment edits update the original summary.
    items = [
        c for c in comments
        if isinstance(c, dict)
        and isinstance(c.get("user"), dict)
        and c["user"].get("id") == _CODEX_BOT_ID
        and c["user"].get("login") == _CODEX_BOT_LOGIN
        and isinstance(c.get("body"), str)
        and "<!-- codex-pull-request-review-summary -->" in c["body"]
    ]
    if not items:
        return None
    return max(items, key=lambda c: (str(c.get("updated_at") or ""),
                                      int(c.get("id") or 0)))


def _github_review_packet(repository: str, pr_number: int) -> tuple[
    dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], set[int]
]:
    """Read only native REST source records; reusable outside GitHub Actions."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("repository must be owner/name")
    if type(pr_number) is not int or pr_number < 1:
        raise ValueError("PR number must be positive")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    use_existing_gh = not bool(token)
    api = os.environ.get("GH_API_URL", "https://api.github.com").rstrip("/")
    parsed = urllib.parse.urlparse(api)
    if (parsed.scheme != "https" or parsed.hostname != "api.github.com"
            or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("GH_API_URL must be https://api.github.com")
    parts = repository.split("/")
    base = f"{api}/repos/{urllib.parse.quote(parts[0])}/{urllib.parse.quote(parts[1])}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def get_json(url: str) -> Any:
        if use_existing_gh:
            endpoint = urllib.parse.urlparse(url)
            relative = endpoint.path + ("?" + endpoint.query if endpoint.query else "")
            response = subprocess.run(
                ["gh", "api", relative, "--hostname", "github.com"],
                capture_output=True, text=True,
                check=True, timeout=20,
            )
            return json.loads(response.stdout)
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def trusted_bot_edit_history(comment: dict[str, Any]) -> bool:
        """Verify every edit via GitHub GraphQL, not only original REST author."""
        user = comment.get("user") or {}
        node_id = user.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            return False
        query = """
        query($id: ID!) {
          node(id: $id) {
            ... on IssueComment {
              id
              body
              editor { ... on Bot { id } }
              lastEditedAt
              userContentEdits(first: 100) {
                pageInfo { hasNextPage }
                nodes { editor { ... on Bot { id } } }
              }
            }
          }
        }
        """
        data = json.dumps({"query": query, "variables": {"id": comment.get("node_id")}}).encode("utf-8")
        if not comment.get("node_id"):
            return False
        try:
            if use_existing_gh:
                response = subprocess.run(
                    ["gh", "api", "graphql", "--hostname", "github.com",
                     "-f", f"query={query}", "-F", f"id={comment['node_id']}"],
                    capture_output=True, text=True, check=True, timeout=20,
                )
                packet = json.loads(response.stdout)
            else:
                request = urllib.request.Request(
                    f"{api}/graphql", data=data,
                    headers={**headers, "Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=20) as response:
                    packet = json.load(response)
        except (OSError, ValueError, subprocess.SubprocessError):
            return False
        if not isinstance(packet, dict) or packet.get("errors"):
            return False
        node = (packet.get("data") or {}).get("node")
        if not isinstance(node, dict) or node.get("id") != comment.get("node_id"):
            return False
        # Re-read the same rendered body through an independent GitHub API
        # surface to guard an edit racing with the REST read.
        if node.get("body") != comment.get("body"):
            return False
        history = node.get("userContentEdits")
        if not isinstance(history, dict) or not isinstance(history.get("nodes"), list):
            return False
        if (history.get("pageInfo") or {}).get("hasNextPage") is not False:
            return False
        if node.get("lastEditedAt") is not None:
            if not isinstance(node.get("editor"), dict) or node["editor"].get("id") != node_id:
                return False
            if not history["nodes"]:
                return False
        return all(
            isinstance(edit, dict)
            and isinstance(edit.get("editor"), dict)
            and edit["editor"].get("id") == node_id
            for edit in history["nodes"]
        )

    def pages(suffix: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for page in range(1, 21):
            query = urllib.parse.urlencode({"per_page": 100, "page": page})
            batch = get_json(f"{base}/{suffix}?{query}")
            if not isinstance(batch, list) or any(not isinstance(v, dict) for v in batch):
                raise ValueError("Unexpected GitHub list response")
            found.extend(batch)
            if len(batch) < 100:
                return found
        raise ValueError("GitHub source pagination incomplete")

    pr = get_json(f"{base}/pulls/{pr_number}")
    if not isinstance(pr, dict):
        raise ValueError("Unexpected GitHub PR response")
    reviews = pages(f"pulls/{pr_number}/reviews")
    comments = pages(f"issues/{pr_number}/comments")
    verified_bot_ids: set[int] = set()
    summary = _latest_codex_summary(comments)
    if summary is not None and trusted_bot_edit_history(summary):
        verified_bot_ids.add(summary["id"])
    return pr, reviews, comments, verified_bot_ids


def evaluate(
    pr: dict[str, Any], reviews: list[dict[str, Any]],
    comments: list[dict[str, Any]] | None = None,
    *, verified_codex_ids: set[int] | None = None,
) -> ReadinessResult:
    body = str(pr.get("body") or "")
    formal_required, valid_formal_gate = _yes_no_field(body, "Formal review required")
    different_required, valid_different_gate = _yes_no_field(
        body, "Different reviewer required"
    )
    if not valid_formal_gate or not valid_different_gate:
        return ReadinessResult(False, "Formal/different review gate is missing, ambiguous, or invalid")
    assert formal_required is not None
    assert different_required is not None

    if different_required and not formal_required:
        return ReadinessResult(False, "Review gate is inconsistent: different reviewer requires formal review")
    last_error = _last_implementer_error(body)
    if last_error:
        return ReadinessResult(False, last_error)
    if not formal_required:
        return ReadinessResult(True, "Formal review is not required by explicit PR classification")

    implementer_system, unique_system = _single_field(body, "Implementer-System")
    implementer_model, unique_model = _single_field(body, "Implementer-Model")
    if (
        not unique_system
        or not unique_model
        or not implementer_system
        or not implementer_model
    ):
        return ReadinessResult(False, "Implementer signature is missing or ambiguous")
    implementer_signature = _signature(implementer_system, implementer_model)
    # Co-implemented PRs (`Implementer-System: mixed`) must name the worker who
    # made the most recent change. Different-reviewer eligibility is judged
    # against that last implementer only; earlier co-implementers may review.
    independence_signature = implementer_signature
    if implementer_signature[0] == "mixed":
        last_system, _ = _single_field(body, "Last-Implementer-System")
        last_model, _ = _single_field(body, "Last-Implementer-Model")
        assert last_system is not None and last_model is not None
        independence_signature = _signature(last_system, last_model)

    head = pr.get("head") or {}
    head_sha = str(head.get("sha") or "")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha):
        return ReadinessResult(False, "Current head SHA is missing or invalid")

    if comments is not None:
        latest_bot = _latest_codex_summary(comments)
        # A native REQUEST_CHANGES is a separate blocking gate; even a clean
        # bot summary must not silently override it.
        current_head_formal = [
            r for r in reviews
            if _provenance_fields(str(r.get("body") or "")) is not None
            and _commit_value(_provenance_fields(str(r.get("body") or ""))["Reviewed-Commit"]) == head_sha
        ]
        # A submitted COMMENT Review can block a merge. A later submission
        # clears that state only when the *whole* formal review is valid.
        # In particular, v1, dismissed, mismatched API commit, and malformed
        # provenance cannot silently clear an earlier blocker.
        formal_blocker = False
        for candidate in current_head_formal:
            formal_blocker = _review_rejection(
                candidate,
                implementer_signature=implementer_signature,
                head_sha=head_sha,
            ) is not None
        has_native_blocker = formal_blocker or any(
            str(r.get("state") or "").upper() == "CHANGES_REQUESTED"
            for r in reviews
        )
        has_malformed_native = any(
            _PROVENANCE_HEADING.search(str(r.get("body") or ""))
            and _provenance_fields(str(r.get("body") or "")) is None
            for r in reviews
        )
        if (
            latest_bot is not None
            and latest_bot.get("id") in (verified_codex_ids or set())
            and _verified_codex_summary(latest_bot, head_sha)
            and not has_native_blocker
            and not has_malformed_native
            and independence_signature[0]
            not in {"chatgpt-codex-connector", "chatgpt-codex-connector[bot]"}
        ):
            return ReadinessResult(
                True,
                "Current-head verified GitHub Codex Code Review completed with no unresolved findings",
                latest_bot.get("id"),
            )

    managed = _managed_reviews(reviews)
    if not managed:
        if any(
            re.search(r"(?mi)^###\s+Review Provenance\s*$", str(item.get("body") or ""))
            for item in reviews
        ):
            return ReadinessResult(False, "No valid formal review provenance satisfies v2 schema")
        return ReadinessResult(False, "No formal review provenance found")

    latest_index, latest_review, _latest_fields = managed[-1]
    if any(
        str(candidate.get("state") or "").upper() == "CHANGES_REQUESTED"
        for candidate in reviews[latest_index + 1 :]
    ):
        return ReadinessResult(
            False,
            "A newer REQUEST_CHANGES review remains unresolved",
        )

    if any(
        _PROVENANCE_HEADING.search(str(candidate.get("body") or ""))
        for candidate in reviews[latest_index + 1 :]
    ):
        # A newer Review that attempted formal provenance but is ambiguous or
        # malformed must block rather than be ignored in favor of an older one.
        return ReadinessResult(
            False,
            "A newer formal review has ambiguous or malformed provenance",
        )

    latest_rejection = _review_rejection(
        latest_review,
        implementer_signature=implementer_signature,
        head_sha=head_sha,
    )
    if latest_rejection is not None:
        return ReadinessResult(False, latest_rejection)

    if not different_required:
        return ReadinessResult(
            True,
            "Current-head formal Review Provenance v2 is present",
            latest_review.get("id"),
        )

    for _index, candidate, fields in reversed(managed):
        reviewer_signature = _signature(fields["Reviewer-System"], fields["Reviewer-Model"])
        if not _qualifies_as_different_reviewer(
            reviewer_signature,
            independence_signature,
        ):
            continue
        rejection = _review_rejection(
            candidate,
            implementer_signature=implementer_signature,
            head_sha=head_sha,
        )
        if rejection is None:
            return ReadinessResult(
                True,
                "Current-head formal Review Provenance v2 from a different reviewer signature is present",
                candidate.get("id"),
            )
        return ReadinessResult(False, rejection)

    return ReadinessResult(False, "Different reviewer is required but no differing current-head signature qualifies")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr-json", type=Path)
    parser.add_argument("--reviews-json", type=Path)
    parser.add_argument("--comments-json", type=Path)
    parser.add_argument("--repository", help="GitHub owner/name for authenticated read-only REST mode")
    parser.add_argument("--pr-number", type=int, help="PR number for REST mode")
    args = parser.parse_args()

    try:
        if args.repository is not None or args.pr_number is not None:
            if (args.repository is None or args.pr_number is None
                    or args.pr_json or args.reviews_json or args.comments_json):
                parser.error("live mode requires --repository and --pr-number only")
            pr, reviews, comments, verified_bot_ids = _github_review_packet(args.repository, args.pr_number)
            summary = _latest_codex_summary(comments)
            evidence_state = (
                "absent" if summary is None else
                "editor-history-verified" if summary.get("id") in verified_bot_ids else
                "editor-history-unverified"
            )
            print(f"review-readiness-source: codex-summary={evidence_state}")
        else:
            if args.pr_json is None or args.reviews_json is None:
                parser.error("offline mode requires --pr-json and --reviews-json")
            pr = json.loads(args.pr_json.read_text(encoding="utf-8"))
            reviews = json.loads(args.reviews_json.read_text(encoding="utf-8"))
            comments = (json.loads(args.comments_json.read_text(encoding="utf-8"))
                        if args.comments_json else None)
            verified_bot_ids = set()  # Fixture JSON is not authenticated GitHub evidence.
        if (not isinstance(pr, dict) or not isinstance(reviews, list)
                or (comments is not None and not isinstance(comments, list))):
            raise ValueError("PR/reviews/comments source JSON has invalid structure")
        result = evaluate(pr, reviews, comments, verified_codex_ids=verified_bot_ids)
    except (ValueError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"review-readiness: FAIL — source unavailable or invalid: {type(exc).__name__}")
        return 1
    status = "PASS" if result.ready else "FAIL"
    matched = f" review_id={result.matched_review_id}" if result.matched_review_id else ""
    print(f"review-readiness: {status}{matched} — {result.reason}")
    print("identity-note: Review Provenance is self-asserted metadata, not cryptographic identity.")
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
