#!/usr/bin/env python3
from __future__ import annotations

import logging
from typing import Any

from mcp.server import MCPServer

try:
    from .devflow_mcp_core import default_service
except ImportError:  # direct script execution
    from devflow_mcp_core import default_service

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

mcp = MCPServer(
    SERVER_NAME,
    version=SERVER_VERSION,
    instructions=SERVER_INSTRUCTIONS,
    log_level="INFO",
)


def _service():
    return default_service()


@mcp.tool()
def bootstrap_repository(repository: str) -> dict[str, Any]:
    """Return live Repository Control state plus the canonical read order for one managed repository."""
    return _service().bootstrap_repository(repository)


@mcp.tool()
def get_repository_control(repository: str) -> dict[str, Any]:
    """Return the exact open devflow `[REPO] <repository>` Control Issue as structured live state."""
    return _service().get_repository_control(repository)


@mcp.tool()
def list_managed_repositories() -> list[str]:
    """List repositories that currently have an open devflow Repository Control Issue."""
    return _service().list_managed_repositories()


@mcp.tool()
def get_issue(repository: str, issue_number: int) -> dict[str, Any]:
    """Read one GitHub Issue from a repository. Private repositories require a read-capable token."""
    return _service().get_issue(repository, issue_number)


@mcp.tool()
def get_sync_health() -> dict[str, Any]:
    """Return the machine-maintained devflow Project Sync Health record."""
    return _service().get_sync_health()


if __name__ == "__main__":
    logger.info("Starting %s %s", SERVER_NAME, SERVER_VERSION)
    mcp.run()
