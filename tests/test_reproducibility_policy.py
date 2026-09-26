import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


class ReproducibilityPolicyTests(unittest.TestCase):
    def test_external_actions_are_pinned_to_full_commit_sha(self):
        mutable = []
        for workflow in sorted(WORKFLOWS.glob("*.y*ml")):
            for line_number, line in enumerate(
                workflow.read_text(encoding="utf-8").splitlines(), start=1
            ):
                match = re.match(r"\s*-?\s*uses:\s*([^\s#]+)", line)
                if not match:
                    continue
                action = match.group(1)
                if action.startswith("./"):
                    continue
                if "@" not in action:
                    mutable.append(f"{workflow.name}:{line_number}: {action}")
                    continue
                ref = action.rsplit("@", 1)[1]
                if not FULL_SHA.fullmatch(ref):
                    mutable.append(f"{workflow.name}:{line_number}: {action}")

        self.assertEqual([], mutable, "mutable external Action refs: " + ", ".join(mutable))

    def test_mcp_direct_dependency_is_exact_pinned(self):
        requirement = (ROOT / "requirements-mcp.txt").read_text(encoding="utf-8").strip()
        self.assertEqual("mcp[cli]==2.2.0", requirement)


if __name__ == "__main__":
    unittest.main()
