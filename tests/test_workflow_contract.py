import importlib
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkflowContractTests(unittest.TestCase):
    def _contract_module(self):
        spec = importlib.util.find_spec("tools.workflow_contract")
        self.assertIsNotNone(
            spec,
            "one shared tools.workflow_contract loader must own machine workflow vocabularies",
        )
        return importlib.import_module("tools.workflow_contract")

    def test_shared_contract_loads_canonical_workflow_vocabularies(self):
        contract = self._contract_module().load_workflow_contract()
        self.assertEqual(
            contract.audit_depths,
            frozenset({"CONTROL", "STANDARD", "DEEP"}),
        )
        self.assertEqual(
            contract.work_states,
            frozenset(
                {
                    "NEEDS_AUDIT",
                    "AUDITED",
                    "WORK_ORDER_READY",
                    "READY_FOR_IMPLEMENTATION",
                    "IMPLEMENTING",
                    "AWAITING_REVIEW",
                    "BLOCKED",
                    "NEEDS_REAUDIT",
                    "PARKED",
                    "DONE",
                }
            ),
        )
        self.assertEqual(contract.control_wait_state, "WAIT")
        self.assertNotIn("WAIT", contract.work_states)

    def test_control_validator_rejects_invalid_present_enums(self):
        module = self._contract_module()
        contract = module.load_workflow_contract()

        with self.assertRaises(module.WorkflowContractError):
            contract.validate_repository_control_sections(
                {
                    "Work Status": "IN_PROGRESS",
                    "Audit Depth": "STANDARD",
                }
            )
        with self.assertRaises(module.WorkflowContractError):
            contract.validate_repository_control_sections(
                {
                    "Work Status": "AUDITED",
                    "Audit Depth": "TARGETED",
                }
            )

    def test_control_validator_keeps_wait_and_legacy_missing_heading_compatibility(self):
        contract = self._contract_module().load_workflow_contract()
        # Legacy Controls may omit newer headings when their equivalent entry
        # references remain unambiguous. Semantic enum validation must not turn
        # that compatibility rule into a required-heading rewrite.
        contract.validate_repository_control_sections(
            {
                "Work Status": "WAIT",
                "Repository State": "ACTIVE",
                "Priority": "P2",
                "Risk": "LOW",
                "Type": "AUDIT",
            }
        )

    def test_project_sync_and_bootstrap_do_not_own_duplicate_workflow_enum_sets(self):
        project_sync_source = (ROOT / "scripts" / "project_sync.py").read_text(encoding="utf-8")
        bootstrap_source = (ROOT / "tools" / "repository_bootstrap.py").read_text(encoding="utf-8")

        self.assertNotIn(
            '"Audit Depth": {"CONTROL", "STANDARD", "DEEP"}',
            project_sync_source,
        )
        self.assertNotIn("WORK_STATES = frozenset(", bootstrap_source)
        self.assertNotIn("REPOSITORY_STATES = frozenset(", bootstrap_source)
        self.assertNotIn('PRIORITIES = frozenset({"P0", "P1", "P2", "P3"})', bootstrap_source)
        self.assertNotIn('RISKS = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})', bootstrap_source)

    def test_canonical_spec_uses_accepted_audit_depth_vocabulary(self):
        spec = (ROOT / "docs" / "spec" / "CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("`CONTROL`", spec)
        self.assertIn("`STANDARD`", spec)
        self.assertIn("`DEEP`", spec)
        self.assertNotIn("- `QUICK`: narrow known change / low uncertainty;", spec)
        self.assertNotIn("- `FULL`: broad/unknown-impact audit", spec)


if __name__ == "__main__":
    unittest.main()
