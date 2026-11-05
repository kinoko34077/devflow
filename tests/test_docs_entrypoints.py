from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DocumentationEntrypointTests(unittest.TestCase):
    def test_docs_entrypoint_routes_to_feature_catalog_and_categories(self) -> None:
        text = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        self.assertIn("../features/README.md", text)
        for category in (
            "spec",
            "operations",
            "decisions",
            "project",
            "superpowers",
            "mobile-actions",
        ):
            with self.subTest(category=category):
                self.assertIn(f"`{category}/`", text)

    def test_root_readme_exposes_both_navigation_layers(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("features/README.md", text)
        self.assertIn("docs/README.md", text)

    def test_entrypoint_declares_navigation_only_boundary(self) -> None:
        text = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        self.assertIn("does not create a new specification", text)
        self.assertIn("permission", text)
        self.assertIn("publication authority", text)

    def test_spec_index_does_not_claim_directory_wide_currentness(self) -> None:
        text = (ROOT / "docs" / "spec" / "README.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("提案仕様", text)
        self.assertIn("網羅的な分類ではない", text)
        self.assertIn("現行契約へ昇格させない", text)


if __name__ == "__main__":
    unittest.main()
