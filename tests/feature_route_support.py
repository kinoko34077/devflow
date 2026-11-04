"""Shared mechanical checks for feature-first documentation routes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_feature_route(root: Path, feature: str) -> tuple[dict[str, Any], str]:
    """Load one feature route without duplicating path conventions in tests."""
    directory = root / "features" / feature
    manifest = json.loads(
        (directory / "manifest.json").read_text(encoding="utf-8")
    )
    readme = (directory / "README.md").read_text(encoding="utf-8")
    return manifest, readme


def assert_index_only_manifest(
    testcase: Any,
    manifest: dict[str, Any],
    *,
    entry: str,
    source_ref: str | None = None,
) -> None:
    testcase.assertEqual(manifest["schema"], "feature-document-route.v1")
    testcase.assertEqual(manifest["authority"], "index_only")
    testcase.assertEqual(manifest["source_repository"], "kinoko34077/devflow")
    testcase.assertEqual(manifest["entry"], entry)
    if source_ref is not None:
        testcase.assertEqual(manifest["source_ref"], source_ref)


def assert_indexed_source_paths_exist(
    testcase: Any, root: Path, manifest: dict[str, Any]
) -> None:
    for route in manifest["routes"].values():
        for key in ("documents", "code", "tests"):
            paths = route.get(key, [])
            testcase.assertEqual(
                len(paths), len(set(paths)), f"duplicate {key} path"
            )
            for relative in paths:
                path = Path(relative)
                testcase.assertFalse(path.is_absolute(), relative)
                testcase.assertNotIn("..", path.parts, relative)
                resolved = root / path
                testcase.assertTrue(
                    resolved.is_file() or resolved.is_dir(), relative
                )


def assert_readme_routes(
    testcase: Any, readme: str, expected_routes: set[str]
) -> None:
    for route in sorted(expected_routes):
        testcase.assertIn(f"## {route}", readme)
