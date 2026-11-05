from __future__ import annotations

from pathlib import Path
import re
import unittest

from tests.feature_route_support import (
    assert_indexed_source_paths_exist,
    assert_index_only_manifest,
    assert_readme_routes,
    load_feature_route,
)


ROOT = Path(__file__).resolve().parents[1]


class FeatureRouteCatalogTests(unittest.TestCase):
    def test_root_catalog_lists_every_feature_route(self) -> None:
        catalog = (ROOT / "features" / "README.md").read_text(
            encoding="utf-8"
        )
        directories = sorted(
            path for path in (ROOT / "features").iterdir()
            if path.is_dir() and (path / "manifest.json").is_file()
        )
        for directory in directories:
            with self.subTest(feature=directory.name):
                self.assertIn(
                    f"]({directory.name}/README.md)", catalog
                )

    def test_every_feature_route_has_consistent_entry_and_sources(self) -> None:
        feature_root = ROOT / "features"
        directories = sorted(
            path for path in feature_root.iterdir()
            if path.is_dir() and (path / "manifest.json").is_file()
        )
        self.assertGreaterEqual(len(directories), 1)
        for directory in directories:
            feature = directory.name
            with self.subTest(feature=feature):
                manifest, readme = load_feature_route(ROOT, feature)
                assert_index_only_manifest(
                    self,
                    manifest,
                    entry=f"features/{feature}/README.md",
                )
                self.assertRegex(
                    manifest.get("source_ref", ""),
                    re.compile(r"^[0-9a-f]{40}$"),
                    f"{feature} must pin the inspected source snapshot",
                )
                if "source_ref" in readme:
                    self.assertIn(manifest["source_ref"], readme)
                assert_indexed_source_paths_exist(self, ROOT, manifest)
                assert_readme_routes(self, readme, set(manifest["routes"]))


if __name__ == "__main__":
    unittest.main()
