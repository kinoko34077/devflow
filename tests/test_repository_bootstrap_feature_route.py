from __future__ import annotations

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
    "request",
    "validation",
    "provisioning",
    "control-trust",
    "workflow",
}


class RepositoryBootstrapFeatureRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest, cls.readme = load_feature_route(ROOT, "repository-bootstrap")

    def test_manifest_is_an_index_only_route(self) -> None:
        assert_index_only_manifest(
            self,
            self.manifest,
            source_ref="b18606558e5292b93f9efb115b3d776fce9b0a4a",
            entry="features/repository-bootstrap/README.md",
        )

    def test_routes_cover_the_pilot_without_execution_authority(self) -> None:
        self.assertEqual(set(self.manifest["routes"]), EXPECTED_ROUTES)
        self.assertEqual(self.manifest["authority"], "index_only")

    def test_every_indexed_source_path_exists_and_is_unique(self) -> None:
        assert_indexed_source_paths_exist(self, ROOT, self.manifest)

    def test_readme_preserves_fail_closed_and_human_gate_boundaries(self) -> None:
        assert_readme_routes(self, self.readme, EXPECTED_ROUTES)
        lower = self.readme.lower()
        self.assertIn("proposal", lower)
        self.assertIn("fail closed", lower)
        self.assertIn("human gate", lower)
        self.assertIn("does not grant", lower)


if __name__ == "__main__":
    unittest.main()

