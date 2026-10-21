"""Regression guard: Codex Cloud incomplete Inbox uses existing B6 reader.

This is a documentation/integration contract, not a simulated Cloud runtime.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
UNION_COMMAND = (
    "python -m tools.kaep_live_union_cli "
    "--recipient codex --response-format agent-api"
)


class CodexIncompleteInboxFallbackDocsTests(unittest.TestCase):
    def test_agent_start_routes_partial_codex_inbox_to_existing_b6(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        section = agents.split(
            "### Codex Cloud with no exposed Devflow MCP tools", 1
        )[1].split("### KAEP Agent Inbox on an already-active Claude check-in", 1)[0]
        self.assertIn("has_unknown_work=true", section)
        self.assertIn("machine TASKs", section)
        self.assertIn(UNION_COMMAND, section)
        self.assertIn("#503 pointer fallback", section)
        self.assertIn("PARTIAL_UNKNOWN", section)
        self.assertIn("Do not start a model", section)

    def test_mcp_runbook_uses_supported_native_union_and_fail_closed_boundary(self):
        doc = (ROOT / "docs/operations/DEVFLOW_MCP.md").read_text(
            encoding="utf-8"
        )
        section = doc.split(
            "## Codex Cloud fallback when MCP tools are not registered", 1
        )[1].split("### Three-read troubleshooting", 1)[0]
        self.assertIn("coverage_status=INCOMPLETE", section)
        self.assertIn("has_unknown_work=true", section)
        self.assertIn(UNION_COMMAND, section)
        self.assertIn("PARTIAL_UNKNOWN", section)
        self.assertIn("#503 fallback", section)
        self.assertIn("cannot prove", section)
        union = (ROOT / "tools/kaep_live_union_cli.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('parser.add_argument("--recipient"', union)
        self.assertIn('choices=("union", "agent-api")', union)
        self.assertIn("project_agent_view(result)", union)
        self.assertIn("MAX_SOURCES", union)


if __name__ == "__main__":
    unittest.main()
