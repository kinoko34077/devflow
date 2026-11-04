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
EXPECTED_ROUTES = {
    "bootstrap",
    "work_view",
    "inbox",
    "workspace",
    "issue_goal_context",
    "assessment",
    "cloud_fallback",
}


class DevflowReadFeatureRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest, cls.readme = load_feature_route(ROOT, "devflow-read")

    def test_manifest_is_an_index_only_route(self) -> None:
        assert_index_only_manifest(
            self, self.manifest, entry="features/devflow-read/README.md"
        )

    def test_routes_cover_the_read_pilot_without_execution_authority(self) -> None:
        self.assertEqual(set(self.manifest["routes"]), EXPECTED_ROUTES)
        self.assertNotIn("claim", json.dumps(self.manifest, ensure_ascii=False).lower())
        self.assertNotIn("permission", json.dumps(self.manifest, ensure_ascii=False).lower())

    def test_every_indexed_source_path_exists_and_is_unique(self) -> None:
        assert_indexed_source_paths_exist(self, ROOT, self.manifest)

    def test_readme_exposes_the_same_bounded_routes(self) -> None:
        assert_readme_routes(self, self.readme, EXPECTED_ROUTES)
        lower = self.readme.lower()
        self.assertIn("read-only", lower)
        self.assertIn("partial", lower)
        self.assertIn("current head", lower)
        self.assertIn("does not grant", lower)


if __name__ == "__main__":
    unittest.main()
