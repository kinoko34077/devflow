"""Read-only, bounded semantic comparison of independently collected evidence.

The caller must authenticate GitHub responses and confirm that the Control
statement is current; booleans/URLs alone CANNOT attest source provenance.
No I/O, GitHub network, workflow, permission, or write authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

DIMENSIONS = {
    "PR_GATE": frozenset({"AWAIT_REVIEW", "AWAIT_MERGE", "MERGED", "CLOSED_UNMERGED", "UNKNOWN"}),
    "PUBLIC_ENTRY": frozenset({"UNVERIFIED", "VERIFIED", "FAILED", "UNKNOWN"}),
    "FIELD_ACCEPTANCE": frozenset({"UNVERIFIED", "ACCEPTED", "REJECTED", "UNKNOWN"}),
}
CURRENT_SECTIONS = frozenset({"Next Action", "Active Work"})
MAX_READ_GAP = timedelta(hours=1)
_SUBJECT = re.compile(r"^(kinoko34077/[A-Za-z0-9_.-]+)#([1-9][0-9]*)$")
_CONTROL_PATH = re.compile(r"^/kinoko34077/devflow/issues/[1-9][0-9]*$")


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _github_path(url: Any) -> tuple[str, str] | None:
    if not isinstance(url, str):
        return None
    try:
        p = urlsplit(url)
        # Exact authority: no port, userinfo, password, query, fragments other
        # than explicit GitHub issue-comment deep links.
        if p.scheme != "https" or p.netloc != "github.com" or p.query:
            return None
        if p.fragment and not re.fullmatch(r"issuecomment-[1-9][0-9]*", p.fragment):
            return None
        return p.path, p.fragment
    except ValueError:
        return None


def compare_claim(control: Mapping[str, Any], observed: Mapping[str, Any]) -> dict[str, str]:
    """Classify one exact same-subject/current-stage Control claim.

    Trusted *complete* source reads, chronology and semantic extraction are
    obligations of the external authorized GET collector; no dict field
    authenticates an actor or authorizes automatic correction. Results are
    conservative read-only signals for further human/independent evaluation.
    """
    unknown = {"status": "UNKNOWN", "reason": "INCOMPLETE_OR_UNTRUSTED_SOURCE"}
    if not isinstance(control, Mapping) or not isinstance(observed, Mapping):
        return unknown
    required = ("repository", "subject", "dimension", "value")
    if any(not isinstance(control.get(k), str) or not control[k] for k in required):
        return unknown
    if any(not isinstance(observed.get(k), str) or not observed[k] for k in required):
        return unknown

    dim = control["dimension"]
    if dim not in DIMENSIONS or observed["dimension"] not in DIMENSIONS:
        return unknown
    m = _SUBJECT.fullmatch(control["subject"])
    if not m or control["repository"] != m.group(1):
        return unknown
    if (control["repository"], control["subject"], dim) != (
        observed["repository"], observed["subject"], observed["dimension"]
    ):
        return {"status": "NOT_COMPARABLE", "reason": "DIFFERENT_SCOPE"}
    if not (
        control.get("section") in CURRENT_SECTIONS
        and control.get("is_current") is True
        and control.get("source_verified") is True
        and observed.get("source_verified") is True
        and observed.get("source_complete") is True
    ):
        return unknown

    cu = _github_path(control.get("source_url"))
    ou = _github_path(observed.get("source_url"))
    if cu is None or not _CONTROL_PATH.fullmatch(cu[0]) or cu[1]:
        return unknown
    subject_number = m.group(2)
    base = "/" + control["repository"] + "/"
    expected_kind = "pull" if dim == "PR_GATE" else "issues"
    if ou is None or ou[0] != base + expected_kind + "/" + subject_number:
        return unknown

    ctrl_time = _timestamp(control.get("read_at"))
    obs_time = _timestamp(observed.get("read_at"))
    if ctrl_time is None or obs_time is None:
        return unknown
    gap = obs_time - ctrl_time
    if gap < timedelta(0) or gap > MAX_READ_GAP:
        return {"status": "UNKNOWN", "reason": "OBSERVATION_STALE_OR_REVERSED"}

    cv, ov = control["value"], observed["value"]
    if cv not in DIMENSIONS[dim] or ov not in DIMENSIONS[dim]:
        return unknown
    if "UNKNOWN" in (cv, ov):
        return {"status": "UNKNOWN", "reason": "UNKNOWN_STAGE"}
    # UNVERIFIED is lack of observed proof, not a refutation of an actual
    # physical/public acceptance claim outside the available GitHub evidence.
    if dim != "PR_GATE" and "UNVERIFIED" in (cv, ov):
        return {"status": "UNKNOWN", "reason": "NO_ACCEPTANCE_EVIDENCE"}
    if cv == ov:
        return {"status": "ALIGNED", "reason": "SAME_SCOPED_STAGE"}
    return {"status": "POTENTIAL_MISMATCH", "reason": "SAME_SCOPE_CONTRADICTORY_STAGE"}
