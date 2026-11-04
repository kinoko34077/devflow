from __future__ import annotations

import json
from pathlib import Path
import unittest

from tests.feature_route_support import (
    assert_indexed_source_paths_exist,
    assert_index_only_manifest,
    assert_readme_routes,
    load_feature_route,
)


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ROUTES = {"inbox", "discovery", "send", "audit", "history"}
SEMANTIC_FIELDS = {
    "actor",
    "trigger",
    "action",
    "exception",
    "exit_status",
    "authority_boundary",
    "source_owner",
}


class KaepFeatureRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest, cls.readme = load_feature_route(ROOT, "kaep")

    def test_manifest_is_an_index_only_route(self) -> None:
        assert_index_only_manifest(
            self, self.manifest, entry="features/kaep/README.md"
        )

    def test_routes_cover_the_pilot_without_adding_execution_authority(self) -> None:
        self.assertEqual(set(self.manifest["routes"]), EXPECTED_ROUTES)
        self.assertNotIn("claim", json.dumps(self.manifest, ensure_ascii=False).lower())
        self.assertNotIn("permission", json.dumps(self.manifest, ensure_ascii=False).lower())

    def test_every_indexed_source_path_exists_and_is_unique(self) -> None:
        assert_indexed_source_paths_exist(self, ROOT, self.manifest)

    def test_routes_expose_a_non_authoritative_semantic_checklist(self) -> None:
        for route_name, route in self.manifest["routes"].items():
            with self.subTest(route=route_name):
                self.assertEqual(set(route["semantic_fields"]), SEMANTIC_FIELDS)
                owners = route["source_owners"]
                self.assertTrue(owners)
                for owner in owners:
                    self.assertRegex(owner, r"^kinoko34077/devflow#\d+$")
                self.assertNotIn("permission", json.dumps(route).lower())

                section = self.readme.split(f"## {route_name}", 1)[1]
                section = section.split("\n## ", 1)[0]
                lower = " ".join(section.lower().split())
                for field in SEMANTIC_FIELDS - {"exit_status"}:
                    self.assertIn(field.replace("_", " "), lower)
                self.assertIn("exit status", lower)
                for owner in owners:
                    self.assertIn(owner, section)

    def test_discovery_route_exposes_same_run_agent_projection(self) -> None:
        discovery = self.manifest["routes"]["discovery"]
        self.assertIn("tools/kaep_agent_api_projection.py", discovery["code"])
        self.assertIn("tests/test_kaep_agent_api_projection.py", discovery["tests"])

    def test_readme_routes_to_the_same_pilot_boundaries(self) -> None:
        assert_readme_routes(self, self.readme, EXPECTED_ROUTES)
        lower = self.readme.lower()
        self.assertIn("partial_unknown", lower)
        self.assertIn("claim", lower)
        self.assertIn("current head", lower)
        self.assertIn("existing source files", lower)


if __name__ == "__main__":
    unittest.main()
