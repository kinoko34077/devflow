"""Read-only KAEP Agent Inbox projection; not a task queue or runtime authority.

Uses existing trusted M3 Repository Work View for task discovery and the
unchanged KAEP v0.2 codec for source-Issue message correlation. This is only a
GET-side read model; it cannot schedule, claim, dispatch or approve work.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

try:
    from .kaep_mailbox_codec import InvalidMessage, RECIPIENTS, read_mailbox
except ImportError:  # direct stdio script from the tools directory
    from kaep_mailbox_codec import InvalidMessage, RECIPIENTS, read_mailbox

MAX_INBOX_TASKS = 20
MAX_ISSUE_COMMENTS = 500
KNOWN_REPLY_KINDS = frozenset({"ACK", "ANSWER", "BLOCKED", "ERROR", "RESULT"})


def _validate_options(recipient: str, limit: int, offset: int, work_status: str | None) -> None:
    if type(recipient) is not str or recipient not in RECIPIENTS:
        raise ValueError("INVALID_RECIPIENT")
    if type(limit) is not int or not 1 <= limit <= MAX_INBOX_TASKS:
        raise ValueError("INVALID_LIMIT")
    if type(offset) is not int or offset < 0:
        raise ValueError("INVALID_OFFSET")
    if work_status is not None and (type(work_status) is not str or not work_status):
        raise ValueError("INVALID_WORK_STATUS")


def select_task_records(
    work_view: Mapping[str, Any], *, recipient: str,
    limit: int = MAX_INBOX_TASKS, offset: int = 0,
    work_status: str | None = None,
) -> dict[str, Any]:
    """Select verified machine TASKs only; no automatic agent ownership."""
    _validate_options(recipient, limit, offset, work_status)
    is_current = (
        work_view.get("source_status") == "AVAILABLE"
        and work_view.get("source_freshness") == "CURRENT"
    )
    observed = work_view.get("observed_task_view") or {}
    rows: list[dict[str, Any]] = []
    if is_current:
        for record in work_view.get("task_records") or []:
            if record.get("record_role") != "TASK":
                continue
            if work_status is not None and record.get("work_status") != work_status:
                continue
            rows.append(record)
    rows.sort(key=lambda row: row.get("issue_number", 0))
    selected = rows[offset:offset + limit] if is_current else []
    return {
        "repository": work_view.get("repository"),
        "recipient": recipient,
        "source_status": work_view.get("source_status"),
        "source_freshness": work_view.get("source_freshness"),
        "observed_task_status": observed.get("status"),
        "source_error": work_view.get("source_error"),
        "coverage_status": work_view.get("coverage_status"),
        "unresolved_open_issue_count": observed.get("unresolved_open_issue_count"),
        "known_task_count": observed.get("known_task_count"),
        "manual_control": work_view.get("manual_control"),
        "can_authorize_execution": False,
        "can_replace_manual_active_work": False,
        "is_full_work_inventory": bool(is_current and observed.get("is_complete_read")),
        "task_count_filtered": len(rows) if is_current else None,
        "next_offset": (offset + len(selected)) if is_current and offset + len(selected) < len(rows) else None,
        "truncated": bool(is_current and offset + len(selected) < len(rows)),
        "selected": selected,
    }


def _issue_messages(
    comments: Sequence[Mapping[str, Any]], *, repository: str,
    issue_number: int, recipient: str, expected_actor: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read correlation from complete stored comments; never return raw prompts."""
    if len(comments) > MAX_ISSUE_COMMENTS:
        raise InvalidMessage("ISSUE_COMMENTS_LIMIT")
    task_ref = f"{repository}#{issue_number}"
    parsed = read_mailbox(comments, task_ref=task_ref)
    actors: dict[int, str] = {}
    for comment in comments:
        cid, user = comment.get("id"), comment.get("user")
        if type(cid) is not int or type(user) is not dict:
            raise InvalidMessage("INVALID_GITHUB_COMMENT")
        login = user.get("login")
        if type(login) is not str or not login:
            raise InvalidMessage("INVALID_GITHUB_ACTOR")
        actors[cid] = login
    roots: dict[str, tuple[int, dict[str, Any]]] = {}
    warnings: list[dict[str, Any]] = []
    for cid, msg in parsed:
        if msg["kind"] != "REQUEST" or msg["in_reply_to"] is not None:
            continue
        if msg["recipient"] != recipient or msg["scope"]["effect"] != "READ_ONLY":
            continue
        if actors[cid].casefold() != expected_actor.casefold():
            warnings.append({"comment_id": cid, "reason_code": "UNTRUSTED_ROOT_ACTOR"})
            continue
        roots[msg["message_id"]] = (cid, msg)
    out: list[dict[str, Any]] = []
    for message_id, (cid, root) in roots.items():
        reply_kinds = sorted({
            msg["kind"] for reply_id, msg in parsed
            if msg["in_reply_to"] == message_id
            and msg["exchange_id"] == root["exchange_id"]
            and msg["task_ref"] == root["task_ref"]
            and msg["scope"] == root["scope"]
            and msg["intent"] == root["intent"]
            and msg["kind"] in KNOWN_REPLY_KINDS
            and msg["recipient"] != recipient
            and actors[reply_id].casefold() == expected_actor.casefold()
        })
        out.append({
            "source_comment_id": cid,
            "source_message_id": message_id,
            "exchange_id": root["exchange_id"],
            "intent": root["intent"],
            "expected_head": root["scope"]["expected_head"],
            "reply_kinds_observed": reply_kinds,
            "status": "ANSWER_OBSERVED" if "ANSWER" in reply_kinds else
                      "BLOCKED_OBSERVED" if "BLOCKED" in reply_kinds else
                      "ACK_OBSERVED" if "ACK" in reply_kinds else "PENDING_REPLY",
            "source_url": f"https://github.com/{repository}/issues/{issue_number}#issuecomment-{cid}",
            "actor_login_verified_only": True,
        })
    out.sort(key=lambda row: row["source_comment_id"])
    return out, warnings


def build_agent_inbox(
    work_view: Mapping[str, Any], *,
    recipient: str, comments_by_issue: Mapping[int, Sequence[Mapping[str, Any]]],
    errors_by_issue: Mapping[int, str] | None = None,
    limit: int = MAX_INBOX_TASKS, offset: int = 0,
    work_status: str | None = None, expected_actor: str = "kinoko34077",
) -> dict[str, Any]:
    """Produce a bounded read-only observation, not an assignment/Claim."""
    if type(expected_actor) is not str or not expected_actor:
        raise ValueError("INVALID_EXPECTED_ACTOR")
    selection = select_task_records(
        work_view, recipient=recipient, limit=limit, offset=offset,
        work_status=work_status)
    issues: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if selection["source_status"] == "AVAILABLE" and selection["source_freshness"] == "CURRENT":
        for record in selection["selected"]:
            number = record["issue_number"]
            item = {
                "issue_number": number, "url": record["url"],
                "title": record["title"], "work_status": record["work_status"],
                "record_role": "TASK", "recipient_assignment_inferred": False,
                "requests": None, "source_state": "UNAVAILABLE",
            }
            if number in (errors_by_issue or {}):
                errors.append({"issue_number": number, "reason_code": errors_by_issue[number]})
            elif number not in comments_by_issue:
                errors.append({"issue_number": number, "reason_code": "COMMENTS_NOT_READ"})
            else:
                try:
                    item["requests"], warnings = _issue_messages(
                        comments_by_issue[number],
                        repository=selection["repository"], issue_number=number,
                        recipient=recipient, expected_actor=expected_actor)
                    item["source_state"] = "AVAILABLE"
                    errors.extend({"issue_number": number, **warning} for warning in warnings)
                except (InvalidMessage, ValueError) as exc:
                    errors.append({"issue_number": number, "reason_code": str(exc)})
            issues.append(item)
    return {
        **{key: value for key, value in selection.items() if key != "selected"},
        "schema_version": "kaep.agent-inbox.read.v0.1",
        "issues": issues,
        "errors": errors,
        "has_unknown_work": not selection["is_full_work_inventory"] or selection["truncated"] or bool(errors),
        "is_authoritative_assignment": False,
        "is_live_agent_delivery": False,
    }
