#!/usr/bin/env python3
from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from mcp import types
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from pydantic import Field, ValidationError

try:
    from .agent_inbox import MAX_INBOX_TASKS
    from .devflow_mcp_core import DEFAULT_OWNER, default_service
    from .kaep_mailbox_codec import RECIPIENT_ORDER
    from .private_ci_billing_mcp_read import get_configured_billing_observation
except ImportError:  # direct script execution
    from agent_inbox import MAX_INBOX_TASKS
    from devflow_mcp_core import DEFAULT_OWNER, default_service
    from kaep_mailbox_codec import RECIPIENT_ORDER
    from private_ci_billing_mcp_read import get_configured_billing_observation

SERVER_NAME = "KiNoTch Devflow"
SERVER_VERSION = "1.0.0"
SERVER_INSTRUCTIONS = """
This server provides read-only access to KiNoTch live development control state.
Use bootstrap_repository first when resuming, auditing, planning, implementing, reviewing,
or asking for the current state of a managed repository.
Treat devflow as the cross-repository operational authority and the owning repository as the
detailed technical authority. GitHub Project is display-only.
Do not infer current Work Status, Audit SHA, Active Work, blockers or Sync Health from chat
history or static guideline files when this server is available.
For durable progress/evidence/handoff, follow Issue-first reporting in the returned control state.
This server exposes no GitHub mutation tools.
""".strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(SERVER_NAME)

# mcp[cli]==2.2.0 wraps Pydantic argument failures in ToolError.__cause__.
# Keep UnexpectedToolError and non-validation failures unchanged; the pinned
# MCP runtime contract tests exercise this exception-chain dependency.
class _SafeValidationMCPServer(MCPServer):
    """Keep caller-provided invalid values out of tool validation responses."""

    async def call_tool(self, name, arguments, context=None):
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as exc:
            if isinstance(exc, UnexpectedToolError) or not isinstance(exc.__cause__, ValidationError):
                raise
            fields = sorted({str(error["loc"][0]) for error in exc.__cause__.errors() if error["loc"]})
            field_list = ", ".join(fields) if fields else "arguments"
            raise ToolError(
                f"Error executing tool {name}: invalid arguments for {field_list}. "
                "Check tools/list for accepted values and input constraints."
            ) from exc.__cause__


mcp = _SafeValidationMCPServer(
    SERVER_NAME,
    version=SERVER_VERSION,
    instructions=SERVER_INSTRUCTIONS,
    log_level="INFO",
)

RepositoryName = Annotated[
    str,
    Field(
        description=(
            f"Repository as owner/name, or a short name under {DEFAULT_OWNER}; "
            "outer whitespace is trimmed and whitespace within the owner or name is rejected."
        )
    ),
]
PositiveIssueNumber = Annotated[
    int,
    Field(
        ge=1,
        strict=True,
        description="Positive JSON integer GitHub Issue number; minimum value is 1.",
    ),
]
InboxLimit = Annotated[
    int,
    Field(
        ge=1,
        le=MAX_INBOX_TASKS,
        strict=True,
        description=(
            f"TASK Issues to read in this page (1–{MAX_INBOX_TASKS}; default {MAX_INBOX_TASKS}). "
            "Strict JSON integer; numeric strings and floats are rejected. "
            "This is a per-call TASK Issue mailbox bound; each Issue retains the 500-comment bound."
        ),
    ),
]
InboxOffset = Annotated[
    int,
    Field(
        ge=0,
        strict=True,
        description=(
            "Strict JSON integer; numeric strings and floats are rejected. "
            "Zero-based TASK Issue offset (default 0). Continue with next_offset "
            "only when truncated is true."
        ),
    ),
]
_RecipientValues = Literal[tuple(RECIPIENT_ORDER)]
InboxRecipient = Annotated[
    _RecipientValues,
    Field(description="Exact KAEP recipient identifier."),
]
WorkStatusFilter = Annotated[
    str,
    Field(
        min_length=1,
        description=(
            "Optional exact Work Status filter; empty strings are rejected. "
            "Unknown nonempty values may return a filtered zero-item page."
        ),
    ),
] | None
IncludeRecentKaep = Annotated[
    bool,
    Field(
        description=(
            "Opt in to the bounded recent KAEP source observation; defaults to false. "
            "This does not establish complete historical coverage."
        )
    ),
]
BillingIncludeAmounts = Annotated[
    bool,
    Field(strict=True, description=(
        "Default false: show only observation status, source and freshness. "
        "True explicitly includes private account billing amounts from the already-configured "
        "local cache. Never copy these amounts to public Issue/PR/CI logs."
    )),
]
IncludePublishedSupply = Annotated[
    bool,
    Field(
        description=(
            "Opt in to observing published supply candidates; defaults to false. "
            "This does not establish Claim eligibility."
        )
    ),
]
PlanPacket = Annotated[
    dict[str, Any],
    Field(
        description=(
            "Exact top-level keys: schema_version=1, task_ref (the normalized repository#issue_number "
            "passed to this call; matching is case-insensitive), "
            "and steps (1–64). Each step has a unique id (1–120 ASCII identifier chars), "
            "non-empty intent (up to 1000 chars), and optional declared_effects. Each effect "
            "has non-empty key and scope (up to 200 chars), plus state=set with value or "
            "state=removed without value; at most 128 effects total. Example: "
            '{"schema_version":1,"task_ref":"kinoko34077/devflow#14","steps":'
            '[{"id":"docs","intent":"Update the usage guide","declared_effects":'
            '[{"key":"guide","scope":"docs/guide.md","state":"set","value":true}]}]}. '
            "Malformed packets remain eligible for a NEEDS_EVIDENCE advisory. "
            "See docs/operations/DEVFLOW_MCP.md for the accepted packet usage; validators own exact bounds."
        )
    ),
]
OutcomeEvidence = Annotated[
    dict[str, Any] | None,
    Field(
        description=(
            "Nullable packet with exactly task_ref, issue_body_sha256, required_surface, "
            "required_target, observed_surface, observed_target, observed_result, evidence_refs. "
            "task_ref must exactly match (case-sensitively) the normalized repository#issue_number "
            "passed to this call. "
            "Use a lower-case 64-hex SHA-256 of the current Issue body; surfaces match "
            "[A-Z][A-Z0-9_]{0,63}, targets are 1–256 printable ASCII chars, and evidence_refs "
            "contains 1–8 unique URLs of the form "
            "https://github.com/kinoko34077/<repo>/issues/<issue>#issuecomment-<comment>. "
            "observed_result is SUCCESS, FAILURE, "
            "VALID_NEGATIVE, UNKNOWN, or NOT_RUN. Replace the example digest with the current "
            "Issue body's SHA-256. Example: "
            '{"task_ref":"kinoko34077/devflow#14","issue_body_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
            '"required_surface":"PUBLIC_BROWSER","required_target":"git:abc123",'
            '"observed_surface":"PUBLIC_BROWSER","observed_target":"git:abc123",'
            '"observed_result":"SUCCESS","evidence_refs":'
            '["https://github.com/kinoko34077/devflow/issues/14#issuecomment-123"]}. '
            "Null or incomplete packets return NEEDS_EVIDENCE. DECLARED_ALIGNED checks "
            "declared identities only; it does not fetch/authenticate linked comments or acceptance. "
            "See docs/operations/DEVFLOW_MCP.md for the accepted packet usage; validators own exact bounds."
        )
    ),
]


def _service():
    return default_service()


@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def bootstrap_repository(repository: RepositoryName) -> dict[str, Any]:
    """Start a current-state task by reading the live Repository Control and its canonical entry order.

    The result identifies the cross-repository authority and repository-local sources to read next.
    This is a read-only routing result; it does not grant execution or mutation authority.
    """
    return _service().bootstrap_repository(repository)


@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def get_repository_control(repository: RepositoryName) -> dict[str, Any]:
    """Read the exact open devflow `[REPO] <repository>` Control Issue for one managed repository.

    Use it for the manual cross-repository Active Work, Next Action, and canonical entry points.
    It is a control record, not a complete repository task inventory.
    """
    return _service().get_repository_control(repository)


@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def list_managed_repositories() -> list[str]:
    """List repository names with a currently open devflow Repository Control Issue.

    Use this to discover managed repository names before reading a repository-specific source.
    The result does not report task-level coverage or whether all work is known.
    """
    return _service().list_managed_repositories()


@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def get_repository_projection(repository: RepositoryName) -> dict[str, Any]:
    """Read the repository-local Issue projection and its source, freshness, and coverage fields.

    Use it for a bounded view of classified repository Issues. Check the source and coverage status
    before treating an empty projection as evidence that no work exists.
    """
    return _service().get_repository_projection(repository)


@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def get_repository_work_view(repository: RepositoryName) -> dict[str, Any]:
    """Discover current all-status owner TASKs with the explicit legacy Control fallback.

    Inspect coverage, unresolved counts, and each TASK record; INCOMPLETE or UNKNOWN coverage
    does not establish an empty inventory. The returned read-only view cannot authorize execution.
    """
    return _service().get_repository_work_view(repository)


@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def get_scoped_task_read(
    repository: RepositoryName,
    issue_number: PositiveIssueNumber,
) -> dict[str, Any]:
    """Verify one exact known owner TASK Issue and its current structured work metadata.

    Use this for a referenced Issue after discovery. It covers that Issue only; it does not
    establish repository-wide work coverage or authorize a claim.
    """
    return _service().get_scoped_task_read(repository, issue_number)


@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def get_agent_inbox(
    repository: RepositoryName, recipient: InboxRecipient = "claude-code",
    limit: InboxLimit = MAX_INBOX_TASKS, offset: InboxOffset = 0,
    work_status: WorkStatusFilter = None,
) -> dict[str, Any]:
    """Read a bounded page of trusted TASK Issues for one exact KAEP recipient.

    The page limit applies to TASK Issue mailboxes, not comments; its bounds and default are
    published in the input schema. Each Issue retains its existing 500-comment bound. Follow
    next_offset only when truncated is true. Coverage and
    filtered-zero results must be interpreted with their status fields; Inbox visibility is read-only and grants
    no execution, Claim, ACK, or delivery authority.
    """
    return _service().get_agent_inbox(
        repository, recipient, limit=limit, offset=offset,
        work_status=work_status)


@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def get_agent_workspace(
    repository: RepositoryName, recipient: InboxRecipient = "codex",
    limit: InboxLimit = MAX_INBOX_TASKS, offset: InboxOffset = 0,
    work_status: WorkStatusFilter = None,
    include_recent_kaep: IncludeRecentKaep = False,
    include_published_supply: IncludePublishedSupply = False,
) -> dict[str, Any]:
    """Read the bounded unified Work view with optional KAEP and published-supply observations.

    `include_recent_kaep` and `include_published_supply` default to false and opt in to those
    sections. Inspect source status, coverage, and unknown sections; the result does not establish
    all-history completeness, live agent pickup, Offer/Claim eligibility, or execution authority.
    """
    return _service().get_agent_workspace(
        repository, recipient, limit=limit, offset=offset,
        work_status=work_status, include_recent_kaep=include_recent_kaep,
        include_published_supply=include_published_supply,
    )


@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def get_portfolio_projection() -> dict[str, Any]:
    """Read observed aggregate counts and repository summaries across managed repositories.

    Check each source and coverage status before using the projection; unavailable or incomplete
    sources remain visible. Use a repository-specific read for an exact Issue decision.
    """
    return _service().get_portfolio_projection()


@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def get_human_portfolio(repository: RepositoryName) -> dict[str, Any]:
    """Read the current Human Portfolio queue for one managed repository.

    Use entry dispositions and evidence freshness to identify work awaiting human attention.
    The queue is a read-only projection and can retain incomplete or unresolved source status.
    """
    return _service().get_human_portfolio(repository)


@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def get_issue(
    repository: RepositoryName,
    issue_number: PositiveIssueNumber,
) -> dict[str, Any]:
    """Read one exact GitHub Issue by repository and positive Issue number.

    The result contains the observed Issue identity, body, parsed sections, and update time.
    Private repositories require an already configured read-capable token.
    """
    return _service().get_issue(repository, issue_number)


@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def get_issue_goal_context(
    repository: RepositoryName,
    issue_number: PositiveIssueNumber,
) -> dict[str, Any]:
    """Resolve source-linked effective Goal Context for one Issue through bounded read-only ancestry.

    Inspect source references and resolution status before using adopted conditions. The result
    resolves declarations; it does not prove implementation behavior or user acceptance.
    """
    return _service().get_issue_goal_context(repository, issue_number)


@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def assess_issue_plan(
    repository: RepositoryName,
    issue_number: PositiveIssueNumber,
    plan: PlanPacket,
) -> dict[str, Any]:
    """Compare one declared plan with the Issue's adopted source-linked conditions.

    The plan argument schema in tools/list contains the accepted packet keys,
    bounds, and example; see docs/operations/DEVFLOW_MCP.md for usage.
    This is advisory only: no execution permission or task-wide acceptance.
    """
    return _service().assess_issue_plan(repository, issue_number, plan)


@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def assess_outcome_observation(
    repository: RepositoryName,
    issue_number: PositiveIssueNumber,
    evidence: OutcomeEvidence,
) -> dict[str, Any]:
    """Compare declared outcome identities against one Issue's current body revision.

    The evidence argument schema in tools/list contains the exact packet fields,
    constraints, and example; see docs/operations/DEVFLOW_MCP.md for usage.
    No evidence URL is authenticated here, and alignment does not prove acceptance
    or authorize any execution.
    """
    return _service().assess_outcome_observation(repository, issue_number, evidence)


@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def get_sync_health() -> dict[str, Any]:
    """Read the machine-maintained devflow Project Sync Health record.

    This reports Project synchronization status and diagnostics. It does not assess technical
    correctness, repository task completeness, or Issue acceptance.
    """
    return _service().get_sync_health()


@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def get_github_actions_billing_observation(
    include_amounts: BillingIncludeAmounts = False,
) -> dict[str, Any]:
    """Read the owner's current-month GitHub Actions billing UI observation, never refresh it.

    The pinned, private local path must be configured by the MCP host using
    DEVFLOW_GITHUB_BILLING_UI_CACHE. No path, account, URL or command is accepted
    from a remote caller. No file/network/credential access outside that one
    local cache. Missing or stale observations return UNKNOWN, not a guess.
    Default summary omits amounts; include_amounts=true explicitly returns
    the private observed USD figures only to this MCP client. This is
    advisory, not quota remaining proof or authorization to run Private CI.
    """
    return get_configured_billing_observation(include_amounts=include_amounts)


if __name__ == "__main__":
    logger.info("Starting %s %s", SERVER_NAME, SERVER_VERSION)
    mcp.run()
