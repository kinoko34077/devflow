from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FEATURE = ROOT / "features" / "repository-bootstrap"
MANIFEST = FEATURE / "manifest.json"
README = FEATURE / "README.md"
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
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.readme = README.read_text(encoding="utf-8")

    def test_manifest_is_an_index_only_route(self) -> None:
        self.assertEqual(self.manifest["schema"], "feature-document-route.v1")
        self.assertEqual(self.manifest["authority"], "index_only")
        self.assertEqual(self.manifest["source_repository"], "kinoko34077/devflow")
        self.assertEqual(self.manifest["source_ref"], "c83c4df50fbd0b1c6fbfce36718a1a34b38ec0d5")
        self.assertEqual(self.manifest["entry"], "features/repository-bootstrap/README.md")

    def test_routes_cover_the_pilot_without_execution_authority(self) -> None:
        self.assertEqual(set(self.manifest["routes"]), EXPECTED_ROUTES)
        self.assertEqual(self.manifest["authority"], "index_only")

    def test_every_indexed_source_path_exists_and_is_unique(self) -> None:
        for route in self.manifest["routes"].values():
            for key in ("documents", "code", "tests"):
                paths = route.get(key, [])
                self.assertEqual(len(paths), len(set(paths)), f"duplicate {key} path")
                for relative in paths:
                    path = Path(relative)
                    self.assertFalse(path.is_absolute(), relative)
                    self.assertNotIn("..", path.parts, relative)
                    self.assertTrue((ROOT / path).is_file(), relative)

    def test_readme_preserves_fail_closed_and_human_gate_boundaries(self) -> None:
        for route in sorted(EXPECTED_ROUTES):
            self.assertIn(f"## {route}", self.readme)
        lower = self.readme.lower()
        self.assertIn("proposal", lower)
        self.assertIn("fail closed", lower)
        self.assertIn("human gate", lower)
        self.assertIn("does not grant", lower)


if __name__ == "__main__":
    unittest.main()

