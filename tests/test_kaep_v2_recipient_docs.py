"""Contract: approved public #789 has an existing-recipient entrypoint.

These tests verify documentation and the installed CLI switches; they are
not evidence of an independently running model or live KAEP request.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CMD = (
    "python -m tools.kaep_discovery_reader --dual-shadow "
    "--expect-notice-actor kinoko34077 --expect-source-actor kinoko34077"
)


class V2ActiveRecipientDocsTests(unittest.TestCase):
    def test_agent_entrypoint_uses_existing_a3_not_an_automatic_wake(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        chunk = agents.split(
            "#### Approved #789 successor discovery for an already-running Claude recipient", 1
        )[1].split(
            "### Machine-first KAEP source discovery for any already-active agent (B6)", 1
        )[0]
        for required in (CMD, "#503", "#789", "PARTIAL_UNKNOWN",
                         "exit code 2", "source_verified_roots",
                         "index_diagnostics", "current HEAD",
                         "not proof", "timer", "ACK/ANSWER"):
            self.assertIn(required, chunk)

    def test_mcp_runbook_keeps_unknown_and_strict_origins(self):
        source = (ROOT / "docs/operations/DEVFLOW_MCP.md").read_text(encoding="utf-8")
        block = source.split(
            "### Approved #789 public pointer discovery (already-running Claude only)", 1
        )[1].split(
            "Exit code 0 means the read method returned structured data;", 1
        )[0]
        for required in (CMD, "exit code 2", "PARTIAL_UNKNOWN", "source_verified_roots",
                         "#503", "#789", "original Issue", "current HEAD",
                         "No live Claude runtime invocation"):
            self.assertIn(required, block)

    def test_documented_command_is_supported_by_real_read_only_cli(self):
        cli = (ROOT / "tools/kaep_discovery_reader.py").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--dual-shadow"', cli)
        self.assertIn('parser.add_argument("--expect-notice-actor"', cli)
        self.assertIn('parser.add_argument("--expect-source-actor"', cli)
        self.assertIn("discover_dual_index_shadow(", cli)
        self.assertIn('return 0 if result["status"] == "BOUNDED_DUAL_INDEX_READ" else 2', cli)


if __name__ == "__main__":
    unittest.main()
