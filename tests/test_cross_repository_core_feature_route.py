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
    "bootstrap-control",
    "issue-goal",
    "handoff",
    "semantic-control",
}


class CrossRepositoryCoreFeatureRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest, cls.readme = load_feature_route(
            ROOT, "cross-repository-core"
        )

    def test_manifest_is_index_only(self) -> None:
        assert_index_only_manifest(
            self,
            self.manifest,
            entry="features/cross-repository-core/README.md",
        )

    def test_routes_are_bounded_and_non_authoritative(self) -> None:
        self.assertEqual(set(self.manifest["routes"]), EXPECTED_ROUTES)
        serialized = json.dumps(self.manifest, ensure_ascii=False).lower()
        self.assertNotIn("claim", serialized)
        self.assertNotIn("permission", serialized)

    def test_every_indexed_path_exists(self) -> None:
        assert_indexed_source_paths_exist(self, ROOT, self.manifest)

    def test_readme_exposes_routes_and_boundaries(self) -> None:
        assert_readme_routes(self, self.readme, EXPECTED_ROUTES)
        lowered = self.readme.lower()
        self.assertIn("index-only", lowered)
        self.assertIn("live", lowered)
        self.assertIn("fail closed", lowered)
        self.assertIn("does not", lowered)
