"""Public machine-readable KAEP discovery snapshot, not an authority or live inbox.

A small allowlisted GET document for agent source locators. Consumers MUST re-read
the canonical source Issue and strict KAEP reply chain before any action.
"""
from __future__ import annotations

import re
from typing import Any

from tools.kaep_issue_list_html import _safe_link

_ROW_KEYS = ("repository", "issue_number", "issue_url", "source_url",
             "issue_state", "issue_role", "issue_type", "role_source",
             "recipient", "intent", "reply_observation",
             "source_validation", "message_id", "source_comment_id",
             "head_freshness")
_REPO = re.compile(r"kinoko34077/[A-Za-z0-9_.-]+\Z")


def to_public_index(result: dict[str, Any]) -> dict[str, Any]:
    """Fail closed on blocked/malformed source; publish no raw Issue bodies."""
    if type(result) is not dict or result.get("status") not in (
            "BOUNDED_SEARCH_READ", "PARTIAL_UNKNOWN"):
        raise ValueError("PUBLIC_INDEX_SOURCE_BLOCKED")
    rows = result.get("rows")
    errors = result.get("errors")
    repos = result.get("repositories")
    if type(rows) is not list or type(errors) is not list or type(repos) is not list:
        raise ValueError("PUBLIC_INDEX_INVALID_SOURCE")
    if len(repos) > 3 or any(type(x) is not str or not _REPO.fullmatch(x)
                            for x in repos):
        raise ValueError("PUBLIC_INDEX_INVALID_REPOSITORY")
    if len(rows) > 4000 or len(errors) > 100:
        raise ValueError("PUBLIC_INDEX_LIMIT")
    public_rows = []
    for item in rows:
        if type(item) is not dict:
            raise ValueError("PUBLIC_INDEX_INVALID_ROW")
        row = {key: item.get(key) for key in _ROW_KEYS}
        if (type(row["repository"]) is not str
                or row["repository"] not in repos
                or type(row["issue_number"]) is not int
                or row["issue_number"] < 1
                or type(row["source_comment_id"]) is not int
                or row["source_comment_id"] < 1
                or row["issue_url"] != f'https://github.com/{row["repository"]}/issues/{row["issue_number"]}'
                or not _safe_link(row["issue_url"], source=False)
                or not _safe_link(row["source_url"], source=True)
                or not str(row["source_url"]).startswith(row["issue_url"] + "#issuecomment-")):
            raise ValueError("PUBLIC_INDEX_INVALID_LOCATOR")
        for key in _ROW_KEYS:
            if key in ("issue_number", "source_comment_id"):
                continue
            if type(row[key]) is not str or len(row[key]) > 256:
                raise ValueError("PUBLIC_INDEX_INVALID_FIELD")
        public_rows.append(row)

    public_errors = []
    for item in errors:
        if type(item) is not dict or type(item.get("reason_code")) is not str:
            raise ValueError("PUBLIC_INDEX_INVALID_DIAGNOSTIC")
        reason = item["reason_code"]
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", reason):
            raise ValueError("PUBLIC_INDEX_INVALID_DIAGNOSTIC")
        locator = item.get("owning_issue")
        # Unknown/bad URLs are not published as active links.
        if locator is not None and not _safe_link(locator, source=False):
            locator = None
        public_errors.append({"reason_code": reason, "owning_issue": locator})

    out = {
        "schema_version": "kaep.public-source-index.v1",
        "kind": "NON_AUTHORITATIVE_CANDIDATE_SNAPSHOT",
        "observed_at": result.get("observed_at"),
        "status": result["status"],
        "source_coverage": "SEARCH_INDEX_NOT_AUTHORITATIVE",
        "repositories": repos,
        "rows": public_rows,
        "errors": public_errors,
        "has_unknown_work": True,
        "complete_source_universe": False,
        "can_authorize_execution": False,
        "fallback_retirement_authorized": False,
        "requires_live_original_issue_revalidation": True,
        "preferred_live_read": "get_agent_inbox / tools.kaep_agent_inbox_cli",
        "fallback": "devflow manual Control + KAEP #503 pointer",
    }
    if type(out["observed_at"]) is not str or len(out["observed_at"]) > 64:
        raise ValueError("PUBLIC_INDEX_INVALID_TIMESTAMP")
    return out
