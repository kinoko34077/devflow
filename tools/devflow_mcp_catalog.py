"""Shared, narrowly scoped MCP catalog admission (#805).

Catalog validity is not proof of authority or tool semantics. The existing
trusted release/CI/review and runtime isolation gates remain mandatory.
No network schema resolution, automatic privilege grants, or guessed adapters.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.validators import validator_for
from referencing import Registry


class CatalogError(ValueError):
    """Credential-free, bounded catalog rejection."""


RESTART_TOOL = "restart_mcp"
REPOSITORY = "kinoko34077/devflow"
# Actual existing consumer calls; not an inventory or a fixed catalog size.
REQUIRED_CALLS = {
    "bootstrap_repository": {"repository": REPOSITORY},
    "get_human_portfolio": {"repository": REPOSITORY},
    "get_repository_work_view": {"repository": REPOSITORY},
    "get_agent_inbox": {"repository": REPOSITORY, "recipient": "codex", "limit": 1, "offset": 0},
    "get_agent_workspace": {"repository": REPOSITORY, "recipient": "codex", "limit": 1, "offset": 0},
}
SMOKE_CALLS = ("bootstrap_repository", "get_human_portfolio")
# The original verified, annotation-free read-only interface is a bounded
# compatibility exception, not a required inventory or a fixed tool count.
LEGACY_UNANNOTATED_READS = frozenset({
    "bootstrap_repository", "get_repository_control", "list_managed_repositories",
    "get_repository_projection", "get_repository_work_view", "get_scoped_task_read",
    "get_agent_inbox", "get_agent_workspace", "get_portfolio_projection",
    "get_human_portfolio", "get_issue", "get_issue_goal_context",
    "assess_issue_plan", "assess_outcome_observation", "get_sync_health",
    "get_github_actions_billing_observation",
})


def _validator(schema: object):
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise CatalogError("MCP tool schema must describe an object")
    cls = (validator_for(schema, default=None) if "$schema" in schema
           else Draft202012Validator)
    if cls is None:
        raise CatalogError("unsupported MCP schema dialect")
    try:
        cls.check_schema(schema)
        # An empty registry deliberately disables remote reference retrieval.
        return cls(schema, registry=Registry())
    except Exception as error:
        raise CatalogError("invalid MCP tool schema") from error


def admit_catalog(
    tools: Sequence[Any], *, next_cursor: object = None,
    required_calls: Mapping[str, Mapping[str, Any]] = REQUIRED_CALLS,
) -> dict[str, Any]:
    """Validate the complete observed worker catalog, not its equality to old.

    Accept additive and optional changes; require known essential call inputs.
    Reject explicit incompatible effects and newly introduced tools without an
    explicit read-only declaration. Only the verified legacy names may omit it.
    An annotation never proves authority or actual implementation safety.
    SDK tools are retained so the connection can publish their actual schemas.
    """
    if next_cursor is not None:
        raise CatalogError("incomplete MCP tool catalog")
    result: dict[str, Any] = {}
    for tool in tools:
        name = tool.name
        if not isinstance(name, str) or not name.strip() or name in result or name == RESTART_TOOL:
            raise CatalogError("invalid, duplicate or reserved MCP tool name")
        validator = _validator(tool.input_schema)
        output = getattr(tool, "output_schema", None)
        if output is not None:
            _validator(output)
        annotations = getattr(tool, "annotations", None)
        if annotations is not None and (
            getattr(annotations, "read_only_hint", None) is False
            or getattr(annotations, "destructive_hint", None) is True
        ):
            raise CatalogError("MCP tool declares incompatible side effects")
        if (name not in LEGACY_UNANNOTATED_READS
                and getattr(annotations, "read_only_hint", None) is not True):
            raise CatalogError("new MCP tool lacks a read-only declaration")
        if name in required_calls:
            try:
                validator.validate(dict(required_calls[name]))
            except Exception as error:
                raise CatalogError("essential MCP call contract unavailable") from error
        result[name] = tool
    if not result or not required_calls.keys() <= result.keys():
        raise CatalogError("essential MCP tools unavailable")
    return result


def arguments_supported(tool: Any, arguments: Mapping[str, Any]) -> bool:
    """Check an actual request; do not coerce or invent argument semantics."""
    try:
        _validator(tool.input_schema).validate(dict(arguments))
    except Exception:
        return False
    return True
