"""Guard the direction and acyclicity of local ``tools`` imports."""
from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def _module_names() -> dict[str, Path]:
    return {path.stem: path for path in TOOLS.glob("*.py")}


def _local_imports(tree: ast.AST, modules: set[str]) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            candidates = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "tools":
                candidates = [f"tools.{alias.name}" for alias in node.names]
            else:
                candidates = [node.module]
        else:
            continue
        for candidate in candidates:
            if not candidate.startswith("tools."):
                continue
            module = candidate.removeprefix("tools.").split(".", 1)[0]
            if module in modules:
                imports.add(module)
    return imports


def _dependency_graph() -> dict[str, set[str]]:
    modules = _module_names()
    names = set(modules)
    graph: dict[str, set[str]] = {}
    for name, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        graph[name] = _local_imports(tree, names) - {name}
    return graph


def _cycles(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    found: list[tuple[str, ...]] = []
    visited: set[str] = set()
    active: list[str] = []

    def visit(node: str) -> None:
        if node in active:
            start = active.index(node)
            found.append(tuple(active[start:] + [node]))
            return
        if node in visited:
            return
        active.append(node)
        for target in sorted(graph[node]):
            visit(target)
        active.pop()
        visited.add(node)

    for node in sorted(graph):
        visit(node)
    return found


class ToolsDependencyGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = _dependency_graph()

    def test_local_tools_import_graph_is_acyclic(self) -> None:
        self.assertEqual(_cycles(self.graph), [])

    def test_kaep_projection_owns_the_projection_edge(self) -> None:
        projection = self.graph["kaep_agent_api_projection"]
        union = self.graph["kaep_live_union_cli"]
        self.assertIn("kaep_mailbox_codec", projection)
        self.assertNotIn("kaep_live_union_cli", projection)
        self.assertIn("kaep_agent_api_projection", union)

    def test_kaep_non_presentation_validation_does_not_depend_on_renderer(self) -> None:
        self.assertNotIn("kaep_issue_list_html", self.graph["kaep_live_candidate_cli"])
        self.assertNotIn("kaep_issue_list_html", self.graph["kaep_public_index"])
        self.assertIn("kaep_link_validation", self.graph["kaep_live_candidate_cli"])
        self.assertIn("kaep_link_validation", self.graph["kaep_public_index"])

    def test_kaep_public_index_does_not_depend_on_inbox_transport(self) -> None:
        self.assertNotIn("kaep_inbox_reader", self.graph["kaep_public_index"])
        self.assertIn(
            "kaep_repository_validation",
            self.graph["kaep_public_index"],
        )

    def test_kaep_live_delta_validation_does_not_depend_on_inbox_transport(self) -> None:
        delta = self.graph["kaep_live_delta_view"]
        self.assertNotIn("kaep_inbox_reader", delta)
        self.assertIn("kaep_mailbox_codec", delta)
        self.assertIn("kaep_repository_validation", delta)

    def test_kaep_low_level_readers_do_not_depend_on_inbox_transport(self) -> None:
        expected_codec_users = {
            "kaep_agent_api_projection",
            "kaep_b5_b6_parity_cli",
            "kaep_public_incremental_cli",
            "kaep_public_locator_cli",
            "kaep_live_union_cli",
        }
        for module in expected_codec_users:
            with self.subTest(module=module):
                self.assertNotIn("kaep_inbox_reader", self.graph[module])
                self.assertIn("kaep_mailbox_codec", self.graph[module])

    def test_kaep_agent_projection_reuses_repository_validation(self) -> None:
        projection = self.graph["kaep_agent_api_projection"]
        self.assertIn("kaep_repository_validation", projection)

    def test_kaep_public_locator_reuses_repository_validation(self) -> None:
        locator = self.graph["kaep_public_locator_cli"]
        self.assertIn("kaep_repository_validation", locator)

    def test_kaep_public_locator_does_not_depend_on_live_delta(self) -> None:
        locator = self.graph["kaep_public_locator_cli"]
        self.assertNotIn("kaep_live_delta_view", locator)
        self.assertIn("kaep_link_validation", locator)

    def test_kaep_issue_url_parsers_reuse_link_validation(self) -> None:
        for module in (
            "kaep_b5_b6_parity_cli",
            "kaep_discovery_reader",
            "kaep_issue_search_view",
        ):
            with self.subTest(module=module):
                self.assertIn("kaep_link_validation", self.graph[module])
        self.assertIn(
            "kaep_repository_validation",
            self.graph["kaep_live_union_cli"],
        )

    def test_kaep_mailbox_reuses_repository_and_task_validation(self) -> None:
        from tools import kaep_mailbox_codec as codec
        from tools import kaep_repository_validation as repository

        self.assertIn("kaep_repository_validation", self.graph["kaep_mailbox_codec"])
        self.assertIs(codec.REPOSITORY, repository.REPOSITORY)
        self.assertIs(codec.TASK_REF, repository.TASK_REF)

    def test_gpt_chat_mailbox_reuses_kaep_task_validation(self) -> None:
        from tools import gpt_liveness_chat_registry as registry
        from tools import kaep_repository_validation as repository

        self.assertIn("kaep_repository_validation", self.graph["gpt_liveness_chat_registry"])
        self.assertIs(registry.MAILBOX, repository.TASK_REF)

    def test_gpt_chat_mailbox_alias_survives_regex_cache_purge(self) -> None:
        script = """
import re
from tools import kaep_repository_validation as repository

task_ref = repository.TASK_REF
re.purge()

from tools import gpt_liveness_chat_registry as registry

if registry.MAILBOX is not task_ref:
    raise AssertionError("chat mailbox must reuse the canonical TASK_REF object")
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_kaep_source_and_route_actor_checks_reuse_shared_boundary(self) -> None:
        from tools import kaep_mailbox_support as support
        from tools import kaep_route_notice as route
        from tools import kaep_source_route_audit as audit

        self.assertIs(route.matching_actor, support.matching_actor)
        self.assertIs(audit.matching_actor, support.matching_actor)

    def test_kaep_message_id_aliases_reuse_mailbox_codec(self) -> None:
        from tools import kaep_agent_api_projection as projection
        from tools import kaep_b5_b6_parity_cli as parity
        from tools import kaep_live_candidate_cli as candidate
        from tools import kaep_mailbox_codec as codec

        self.assertIs(projection._MESSAGE, codec.MESSAGE_ID)
        self.assertIs(parity.MESSAGE_ID, codec.MESSAGE_ID)
        self.assertIs(candidate.MESSAGE, codec.MESSAGE_ID)

    def test_kaep_reason_code_aliases_reuse_mailbox_codec(self) -> None:
        from tools import kaep_agent_api_projection as projection
        from tools import kaep_b5_b6_parity_cli as parity
        from tools import kaep_mailbox_codec as codec
        from tools import kaep_public_index as public_index

        self.assertIn("kaep_mailbox_codec", self.graph["kaep_public_index"])
        self.assertIs(projection._CODE, codec.REASON_CODE)
        self.assertIs(projection._ORIGIN, codec.REASON_CODE)
        self.assertIs(parity.REASONS, codec.REASON_CODE)
        self.assertIs(public_index.REASON_CODE, codec.REASON_CODE)

    def test_kaep_source_roster_uses_shared_actor_boundary(self) -> None:
        from tools import kaep_mailbox_support as support
        from tools import kaep_source_roster_shadow as roster

        self.assertIs(roster.matching_actor, support.matching_actor)

    def test_kaep_actor_login_validators_reuse_mailbox_codec(self) -> None:
        from tools import kaep_issue_search_view as search
        from tools import kaep_live_delta_view as delta
        from tools import kaep_mailbox_codec as codec

        self.assertIs(search.ACTOR_LOGIN, codec.ACTOR_LOGIN)
        self.assertIs(delta.ACTOR_LOGIN, codec.ACTOR_LOGIN)

    def test_gpt_liveness_actor_validators_reuse_mailbox_codec(self) -> None:
        from tools import gpt_liveness_evidence as evidence
        from tools import gpt_liveness_pilot as pilot
        from tools import kaep_mailbox_codec as codec

        self.assertIs(evidence.ACTOR_LOGIN, codec.ACTOR_LOGIN)
        self.assertIs(pilot.ACTOR_LOGIN, codec.ACTOR_LOGIN)

    def test_gpt_liveness_opaque_id_validators_reuse_id_boundary(self) -> None:
        from tools import gpt_liveness_evidence as evidence
        from tools import gpt_liveness_ids as ids
        from tools import gpt_liveness_pilot as pilot

        self.assertIs(evidence.ID, ids.OPAQUE_ID)
        self.assertIs(pilot.ID, ids.OPAQUE_ID)


    def test_gpt_liveness_nonce_validators_reuse_pilot_boundary(self) -> None:
        from tools import gpt_liveness_mailbox as mailbox
        from tools import gpt_liveness_pilot as pilot

        self.assertIs(mailbox.NONCE, pilot.NONCE)


if __name__ == "__main__":
    unittest.main()
