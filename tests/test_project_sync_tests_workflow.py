from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "project-sync-tests.yml"


def _github_path_pattern_matches(pattern: str, path: str) -> bool:
    pattern_parts = pattern.split("/")
    path_parts = path.split("/")

    def match(pattern_index: int, path_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        if pattern_parts[pattern_index] == "**":
            return any(
                match(pattern_index + 1, candidate)
                for candidate in range(path_index, len(path_parts) + 1)
            )
        return (
            path_index < len(path_parts)
            and fnmatchcase(path_parts[path_index], pattern_parts[pattern_index])
            and match(pattern_index + 1, path_index + 1)
        )

    return match(0, 0)


class ProjectSyncTestsWorkflowTests(unittest.TestCase):
    def test_feature_route_only_push_triggers_main_required_verification(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        push = re.search(
            r"(?ms)^  push:\s*\n(?P<section>.*?)(?=^[A-Za-z_][A-Za-z0-9_-]*:|\Z)",
            workflow,
        )
        self.assertIsNotNone(push, "main push trigger must be declared")
        paths = re.search(
            r"(?ms)^    paths:\s*\n(?P<list>(?:^      - .*\n)+)",
            push.group("section"),
        )
        self.assertIsNotNone(paths, "main push trigger must have an explicit path list")
        patterns = re.findall(r"^      - ['\"]([^'\"]+)['\"]\s*$", paths.group("list"), re.MULTILINE)

        self.assertTrue(
            any(
                _github_path_pattern_matches(pattern, "features/kaep/manifest.json")
                for pattern in patterns
            ),
            "feature-route-only changes must schedule the main Required PR gate",
        )


if __name__ == "__main__":
    unittest.main()
