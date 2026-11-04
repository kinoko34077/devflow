from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "project-sync-tests.yml"


class ProjectSyncTestsWorkflowTests(unittest.TestCase):
    def test_main_push_filter_includes_feature_routes_and_required_job(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        push = re.search(
            r"(?ms)^  push:\s*\n(?P<section>.*?)(?=^[A-Za-z_][A-Za-z0-9_-]*:|\Z)",
            workflow,
        )
        self.assertIsNotNone(push, "push trigger must be declared")
        branches = re.search(
            r"(?m)^    branches:\s*\[([^\]]*)\]\s*$", push.group("section")
        )
        self.assertIsNotNone(branches, "push trigger must declare its branches")
        branch_names = [name.strip().strip("'\"") for name in branches.group(1).split(",")]
        self.assertIn("main", branch_names, "Required push gate must include main")

        paths = re.search(
            r"(?ms)^    paths:\s*\n(?P<list>(?:^      - .*\n)+)",
            push.group("section"),
        )
        self.assertIsNotNone(paths, "push trigger must have an explicit path list")
        patterns = re.findall(r"^      - ['\"]([^'\"]+)['\"]\s*$", paths.group("list"), re.MULTILINE)
        self.assertIn("features/**", patterns, "feature routes must trigger main verification")

        jobs = re.search(
            r"(?ms)^jobs:\s*\n(?P<section>.*?)(?=^[A-Za-z_][A-Za-z0-9_-]*:|\Z)",
            workflow,
        )
        self.assertIsNotNone(jobs, "Required workflow must declare jobs")
        self.assertRegex(
            jobs.group("section"),
            r"(?m)^  verify:\s*$",
            "Required verify job must remain present",
        )


if __name__ == "__main__":
    unittest.main()
