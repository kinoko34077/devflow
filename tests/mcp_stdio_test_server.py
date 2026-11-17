"""Deterministic subprocess server used by the public MCP contract tests."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import devflow_mcp  # noqa: E402
from tools.agent_inbox import validate_inbox_options  # noqa: E402
from tools.devflow_mcp_core import DevflowService  # noqa: E402


class FixedReader:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get_issue(self, repository: str, issue_number: int) -> dict[str, Any]:
        self.calls.append(
            {
                "method": "get_issue",
                "repository": repository,
                "issue_number": issue_number,
            }
        )
        return {
            "number": issue_number,
            "title": "MCP contract fixture",
            "state": "open",
            "body": "## Purpose\n\nExercise the MCP contract.\n",
            "repository_url": f"https://api.github.com/repos/{repository}",
            "html_url": f"https://github.com/{repository}/issues/{issue_number}",
            "updated_at": "2026-11-17T00:00:00Z",
        }


class RecordingService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.reader = FixedReader()
        self.assessor = DevflowService(self.reader)

    def __getattr__(self, name: str):
        def invoke(*args: Any, **kwargs: Any) -> Any:
            if name in {"get_agent_inbox", "get_agent_workspace"}:
                recipient = args[1] if len(args) > 1 else "claude-code"
                validate_inbox_options(
                    recipient,
                    kwargs.get("limit", 20),
                    kwargs.get("offset", 0),
                    kwargs.get("work_status"),
                )
            if name in {"assess_issue_plan", "assess_outcome_observation"}:
                result = getattr(self.assessor, name)(*args, **kwargs)
            elif name == "get_repository_control" and args == ("OUTPUT_FAILURE_SENTINEL",):
                result = object()
            elif name == "list_managed_repositories":
                result = ["kinoko34077/devflow"]
            elif name == "get_issue":
                repository, issue_number = args
                result = {
                    "repository": repository,
                    "issue_number": issue_number,
                    "title": "MCP contract fixture",
                    "state": "open",
                    "body": "## Purpose\n\nExercise the MCP contract.\n",
                    "sections": {"Purpose": "Exercise the MCP contract."},
                    "updated_at": "2026-11-17T00:00:00Z",
                    "url": f"https://github.com/{repository}/issues/{issue_number}",
                }
            else:
                result = None
            self.calls.append({"tool": name, "args": list(args), "kwargs": kwargs})
            if name == "get_sync_health":
                result = {"calls": list(self.calls), "source_reads": list(self.reader.calls)}
            elif name not in {
                "list_managed_repositories",
                "get_repository_control",
                "get_issue",
                "assess_issue_plan",
                "assess_outcome_observation",
            }:
                result = {"tool": name, "calls": list(self.calls)}
            return result

        return invoke


SERVICE = RecordingService()
devflow_mcp.default_service = lambda: SERVICE


if __name__ == "__main__":
    devflow_mcp.mcp.run()
