"""Read-only native devflow post-merge Control PR semantic event check (#726).

This is an event-triggered, source-scoped adapter around the existing
source-backed semantic PR reader. No GitHub mutation, new credential, local
persistence, scheduler, general multi-repo hook, or implicit readiness claim.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

from tools import control_semantic_pilot as pilot

REPOSITORY = "kinoko34077/devflow"
CONTROL_NUMBER = 16
CONTROL_URL = "https://github.com/kinoko34077/devflow/issues/16"
EVENT_MAX_BYTES = 1_048_576


def _result(status: str, reason: str, number: int | None = None, repository: str = REPOSITORY) -> dict[str, str]:
    answer = {"status": status, "reason": reason}
    if type(number) is int and number > 0:
        answer["subject"] = f"{repository}#{number}"
    return answer


def _event_number(event: Any, repository_env: str, expected_repository: str = REPOSITORY) -> tuple[int | None, str]:
    if type(event) is not dict or repository_env != expected_repository:
        return None, "UNTRUSTED_REPOSITORY_OR_EVENT"
    if event.get("action") != "closed":
        return None, "NOT_A_CLOSED_PR_EVENT"
    repo = event.get("repository")
    pr = event.get("pull_request")
    if type(repo) is not dict or repo.get("full_name") != expected_repository:
        return None, "UNTRUSTED_REPOSITORY_OR_EVENT"
    if type(pr) is not dict:
        return None, "MISSING_PR_EVENT"
    number = pr.get("number")
    if type(number) is not int or number < 1 or number > 1_000_000_000:
        return None, "INVALID_PR_NUMBER"
    if pr.get("html_url") != f"https://github.com/{expected_repository}/pull/{number}":
        return None, "INVALID_PR_IDENTITY"
    base = pr.get("base")
    if type(base) is not dict or type(base.get("repo")) is not dict:
        return None, "INVALID_PR_BASE"
    if base["repo"].get("full_name") != expected_repository:
        return None, "INVALID_PR_BASE"
    # Non-merged close is not this pilot's acceptance target.
    if pr.get("merged") is False:
        return number, "CLOSED_UNMERGED_NOT_IN_SCOPE"
    if pr.get("merged") is not True:
        return None, "MERGED_FACT_NOT_PROVEN"
    if type(pr.get("merged_at")) is not str or not pr["merged_at"]:
        return None, "MERGED_FACT_NOT_PROVEN"
    return number, "MERGED_EVENT_VERIFIED"


def _current_next_action(issue: dict[str, Any], control_id: int = CONTROL_NUMBER, repository: str = REPOSITORY) -> str | None:
    if (
        type(issue.get("number")) is not int
        or issue.get("number") != control_id
        or issue.get("title") != f"[REPO] {repository.partition(chr(47))[2]}"
        or issue.get("html_url") != f"https://github.com/kinoko34077/devflow/issues/{control_id}"
        or issue.get("state") != "open"
        or type(issue.get("body")) is not str
    ):
        return None
    sections = re.findall(
        r"^## Next Action[ \t]*\n([\s\S]*?)(?=^## |\Z)",
        issue["body"],
        re.MULTILINE,
    )
    if len(sections) != 1:
        return None
    return sections[0].split("**HISTORICAL", 1)[0]



# Reuse the existing PR template's single "- Owning-Issue:" field.
# Accept legacy unbulleted owner lines but never guess owner from loose prose.
OWNER_LINE = re.compile(
    r"^(?:- )?Owning-Issue:[ \t]*([^\r\n]*)\r?$", re.MULTILINE,
)
OWNER_VALUE = re.compile(
    r"(?:#(?P<relative>[1-9][0-9]{0,8})|"
    r"https://github\.com/(?P<absolute_repo>kinoko34077/[A-Za-z0-9_.-]{1,100})"
    r"/issues/(?P<absolute_number>[1-9][0-9]{0,8}))"
)


# GitHub's template has a separate optional closing-keyword relation.
# A closing keyword may start a line whose issue reference has trailing
# description text; never infer an owner from an unanchored prose mention.
CLOSING_LINE = re.compile(
    # An ordinary bullet such as "- Fixes the post-merge handler" is NOT
    # an Issue closing declaration. Require an Issue-reference-shaped value;
    # the subsequent owner parser validates its exact repository and number.
    r"^(?:- )?(?:close(?:s|d)?|fix(?:es|ed)?|resolve(?:s|d)?)[ \t]*:?[ \t]*"
    r"((?:#|https?://|[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#)[^\r\n]*)\r?$",
    re.IGNORECASE | re.MULTILINE,
)
CLOSING_QUALIFIED = re.compile(
    r"(kinoko34077/[A-Za-z0-9_.-]{1,100})#([1-9][0-9]{0,8})"
)
CLOSING_REFERENCE_IN_TAIL = re.compile(
    r"(?<![A-Za-z0-9])(?:#[1-9][0-9]{0,8}(?![0-9])|"
    r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/"
    r"[1-9][0-9]{0,8})",
    re.IGNORECASE,
)
FENCED_CODE_START = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
FENCED_CODE_LIST_START = re.compile(
    r"^(?P<indent> {0,3})(?P<marker>[-+*]|[0-9]{1,9}[.)])"
    r"(?P<gap> {1,4})(?P<fence>`{3,}|~{3,})(?P<info>.*)$"
)


def _without_fenced_code_blocks(text: str) -> str:
    """Keep prose while blanking Markdown fenced code blocks.

    Owner and closing-keyword declarations are metadata only when they are
    actual PR-body fields. Examples inside fenced code must not create an
    ownership or GitHub closing-issue relation.
    """
    result: list[str] = []
    fence_char: str | None = None
    fence_length = 0
    fence_indent = 0

    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        ending = (
            "\r\n" if line.endswith("\r\n")
            else "\n" if line.endswith("\n")
            else "\r" if line.endswith("\r")
            else ""
        )
        if fence_char is not None:
            leading_spaces = len(content) - len(content.lstrip(" "))
            closing = None
            if fence_indent <= leading_spaces <= fence_indent + 3:
                closing = re.fullmatch(
                    rf"{re.escape(fence_char)}{{{fence_length},}}[ \t]*",
                    content[leading_spaces:],
                )
            if closing is not None:
                fence_char = None
                fence_length = 0
                fence_indent = 0
            result.append(ending)
            continue

        list_opening = FENCED_CODE_LIST_START.fullmatch(content)
        opening = FENCED_CODE_START.fullmatch(content)
        if list_opening is not None or opening is not None:
            if list_opening is not None:
                indent, marker, gap, fence, info = list_opening.group(
                    "indent", "marker", "gap", "fence", "info"
                )
                # A list item contributes its marker and following spaces to
                # the indentation required by continuation lines, including
                # the closing fence.
                fence_indent = len(indent) + len(marker) + len(gap)
            else:
                assert opening is not None
                fence, info = opening.groups()
                # Outside a list container, CommonMark permits the closing
                # fence to use any indentation from zero through three.
                fence_indent = 0
            # CommonMark does not permit backticks in a backtick fence's
            # info string; treat that line as prose rather than opening a
            # block that could hide later declarations.
            if fence[0] == "`" and "`" in info:
                fence_indent = 0
                result.append(line)
                continue
            fence_char = fence[0]
            fence_length = len(fence)
            result.append(ending)
            continue

        result.append(line)

    return "".join(result)


def _parse_closing_issue(value: str, caller_repository: str) -> tuple[str, int] | None:
    """Interpret GitHub closing syntax through the *existing* owner parser."""
    value = value.strip()

    def resolve(reference: str) -> tuple[str, int] | None:
        qualified = CLOSING_QUALIFIED.fullmatch(reference)
        if qualified is not None:
            owner, number = qualified.groups()
            reference = f"https://github.com/{owner}/issues/{number}"
        return _parse_owner_issue(reference, caller_repository)

    exact = resolve(value)
    if exact is not None:
        return exact

    # GitHub accepts a closing keyword followed by an Issue reference even
    # when a description immediately follows it (for example, "Fix #726's
    # post-merge reader"). Parse only that leading reference. A second Issue
    # reference keeps the declaration ambiguous and therefore UNKNOWN.
    reference = OWNER_VALUE.match(value)
    if reference is None:
        reference = CLOSING_QUALIFIED.match(value)
    if reference is None:
        return None
    suffix = value[reference.end():]
    if suffix and suffix[0] not in " \t'’.,;:!)]":
        return None
    if CLOSING_REFERENCE_IN_TAIL.search(suffix):
        return None
    return resolve(value[:reference.end()])



def _parse_owner_issue(value: str, caller_repository: str) -> tuple[str, int] | None:
    """GitHub relative #N names the *caller* Issue, never devflow by default."""
    marker = OWNER_VALUE.fullmatch(value)
    if marker is None:
        return None
    if marker.group("relative") is not None:
        return (caller_repository, int(marker.group("relative")))
    absolute = marker.group("absolute_repo")
    # No arbitrary GitHub account/repository issue fetches from user PR text.
    if absolute not in (caller_repository, REPOSITORY):
        return None
    return (absolute, int(marker.group("absolute_number")))


def _owner_reconciliation_candidate(
    current: str, number: int, merged_at: str, repository: str = REPOSITORY,
) -> dict[str, str]:
    """Human-authored ownership yields a read-only review candidate, not proof."""
    receipt = pilot._read_json(f"repos/{repository}/pulls/{number}")
    if receipt is None:
        return _result("UNKNOWN", "PR_SOURCE_READ_FAILED", number, repository)
    pr, _time = receipt
    if (
        type(pr.get("number")) is not int or pr["number"] != number
        or pr.get("html_url") != f"https://github.com/{repository}/pull/{number}"
        or pr.get("state") != "closed"
        or pr.get("merged") is not True
        or pr.get("merged_at") != merged_at
        or type(pr.get("base")) is not dict
        or type(pr["base"].get("repo")) is not dict
        or pr["base"]["repo"].get("full_name") != repository
    ):
        return _result("UNKNOWN", "MERGED_PR_SOURCE_NOT_PROVEN", number, repository)
    body = pr.get("body")
    if body is None:
        body = ""
    if type(body) is not str:
        return _result("UNKNOWN", "INVALID_PR_OWNER_METADATA", number, repository)
    declaration_text = _without_fenced_code_blocks(body)
    declarations = [part.strip() for part in OWNER_LINE.findall(declaration_text)]
    # Blank template fields are not evidence; do not guess from prose.
    filled = [part for part in declarations if part]
    closings = [part.strip() for part in CLOSING_LINE.findall(declaration_text)]
    valid_closings = [part for part in closings if part not in ("", "#")]
    if len(filled) > 1:
        return _result("UNKNOWN", "AMBIGUOUS_OWNER_MARKER", number, repository)
    if len(valid_closings) > 1:
        return _result("UNKNOWN", "AMBIGUOUS_CLOSING_MARKER", number, repository)
    closing_owner = None
    if valid_closings:
        # GitHub interprets PR closing keywords for the default branch only.
        base = pr["base"]
        default = base["repo"].get("default_branch")
        if (
            type(default) is not str or not default
            or type(base.get("ref")) is not str
            or base["ref"] != default
        ):
            return _result("UNKNOWN", "CLOSING_RELATION_BASE_NOT_PROVEN", number, repository)
        closing_owner = _parse_closing_issue(valid_closings[0], repository)
        if closing_owner is None:
            return _result("UNKNOWN", "UNCANONICAL_CLOSING_MARKER", number, repository)
    if filled:
        scoped_owner = _parse_owner_issue(filled[0], repository)
        if scoped_owner is None:
            return _result("UNKNOWN", "UNCANONICAL_OWNER_MARKER", number, repository)
        if closing_owner is not None and scoped_owner != closing_owner:
            return _result("UNKNOWN", "CONTRADICTORY_OWNER_AND_CLOSING_MARKER", number, repository)
    elif closing_owner is not None:
        scoped_owner = closing_owner
    else:
        return _result("NOT_APPLICABLE", "NO_PR_OR_OWNER_REFERENCE", number, repository)
    owner_repository, owner = scoped_owner
    owner_receipt = pilot._read_json(
        f"repos/{owner_repository}/issues/{owner}"
    )
    if owner_receipt is None:
        return _result("UNKNOWN", "OWNER_ISSUE_READ_FAILED", number, repository)
    issue, _at = owner_receipt
    if (
        type(issue.get("number")) is not int or issue["number"] != owner
        or issue.get("html_url")
        != f"https://github.com/{owner_repository}/issues/{owner}"
        or issue.get("state") not in (
            ("open", "closed") if closing_owner is not None else ("open",)
        )
        or type(issue.get("pull_request")) is dict
    ):
        return _result("UNKNOWN", "OWNER_ISSUE_IDENTITY_NOT_PROVEN", number, repository)
    exact_link = f"https://github.com/{owner_repository}/issues/{owner}"
    explicit_url = (
        re.search(re.escape(exact_link) + r"(?=$|[\s)\],;.!?])", current)
        is not None
    )
    if owner_repository == REPOSITORY:
        # Control lives in devflow; bare #N there means a devflow Issue.
        scoped_text = (
            re.search(
                rf"(?<![A-Za-z0-9])(?:devflow)?#{owner}(?![0-9])",
                current,
            ) is not None
        )
    else:
        # A caller-local #N must not accidentally match devflow's #N.
        repo_name = owner_repository.split("/", 1)[1]
        scoped_text = (
            re.search(
                rf"(?<![A-Za-z0-9_./-])(?:{re.escape(owner_repository)}|"
                rf"{re.escape(repo_name)})#{owner}(?![0-9])",
                current,
            ) is not None
        )
    mentioned = explicit_url or scoped_text
    if not mentioned:
        return _result("UNKNOWN", "OWNER_NOT_IN_CURRENT_CONTROL", number, repository)
    answer = _result(
        "RECONCILIATION_REVIEW_REQUIRED",
        ("CLOSING_ISSUE_WITHOUT_PR_LINK" if closing_owner is not None
         else "OWNER_ACTIVE_WITHOUT_PR_LINK"),
        number, repository,
    )
    answer["owner_issue_url"] = exact_link
    return answer



def check_native_postmerge_once(
    event: dict[str, Any], repository_env: str, control_id: int = CONTROL_NUMBER
) -> dict[str, str]:
    if not pilot._scope(control_id, repository_env, 1):
        return _result("UNKNOWN", "OUT_OF_SCOPE_REPOSITORY_OR_CONTROL")
    number, event_reason = _event_number(event, repository_env, repository_env)
    if number is None:
        return _result("UNKNOWN", event_reason)
    if event_reason == "CLOSED_UNMERGED_NOT_IN_SCOPE":
        return _result("NOT_APPLICABLE", event_reason, number, repository_env)
    receipt = pilot._read_json(f"repos/kinoko34077/devflow/issues/{control_id}")
    if receipt is None:
        return _result("UNKNOWN", "CANONICAL_CONTROL_READ_FAILED", number, repository_env)
    issue, _stamp = receipt
    current = _current_next_action(issue, control_id, repository_env)
    if current is None:
        return _result("UNKNOWN", "CURRENT_CONTROL_NOT_PROVEN", number, repository_env)
    exact_link = (
        f"[PR #{number}](https://github.com/{repository_env}/pull/{number})"
    )
    if exact_link not in current:
        # A loose but exact-number PR reference cannot safely be skipped.
        if re.search(rf"\bPR\s*#{number}(?!\d)", current):
            return _result("UNKNOWN", "UNCANONICAL_CURRENT_PR_REFERENCE", number, repository_env)
        # No reference is NOT confirmation that the Control is consistent.
        return _owner_reconciliation_candidate(
            current, number, event["pull_request"]["merged_at"], repository_env
        )
    checked = pilot.check_pr_transition_once(control_id, repository_env, number)
    if checked.get("status") == "UNKNOWN":
        checked["reason"] = "EXPLICIT_REFERENCE_BUT_STAGE_NOT_PROVEN"
    return checked



def check_owner_transition_once(
    owner_repository: str, owner_number: int, control_id: int = 15,
) -> dict[str, str]:
    """Read-only Issue/Control status pilot; never interpret a dated Audit SHA."""
    # Explicit one-repository pilot. A cross-repository event subscription,
    # token scope, or fleet-wide writer is NOT created by this reader.
    if (
        owner_repository != "kinoko34077/dev_agent"
        or type(owner_number) is not int or not 1 <= owner_number <= 1_000_000_000
        or type(control_id) is not int or control_id != 15
    ):
        return _result("UNKNOWN", "OUT_OF_SCOPE_OWNER_OR_CONTROL")
    owner_url = f"https://github.com/{owner_repository}/issues/{owner_number}"
    control_url = f"https://github.com/kinoko34077/devflow/issues/{control_id}"
    control_receipt = pilot._read_json(f"repos/kinoko34077/devflow/issues/{control_id}")
    owner_receipt = pilot._read_json(f"repos/{owner_repository}/issues/{owner_number}")
    if control_receipt is None or owner_receipt is None:
        return _result("UNKNOWN", "SOURCE_READ_FAILED", owner_number, owner_repository)
    control, _ = control_receipt
    owner, _ = owner_receipt
    if (
        type(control.get("number")) is not int or control["number"] != control_id
        or control.get("title") != "[REPO] dev_agent"
        or control.get("html_url") != control_url
        or control.get("state") != "open"
        or type(control.get("body")) is not str
        or type(owner.get("number")) is not int or owner["number"] != owner_number
        or owner.get("html_url") != owner_url
        or type(owner.get("pull_request")) is dict
        or owner.get("state") not in ("open", "closed")
    ):
        return _result("UNKNOWN", "SOURCE_IDENTITY_NOT_PROVEN", owner_number, owner_repository)
    active = re.findall(
        r"^## Active Work[ \t]*\n([\s\S]*?)(?=^## |\Z)",
        control["body"], re.MULTILINE,
    )
    if len(active) != 1:
        return _result("UNKNOWN", "CURRENT_ACTIVE_WORK_NOT_PROVEN", owner_number, owner_repository)
    current = active[0].split("**HISTORICAL", 1)[0]
    link = rf"\]\({re.escape(owner_url)}\)"
    links = re.findall(link, current)
    # Exclude exact canonical Markdown links, including their display text.
    # An additional owner mention remains a review candidate even when the
    # canonical link itself appears aligned.
    other_refs = re.sub(
        rf"\[[^\]\n]*\]\({re.escape(owner_url)}\)",
        "",
        current,
    )
    qualified = re.search(
        rf"(?<![A-Za-z0-9_./-])(?:{re.escape(owner_repository)}|"
        rf"{re.escape(owner_repository.rsplit('/', 1)[1])})[ \t]*#[ \t]*"
        rf"{owner_number}(?![0-9])",
        other_refs,
    )
    bare_url = re.search(re.escape(owner_url) + r"(?![0-9])", other_refs)
    if qualified is not None or bare_url is not None:
        return _result(
            "RECONCILIATION_REVIEW_REQUIRED",
            "NONCANONICAL_OWNER_CLAIM",
            owner_number, owner_repository,
        )
    if not links:
        return _result("NOT_APPLICABLE", "OWNER_NOT_IN_CURRENT_ACTIVE_WORK", owner_number, owner_repository)
    if len(links) != 1:
        return _result("UNKNOWN", "AMBIGUOUS_OWNER_CLAIM", owner_number, owner_repository)
    stage = re.findall(
        link + r"\s+is\s+\*\*(OPEN|CLOSED / COMPLETED|CLOSED / NOT_PLANNED)\*\*",
        current,
    )
    if len(stage) != 1:
        return _result("RECONCILIATION_REVIEW_REQUIRED", "OWNER_CLAIM_NOT_CANONICAL", owner_number, owner_repository)
    if owner["state"] == "open":
        observed = "OPEN"
    elif owner.get("state_reason") == "completed":
        observed = "CLOSED / COMPLETED"
    elif owner.get("state_reason") == "not_planned":
        observed = "CLOSED / NOT_PLANNED"
    else:
        return _result("UNKNOWN", "CLOSED_REASON_NOT_PROVEN", owner_number, owner_repository)
    answer = _result(
        "ALIGNED" if stage[0] == observed else "POTENTIAL_MISMATCH",
        "EXACT_OWNER_STAGE_MATCH" if stage[0] == observed else "OWNER_STAGE_DIFFERS",
        owner_number, owner_repository,
    )
    answer["claimed_stage"] = stage[0]
    answer["observed_stage"] = observed
    answer["control_url"] = control_url
    answer["owner_issue_url"] = owner_url
    return answer



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Devflow read-only merged-PR Control check")
    parser.add_argument("--event-path")
    parser.add_argument("--owner-issue", type=int)
    parser.add_argument("--owner-repository", default="kinoko34077/dev_agent")
    parser.add_argument("--repository", default=REPOSITORY)
    parser.add_argument("--control", type=int, default=CONTROL_NUMBER)
    args = parser.parse_args(argv)
    if args.owner_issue is not None:
        result = check_owner_transition_once(args.owner_repository, args.owner_issue, args.control)
    elif not args.event_path:
        result = _result("UNKNOWN", "EVENT_PATH_REQUIRED")
    else:
        try:
            if Path(args.event_path).stat().st_size > EVENT_MAX_BYTES:
                raise ValueError("event too large")
            event = json.loads(Path(args.event_path).read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            result = _result("UNKNOWN", "EVENT_UNAVAILABLE_OR_INVALID")
        else:
            result = check_native_postmerge_once(event, args.repository, args.control)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["status"] in ("ALIGNED", "NOT_APPLICABLE"):
        return 0
    if result["status"] == "POTENTIAL_MISMATCH":
        return 2
    if result["status"] == "RECONCILIATION_REVIEW_REQUIRED":
        return 4
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
