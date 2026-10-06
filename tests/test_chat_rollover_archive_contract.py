import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMAND = "kinoko34077/devflow#361を読んで、このチャット全体を議事録化し、後続チャット用資料を作成"
LEGACY = "ガイドライン読んで引き継ぎ"


class ChatRolloverArchiveContractTests(unittest.TestCase):
    def test_preferred_command_is_issue_addressed_on_all_operator_surfaces(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        operations = (ROOT / "docs/operations/CHAT_ROLLOVER_ARCHIVE.md").read_text(encoding="utf-8")
        manual = (ROOT / "docs/operations/AGENT_OPERATING_MANUAL.md").read_text(encoding="utf-8")
        for text in (agents, operations, manual):
            self.assertIn(COMMAND, text)
            self.assertIn("kinoko34077/devflow#361", text)

    def test_machine_contract_names_standing_issue_and_explicit_action_direction(self):
        workflow = (ROOT / ".devflow/WORKFLOW.yaml").read_text(encoding="utf-8")
        self.assertIn('standing_policy_issue: "kinoko34077/devflow#361"', workflow)
        self.assertIn(f'canonical_command: "{COMMAND}"', workflow)
        self.assertIn("canonical_command_requires_issue_lookup_first: true", workflow)
        self.assertIn("current_worker_records_current_chat_and_creates_successor_material_not_resume_or_takeover", workflow)
        self.assertIn(f'legacy_shorthand: "{LEGACY}"', workflow)
        self.assertIn("legacy_shorthand_status: ambiguous_not_preferred", workflow)

    def test_old_phrase_is_legacy_and_archive_outputs_remain_paired(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        operations = (ROOT / "docs/operations/CHAT_ROLLOVER_ARCHIVE.md").read_text(encoding="utf-8")
        self.assertIn(LEGACY, agents)
        self.assertIn("legacy/ambiguous", agents)
        self.assertIn(LEGACY, operations)
        self.assertIn("legacy/ambiguous", operations)
        self.assertIn("[MINUTES]", operations)
        self.assertIn("[HANDOFF]", operations)
        self.assertIn("do not take over or resume successor work", operations)


if __name__ == "__main__":
    unittest.main()
