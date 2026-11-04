"""Guard the direction and acyclicity of local ``tools`` imports."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


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
        self.assertIn(
            "kaep_repository_validation",
            self.graph["kaep_live_union_cli"],
        )


if __name__ == "__main__":
    unittest.main()
