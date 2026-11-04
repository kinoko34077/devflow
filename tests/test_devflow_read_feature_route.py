from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FEATURE = ROOT / "features" / "devflow-read"
MANIFEST = FEATURE / "manifest.json"
README = FEATURE / "README.md"
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
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.readme = README.read_text(encoding="utf-8")

    def test_manifest_is_an_index_only_route(self) -> None:
        self.assertEqual(self.manifest["schema"], "feature-document-route.v1")
        self.assertEqual(self.manifest["authority"], "index_only")
        self.assertEqual(self.manifest["source_repository"], "kinoko34077/devflow")
        self.assertEqual(self.manifest["entry"], "features/devflow-read/README.md")

    def test_routes_cover_the_read_pilot_without_execution_authority(self) -> None:
        self.assertEqual(set(self.manifest["routes"]), EXPECTED_ROUTES)
        self.assertNotIn("claim", json.dumps(self.manifest, ensure_ascii=False).lower())
        self.assertNotIn("permission", json.dumps(self.manifest, ensure_ascii=False).lower())

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

    def test_readme_exposes_the_same_bounded_routes(self) -> None:
        for route in sorted(EXPECTED_ROUTES):
            self.assertIn(f"## {route}", self.readme)
        lower = self.readme.lower()
        self.assertIn("read-only", lower)
        self.assertIn("partial", lower)
        self.assertIn("current head", lower)
        self.assertIn("does not grant", lower)


if __name__ == "__main__":
    unittest.main()
