"""Source-scoped cross-repository event regressions for #726."""
from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import patch

from tools import control_semantic_postmerge_event as event_check

REPO = "kinoko34077/2bit-cell-automaton"
CONTROL = 6
AT = datetime(2026, 10, 22, tzinfo=timezone.utc)


def pr_event(number=21):
    return {
        "action": "closed",
        "repository": {"full_name": REPO},
        "pull_request": {
            "number": number,
            "html_url": f"https://github.com/{REPO}/pull/{number}",
            "base": {"repo": {"full_name": REPO}},
            "merged": True,
            "merged_at": "2026-10-22T00:00:00Z",
        },
    }


def control(claim):
    return {
        "number": CONTROL, "title": "[REPO] 2bit-cell-automaton",
        "html_url": "https://github.com/kinoko34077/devflow/issues/6",
        "state": "open",
        "body": "## Next Action\n" + claim + "\n## Canonical Entry Points\nAGENTS.md\n",
    }


def pr(number=21, body="- Owning-Issue: #726"):
    return {
        "number": number, "html_url": f"https://github.com/{REPO}/pull/{number}",
        "state": "closed", "merged": True,
        "merged_at": "2026-10-22T00:00:00Z",
        "base": {"repo": {"full_name": REPO}}, "body": body,
    }


def owner():
    return {
        "number": 726, "html_url": "https://github.com/kinoko34077/devflow/issues/726",
        "state": "open",
    }


class CrossRepoEventTests(TestCase):
    def run_check(self, claim, response_pr=None):
        calls = []
        values = [
            control(claim), response_pr if response_pr is not None else pr(), owner()
        ]

        def read(path):
            calls.append(path)
            return (values[len(calls) - 1], AT)

        with patch.object(event_check.pilot, "_read_json", side_effect=read):
            result = event_check.check_native_postmerge_once(pr_event(), REPO, CONTROL)
        return result, calls

    def test_verified_owner_marker_yields_candidate_not_proven_mismatch(self):
        result, calls = self.run_check(
            "- [#726](https://github.com/kinoko34077/devflow/issues/726) active"
        )
        self.assertEqual(result["status"], "RECONCILIATION_REVIEW_REQUIRED")
        self.assertEqual(result["subject"], f"{REPO}#21")
        self.assertEqual(calls, [
            "repos/kinoko34077/devflow/issues/6",
            f"repos/{REPO}/pulls/21",
            "repos/kinoko34077/devflow/issues/726",
        ])

    def test_no_owner_marker_remains_not_applicable(self):
        result, calls = self.run_check(
            "- #726 current", pr(body="No owner declaration")
        )
        self.assertEqual(result["status"], "NOT_APPLICABLE")
        self.assertEqual(result["subject"], f"{REPO}#21")
        self.assertEqual(len(calls), 2)

    def test_invalid_or_ambiguous_owner_marker_not_green(self):
        for body in (
            "- Owning-Issue: #726\n- Owning-Issue: #726",
            "- Owning-Issue: #999999999999",
            "- Owning-Issue: https://evil.invalid/issues/726",
        ):
            with self.subTest(body=body):
                result, _ = self.run_check("- #726 current", pr(body=body))
                self.assertEqual(result["status"], "UNKNOWN")

    def test_current_control_wrong_title_or_id_rejected(self):
        bad = control("#726 current")
        bad["title"] = "[REPO] other"
        with patch.object(
            event_check.pilot, "_read_json", return_value=(bad, AT)
        ) as read:
            result = event_check.check_native_postmerge_once(
                pr_event(), REPO, CONTROL
            )
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(read.call_count, 1)

    def test_wrong_event_repo_cannot_use_other_public_control(self):
        with patch.object(
            event_check.pilot, "_read_json", side_effect=AssertionError("GET called")
        ):
            event = pr_event()
            event["repository"]["full_name"] = "kinoko34077/other"
            result = event_check.check_native_postmerge_once(
                event, REPO, CONTROL
            )
        self.assertEqual(result["status"], "UNKNOWN")

    def test_wrong_control_number_rejected(self):
        with patch.object(
            event_check.pilot, "_read_json", return_value=(control("#726"), AT)
        ) as read:
            result = event_check.check_native_postmerge_once(
                pr_event(), REPO, 7
            )
        self.assertEqual(result["status"], "UNKNOWN")
        read.assert_called_once_with("repos/kinoko34077/devflow/issues/7")

    def test_explicit_pr_stage_uses_existing_comparator(self):
        doc = control(
            f"- [PR #21](https://github.com/{REPO}/pull/21) is **MERGED**"
        )
        with patch.object(
            event_check.pilot, "_read_json", return_value=(doc, AT)
        ) as read, patch.object(
            event_check.pilot, "check_pr_transition_once",
            return_value={"status": "ALIGNED", "subject": f"{REPO}#21"},
        ) as check:
            outcome = event_check.check_native_postmerge_once(
                pr_event(), REPO, CONTROL
            )
        self.assertEqual(outcome["status"], "ALIGNED")
        check.assert_called_once_with(CONTROL, REPO, 21)
        read.assert_called_once()

    def test_legacy_devflow_default_signature_remains_supported(self):
        ev = pr_event()
        ev["repository"]["full_name"] = "kinoko34077/devflow"
        ev["pull_request"]["html_url"] = "https://github.com/kinoko34077/devflow/pull/21"
        ev["pull_request"]["base"]["repo"]["full_name"] = "kinoko34077/devflow"
        with patch.object(event_check.pilot, "_read_json", return_value=None):
            self.assertEqual(
                event_check.check_native_postmerge_once(
                    ev, "kinoko34077/devflow"
                )["reason"], "CANONICAL_CONTROL_READ_FAILED"
            )
