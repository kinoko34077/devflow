"""GitHub PR-template closing keyword fallback, only advisory (#726)."""
from __future__ import annotations
from datetime import datetime, timezone
from io import StringIO
from contextlib import redirect_stdout
from unittest import TestCase, main
from unittest.mock import patch
import json

from tools import control_semantic_postmerge_event as target

AT = datetime(2026, 10, 22, tzinfo=timezone.utc)
OWNER = "kinoko34077/devflow"
PR_NO = 900
ISSUE_NO = 726


def event():
    return {
        "action": "closed",
        "repository": {"full_name": OWNER},
        "pull_request": {
            "number": PR_NO,
            "html_url": f"https://github.com/{OWNER}/pull/{PR_NO}",
            "merged": True,
            "merged_at": "2026-10-22T06:00:00Z",
            "base": {"repo": {"full_name": OWNER}},
        },
    }


def control(body="The current owner #726 needs follow-up."):
    return {
        "number": 16,
        "title": "[REPO] devflow",
        "html_url": "https://github.com/kinoko34077/devflow/issues/16",
        "state": "open",
        "body": f"## Active Work\n\n## Next Action\n{body}\n\n"
                "## Canonical Entry Points\n\nroot\n",
    }


def pr(body="- Closes #726\n- Owning-Issue:\n", base="main", default="main"):
    return {
        "number": PR_NO,
        "html_url": f"https://github.com/{OWNER}/pull/{PR_NO}",
        "state": "closed",
        "merged": True,
        "merged_at": "2026-10-22T06:00:00Z",
        "base": {"ref": base, "repo": {"full_name": OWNER, "default_branch": default}},
        "body": body,
    }


def issue(state="closed"):
    return {
        "number": ISSUE_NO,
        "html_url": f"https://github.com/{OWNER}/issues/{ISSUE_NO}",
        "state": state,
    }


class ClosingIssueTests(TestCase):
    def check(self, pr_data=None, control_data=None, issue_data=None):
        p = pr() if pr_data is None else pr_data
        c = control() if control_data is None else control_data
        i = issue() if issue_data is None else issue_data
        paths = []

        def get(path):
            paths.append(path)
            data = {
                "repos/kinoko34077/devflow/issues/16": c,
                f"repos/{OWNER}/pulls/{PR_NO}": p,
                f"repos/{OWNER}/issues/{ISSUE_NO}": i,
            }.get(path)
            if data is None:
                return None
            return data, AT

        with patch.object(target.pilot, "_read_json", side_effect=get):
            result = target.check_native_postmerge_once(event(), OWNER)
        return result, paths

    def test_exact_closes_with_blank_owner_and_closed_issue_is_review(self):
        result, paths = self.check()
        self.assertEqual(result["status"], "RECONCILIATION_REVIEW_REQUIRED")
        self.assertEqual(result["reason"], "CLOSING_ISSUE_WITHOUT_PR_LINK")
        self.assertEqual(result["owner_issue_url"],
                         "https://github.com/kinoko34077/devflow/issues/726")
        self.assertEqual(paths, [
            "repos/kinoko34077/devflow/issues/16",
            "repos/kinoko34077/devflow/pulls/900",
            "repos/kinoko34077/devflow/issues/726",
        ])

    def test_fixes_and_resolves_github_keyword_forms(self):
        for declaration in (
            "Fixes #726",
            "- Resolves #726",
            "CLOSES: #726",
            "- closes kinoko34077/devflow#726",
            "Closes https://github.com/kinoko34077/devflow/issues/726",
        ):
            with self.subTest(declaration=declaration):
                result, _ = self.check(pr_data=pr(declaration))
                self.assertEqual(result["status"],
                                 "RECONCILIATION_REVIEW_REQUIRED")

    def test_pr_template_blank_closes_field_does_not_create_owner(self):
        result, paths = self.check(pr_data=pr("- Closes #\n- Owning-Issue:\n"))
        self.assertEqual((result["status"], result["reason"]),
                         ("NOT_APPLICABLE", "NO_PR_OR_OWNER_REFERENCE"))
        self.assertEqual(len(paths), 2)

    def test_invalid_or_multiple_closes_lines_are_not_mismatch(self):
        for body in (
            "- Closes #bogus\n",
            "- Closes #726\n- Fixes #726\n",
            "- Closes: owner/other#726\n",
            "- Closes #7260\n",
        ):
            with self.subTest(body=body):
                result, _ = self.check(pr_data=pr(body))
                self.assertEqual(result["status"], "UNKNOWN")

    def test_wrong_base_does_not_imply_auto_closing_relation(self):
        result, paths = self.check(pr_data=pr(base="feature"))
        self.assertEqual((result["status"], result["reason"]),
                         ("UNKNOWN", "CLOSING_RELATION_BASE_NOT_PROVEN"))
        self.assertEqual(len(paths), 2)

    def test_default_branch_is_from_provider_not_assumed_main(self):
        # Shared caller may use master; a nondefault main is not a valid
        # GitHub closing-issue relation for that caller.
        accepted, _ = self.check(pr_data=pr(base="master", default="master"))
        self.assertEqual(accepted["status"], "RECONCILIATION_REVIEW_REQUIRED")
        rejected, _ = self.check(pr_data=pr(base="main", default="master"))
        self.assertEqual((rejected["status"], rejected["reason"]),
                         ("UNKNOWN", "CLOSING_RELATION_BASE_NOT_PROVEN"))
        missing, _ = self.check(pr_data=pr(default=""))
        self.assertEqual(missing["status"], "UNKNOWN")

    def test_multiple_ownership_sources_agree_or_hold(self):
        good = "- Closes #726\n- Owning-Issue: #726\n"
        bad = "- Closes #726\n- Owning-Issue: #725\n"
        self.assertEqual(self.check(pr_data=pr(good))[0]["status"],
                         "RECONCILIATION_REVIEW_REQUIRED")
        self.assertEqual(self.check(pr_data=pr(bad))[0]["reason"],
                         "CONTRADICTORY_OWNER_AND_CLOSING_MARKER")

    def test_owner_reference_must_be_in_current_control(self):
        result, paths = self.check(control_data=control("Work #7260 only"))
        self.assertEqual((result["status"], result["reason"]),
                         ("UNKNOWN", "OWNER_NOT_IN_CURRENT_CONTROL"))
        self.assertEqual(len(paths), 3)

    def test_closed_owner_without_closes_keyword_remains_unknown(self):
        result, _ = self.check(pr_data=pr("- Owning-Issue: #726\n"))
        self.assertEqual((result["status"], result["reason"]),
                         ("UNKNOWN", "OWNER_ISSUE_IDENTITY_NOT_PROVEN"))

    def test_open_owner_issue_with_closes_keyword_is_review_candidate(self):
        result, _ = self.check(issue_data=issue("open"))
        self.assertEqual(result["status"], "RECONCILIATION_REVIEW_REQUIRED")

    def test_no_new_issue_or_control_writes_and_status_remains_advisory(self):
        result, _ = self.check()
        self.assertNotIn("write", json.dumps(result).lower())
        self.assertNotIn(result["status"], ("ALIGNED", "POTENTIAL_MISMATCH"))
        # The CLI contract is an explicit review candidate, not a statement
        # that the linked Issue truly needs editing.
        with patch.object(target, "check_native_postmerge_once",
                          return_value=result):
            import tempfile
            from pathlib import Path
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "event.json"
                path.write_text(json.dumps(event()), encoding="utf-8")
                with redirect_stdout(StringIO()):
                    code = target.main([
                        "--event-path", str(path),
                        "--repository", OWNER,
                    ])
                self.assertEqual(code, 4)


if __name__ == "__main__":
    main()
