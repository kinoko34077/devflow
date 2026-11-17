from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from tools.kaep_mailbox_codec import RECIPIENT_ORDER


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "tests" / "mcp_stdio_test_server.py"
BASELINE = ROOT / "tests" / "fixtures" / "mcp_tools_list_baseline.json"
ADDITIONAL_SCHEMA_KEYS = {"description", "minimum", "maximum", "minLength", "enum"}
ISSUE_BODY = "## Purpose\n\nExercise the MCP contract.\n"


def _strip_additive_metadata(value):
    if isinstance(value, dict):
        return {
            key: _strip_additive_metadata(item)
            for key, item in value.items()
            if key not in ADDITIONAL_SCHEMA_KEYS
        }
    if isinstance(value, list):
        return [_strip_additive_metadata(item) for item in value]
    return value


def _contains_key_value(value, key, expected):
    if isinstance(value, dict):
        if value.get(key) == expected:
            return True
        return any(_contains_key_value(item, key, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key_value(item, key, expected) for item in value)
    return False


def _contains_description(value):
    if isinstance(value, dict):
        description = value.get("description")
        if isinstance(description, str) and description.strip():
            return True
        return any(_contains_description(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_description(item) for item in value)
    return False


def _tool_map(tools):
    return {
        tool.name: tool.model_dump(mode="json", by_alias=True, exclude_none=True)
        for tool in tools
    }


async def _stdio_exchange(calls=()):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER)],
        cwd=str(ROOT),
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await session.initialize()
            listed = await session.list_tools()
            results = []
            for name, arguments in calls:
                results.append(await session.call_tool(name, arguments))
            return initialized, listed, results


def stdio_exchange(calls=()):
    return asyncio.run(_stdio_exchange(calls))


class DevflowMCPToolContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

    def test_stdio_tools_list_preserves_existing_contract_and_adds_metadata(self):
        initialized, listed, _ = stdio_exchange()
        current_initialize = initialized.model_dump(mode="json", by_alias=True, exclude_none=True)
        self.assertEqual(current_initialize, self.baseline["initialize"])

        current = _tool_map(listed.tools)
        baseline = {tool["name"]: tool for tool in self.baseline["tools"]}
        self.assertEqual(list(current), list(baseline))
        for name, old in baseline.items():
            with self.subTest(tool=name):
                new = current[name]
                self.assertNotEqual(new.get("description"), old.get("description"))
                self.assertGreater(len(new.get("description", "")), 60)
                self.assertEqual(
                    _strip_additive_metadata(new["inputSchema"]),
                    _strip_additive_metadata(old["inputSchema"]),
                )
                self.assertEqual(new.get("outputSchema"), old.get("outputSchema"))
                for argument, schema in new["inputSchema"].get("properties", {}).items():
                    self.assertTrue(_contains_description(schema), argument)

        for name in ("get_agent_inbox", "get_agent_workspace"):
            properties = current[name]["inputSchema"]["properties"]
            self.assertEqual(properties["limit"]["minimum"], 1)
            self.assertEqual(properties["limit"]["maximum"], 20)
            self.assertEqual(properties["offset"]["minimum"], 0)
            self.assertEqual(properties["recipient"]["enum"], list(RECIPIENT_ORDER))
            self.assertTrue(_contains_key_value(properties["work_status"], "minLength", 1))

        for name in (
            "get_issue",
            "get_scoped_task_read",
            "get_issue_goal_context",
            "assess_issue_plan",
            "assess_outcome_observation",
        ):
            self.assertEqual(
                current[name]["inputSchema"]["properties"]["issue_number"]["minimum"], 1
            )

        plan_description = (
            current["assess_issue_plan"]["inputSchema"]["properties"]["plan"]["description"]
        )
        evidence_description = (
            current["assess_outcome_observation"]["inputSchema"]["properties"]["evidence"]["description"]
        )
        inbox_limit_description = current["get_agent_inbox"]["inputSchema"]["properties"]["limit"]["description"]
        inbox_offset_description = current["get_agent_inbox"]["inputSchema"]["properties"]["offset"]["description"]
        self.assertIn("normalized repository#issue_number", plan_description)
        self.assertIn("case-insensitive", plan_description)
        self.assertIn("exactly match", evidence_description)
        self.assertIn("case-sensitively", evidence_description)
        self.assertIn("https://github.com/kinoko34077/<repo>/issues/", evidence_description)
        self.assertIn("Strict JSON integer", inbox_limit_description)
        self.assertIn("numeric strings and floats are rejected", inbox_limit_description)
        self.assertIn("Strict JSON integer", inbox_offset_description)
        self.assertIn("numeric strings and floats are rejected", inbox_offset_description)

    def test_stdio_rejects_invalid_scalars_before_service_calls(self):
        invalid_calls = [
            ("get_agent_inbox", {"repository": "devflow", "limit": 0}),
            ("get_agent_inbox", {"repository": "devflow", "limit": 21}),
            ("get_agent_workspace", {"repository": "devflow", "limit": 50}),
            ("get_agent_inbox", {"repository": "devflow", "limit": True}),
            ("get_agent_inbox", {"repository": "devflow", "limit": "14"}),
            ("get_agent_inbox", {"repository": "devflow", "offset": 14.0}),
            ("get_agent_inbox", {"repository": "devflow", "offset": -1}),
            ("get_agent_inbox", {
                "repository": "devflow", "recipient": "SECRET_SENTINEL_DO_NOT_ECHO",
            }),
            ("get_agent_inbox", {"repository": "devflow", "work_status": ""}),
            ("get_issue", {"repository": "devflow", "issue_number": 0}),
            ("get_issue", {"repository": "devflow", "issue_number": True}),
            ("get_issue", {"repository": "devflow", "issue_number": "14"}),
            ("get_issue", {"repository": "devflow", "issue_number": 14.0}),
        ]
        calls = [*invalid_calls, ("get_sync_health", {})]
        _, _, results = stdio_exchange(calls)
        for (name, _), result in zip(invalid_calls, results[:-1]):
            with self.subTest(tool=name, error=result.is_error):
                self.assertTrue(result.is_error)
        recipient_error = "\n".join(block.text for block in results[7].content)
        self.assertIn("recipient", recipient_error)
        self.assertIn("tools/list", recipient_error)
        self.assertNotIn("SECRET_SENTINEL_DO_NOT_ECHO", recipient_error)
        self.assertFalse(results[-1].is_error)
        self.assertEqual(
            results[-1].structured_content["calls"],
            [{"tool": "get_sync_health", "args": [], "kwargs": {}}],
        )
        self.assertEqual(results[-1].structured_content["source_reads"], [])

    def test_stdio_output_conversion_failure_is_not_mislabeled_as_bad_input(self):
        _, _, results = stdio_exchange([
            ("get_repository_control", {"repository": "OUTPUT_FAILURE_SENTINEL"}),
        ])
        self.assertTrue(results[0].is_error)
        error_text = "\n".join(block.text for block in results[0].content)
        self.assertIn("get_repository_control", error_text)
        self.assertNotIn("invalid arguments", error_text)
        self.assertNotIn("OUTPUT_FAILURE_SENTINEL", error_text)

    def test_stdio_preserves_defaults_boundaries_and_unknown_status_filters(self):
        calls = [
            ("get_agent_inbox", {"repository": "devflow"}),
            ("get_agent_workspace", {"repository": "devflow"}),
            ("get_agent_inbox", {
                "repository": "devflow", "recipient": "coordinator",
                "limit": 1, "offset": 20, "work_status": "FUTURE_STATUS",
            }),
            ("get_agent_workspace", {
                "repository": "devflow", "recipient": "chatgpt",
                "limit": 20, "offset": 0, "work_status": "BLOCKED",
            }),
            ("get_issue", {"repository": "devflow", "issue_number": 1}),
        ]
        _, _, results = stdio_exchange(calls)
        for result in results:
            self.assertFalse(result.is_error)
        self.assertEqual(
            results[0].structured_content["calls"][-1],
            {
                "tool": "get_agent_inbox",
                "args": ["devflow", "claude-code"],
                "kwargs": {"limit": 20, "offset": 0, "work_status": None},
            },
        )
        self.assertEqual(
            results[1].structured_content["calls"][-1],
            {
                "tool": "get_agent_workspace",
                "args": ["devflow", "codex"],
                "kwargs": {
                    "limit": 20,
                    "offset": 0,
                    "work_status": None,
                    "include_recent_kaep": False,
                    "include_published_supply": False,
                },
            },
        )
        self.assertEqual(results[2].structured_content["calls"][-1]["args"], [
            "devflow", "coordinator"
        ])
        self.assertEqual(
            results[2].structured_content["calls"][-1]["kwargs"],
            {"limit": 1, "offset": 20, "work_status": "FUTURE_STATUS"},
        )
        self.assertEqual(
            results[3].structured_content["calls"][-1]["kwargs"],
            {
                "limit": 20,
                "offset": 0,
                "work_status": "BLOCKED",
                "include_recent_kaep": False,
                "include_published_supply": False,
            },
        )
        self.assertEqual(
            sorted(results[4].structured_content.keys()),
            sorted(self.baseline["call"]["structured_keys"]),
        )
        self.assertEqual(results[4].is_error, self.baseline["call"]["isError"])

    def test_stdio_workspace_optins_and_recipient_validation(self):
        calls = [
            ("get_agent_workspace", {
                "repository": "devflow", "recipient": "codex",
                "include_recent_kaep": True, "include_published_supply": True,
            }),
            ("get_agent_workspace", {
                "repository": "devflow", "recipient": "WORKSPACE_RECIPIENT_SENTINEL",
            }),
            ("get_sync_health", {}),
        ]
        _, _, results = stdio_exchange(calls)
        self.assertFalse(results[0].is_error)
        self.assertTrue(results[1].is_error)
        invalid_text = "\n".join(block.text for block in results[1].content)
        self.assertNotIn("WORKSPACE_RECIPIENT_SENTINEL", invalid_text)
        self.assertIn("recipient", invalid_text)
        self.assertFalse(results[2].is_error)
        seen_calls = results[2].structured_content["calls"]
        self.assertEqual(
            [item["tool"] for item in seen_calls],
            ["get_agent_workspace", "get_sync_health"],
        )
        self.assertEqual(
            seen_calls[0]["kwargs"],
            {
                "limit": 20,
                "offset": 0,
                "work_status": None,
                "include_recent_kaep": True,
                "include_published_supply": True,
            },
        )

    def test_stdio_assessment_packets_keep_safe_advisory_paths(self):
        current_sha = hashlib.sha256(ISSUE_BODY.encode("utf-8")).hexdigest()
        valid_evidence = {
            "task_ref": "kinoko34077/devflow#14",
            "issue_body_sha256": current_sha,
            "required_surface": "PUBLIC_BROWSER",
            "required_target": "git:abc123",
            "observed_surface": "PUBLIC_BROWSER",
            "observed_target": "git:abc123",
            "observed_result": "SUCCESS",
            "evidence_refs": [
                "https://github.com/kinoko34077/devflow/issues/14#issuecomment-1"
            ],
        }
        stale_evidence = {**valid_evidence, "issue_body_sha256": "0" * 64}
        mismatched_evidence = {**valid_evidence, "task_ref": "kinoko34077/other#14"}
        case_variant_evidence = {**valid_evidence, "task_ref": "KINOKO34077/DEVFLOW#14"}
        calls = [
            ("assess_issue_plan", {
                "repository": "devflow", "issue_number": 14, "plan": {},
            }),
            (
                "assess_issue_plan",
                {
                    "repository": "devflow",
                    "issue_number": 14,
                    "plan": {
                        "schema_version": 1,
                        "task_ref": "kinoko34077/devflow#14",
                        "steps": [{
                            "id": "inspect",
                            "intent": "Inspect the page",
                            "declared_effects": [],
                        }],
                    },
                },
            ),
            (
                "assess_issue_plan",
                {
                    "repository": "devflow",
                    "issue_number": 14,
                    "plan": {
                        "schema_version": 1,
                        "task_ref": "KINOKO34077/DEVFLOW#14",
                        "steps": [{
                            "id": "inspect",
                            "intent": "Inspect the page",
                            "declared_effects": [],
                        }],
                    },
                },
            ),
            (
                "assess_issue_plan",
                {
                    "repository": "devflow",
                    "issue_number": 14,
                    "plan": {
                        "schema_version": 1,
                        "task_ref": "kinoko34077/other#14",
                        "steps": [{
                            "id": "inspect",
                            "intent": "Inspect the page",
                            "declared_effects": [],
                        }],
                    },
                },
            ),
            ("assess_outcome_observation", {
                "repository": "devflow", "issue_number": 14, "evidence": None,
            }),
            ("assess_outcome_observation", {
                "repository": "devflow", "issue_number": 14, "evidence": stale_evidence,
            }),
            ("assess_outcome_observation", {
                "repository": "devflow", "issue_number": 14, "evidence": mismatched_evidence,
            }),
            ("assess_outcome_observation", {
                "repository": "devflow", "issue_number": 14, "evidence": case_variant_evidence,
            }),
            ("assess_outcome_observation", {
                "repository": "devflow", "issue_number": 14, "evidence": valid_evidence,
            }),
        ]
        _, _, results = stdio_exchange(calls)
        for result in results:
            self.assertFalse(result.is_error)
        self.assertEqual(results[0].structured_content["status"], "NEEDS_EVIDENCE")
        self.assertFalse(results[1].structured_content["can_authorize_execution"])
        self.assertEqual(results[2].structured_content["reason_code"], "SOURCE_BOUND_DECLARED_EFFECTS_ONLY")
        self.assertFalse(results[2].structured_content["can_authorize_execution"])
        self.assertEqual(results[3].structured_content["status"], "NEEDS_EVIDENCE")
        self.assertEqual(results[3].structured_content["reason_code"], "TASK_REFERENCE_MISMATCH")
        self.assertFalse(results[3].structured_content["can_authorize_execution"])
        self.assertEqual(results[4].structured_content["status"], "NEEDS_EVIDENCE")
        self.assertEqual(results[5].structured_content["status"], "NEEDS_EVIDENCE")
        self.assertFalse(results[5].structured_content["can_authorize_execution"])
        self.assertEqual(results[6].structured_content["status"], "NEEDS_EVIDENCE")
        self.assertEqual(results[6].structured_content["reason"], "TASK_REF_MISMATCH")
        self.assertFalse(results[6].structured_content["can_authorize_execution"])
        self.assertEqual(results[7].structured_content["status"], "NEEDS_EVIDENCE")
        self.assertEqual(results[7].structured_content["reason"], "TASK_REF_MISMATCH")
        self.assertFalse(results[7].structured_content["can_authorize_execution"])
        self.assertEqual(results[8].structured_content["status"], "DECLARED_ALIGNED")
        self.assertEqual(results[8].structured_content["source_verification"], "NOT_PERFORMED")
        self.assertFalse(results[8].structured_content["acceptance_satisfied"])
        self.assertFalse(results[8].structured_content["can_authorize_execution"])

    def test_cli_pagination_help_describes_the_shared_contract(self):
        commands = [
            [sys.executable, "-m", "tools.devflow_read_cli", "--help"],
            [sys.executable, "-m", "tools.kaep_agent_inbox_cli", "--help"],
        ]
        environment = dict(os.environ)
        environment["PYTHONIOENCODING"] = "utf-8"
        for command in commands:
            with self.subTest(command=command[2]):
                result = subprocess.run(
                    command, cwd=ROOT, capture_output=True, text=True,
                    encoding="utf-8", check=False,
                    env=environment,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("1..20", result.stdout)
                self.assertIn(">= 0", result.stdout)
                self.assertIn("next_offset", result.stdout)
                self.assertIn("truncated", result.stdout)


if __name__ == "__main__":
    unittest.main()
