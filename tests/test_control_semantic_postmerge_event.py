"""Offline native event/Control stage integration regression tests (#726)."""
from datetime import datetime, timezone
from io import StringIO
from contextlib import redirect_stdout
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import control_semantic_postmerge_event as target


NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)


def event(number=777, merged=True):
    return {
        "action": "closed",
        "repository": {"full_name": target.REPOSITORY},
        "pull_request": {
            "number": number,
            "html_url": f"https://github.com/{target.REPOSITORY}/pull/{number}",
            "base": {"repo": {"full_name": target.REPOSITORY}},
            "merged": merged,
            "merged_at": "2026-10-22T01:00:00Z" if merged else None,
        },
    }


def control(number=777, stage="OPEN"):
    return {
        "number": 16,
        "title": "[REPO] devflow",
        "html_url": target.CONTROL_URL,
        "state": "open",
        "body": (
            "## Active Work\n- unrelated\n\n"
            "## Next Action\n\n"
            f"- [PR #{number}](https://github.com/"
            f"kinoko34077/devflow/pull/{number}) is **{stage}** "
            "(explicit current work)\n"
            "\n## Canonical Entry Points\nrepo\n"
        ),
    }


class PostMergeEventTests(unittest.TestCase):
    def verify(self, expected, event_value=None, body=None, checked="ALIGNED"):
        case = event() if event_value is None else event_value
        issue = control() if body is None else body
        with patch.object(
            target.pilot, "_read_json", return_value=(issue, NOW)
        ) as read, patch.object(
            target.pilot, "check_pr_transition_once",
            return_value={"status": checked, "reason": "test", "subject": target.REPOSITORY + "#777"},
        ) as check:
            result = target.check_native_postmerge_once(
                case, target.REPOSITORY
            )
        self.assertEqual(result["status"], expected)
        return result, read, check

    def test_actual_merged_stage_aligned(self):
        result, read, check = self.verify("ALIGNED")
        read.assert_called_once_with("repos/kinoko34077/devflow/issues/16")
        check.assert_called_once_with(16, target.REPOSITORY, 777)
        self.assertEqual(result["subject"], target.REPOSITORY + "#777")

    def test_merge_with_stale_control_is_detected(self):
        result, _, check = self.verify(
            "POTENTIAL_MISMATCH", checked="POTENTIAL_MISMATCH"
        )
        check.assert_called_once()
        self.assertEqual(result["status"], "POTENTIAL_MISMATCH")

    def test_missing_current_pr_link_is_not_fake_alignment(self):
        body = control(number=775, stage="MERGED")
        result, read, check = self.verify("NOT_APPLICABLE", body=body)
        self.assertEqual(result["reason"], "NO_EXPLICIT_CURRENT_PR_REFERENCE")
        read.assert_called_once()
        check.assert_not_called()

    def test_loose_or_prefix_reference_is_not_falsely_aligned(self):
        uncanonical = control()
        uncanonical["body"] = uncanonical["body"].replace(
            "[PR #777](https://github.com/kinoko34077/devflow/pull/777)",
            "PR #777",
        )
        result, _, check = self.verify("UNKNOWN", body=uncanonical)
        self.assertEqual(result["reason"], "UNCANONICAL_CURRENT_PR_REFERENCE")
        check.assert_not_called()

        non_target = control(number=7770)
        result, _, check = self.verify("NOT_APPLICABLE", body=non_target)
        self.assertEqual(result["reason"], "NO_EXPLICIT_CURRENT_PR_REFERENCE")
        check.assert_not_called()

    def test_other_event_wrong_repo_or_bad_subject_denied_without_get(self):
        for corrupted in (
            {"action": "opened"},
            {"repository": {"full_name": "other/repo"}},
            {"pull_request": {"number": 777}},
            {"pull_request": {"number": True}},
            {"pull_request": {
                "number": 777, "html_url": "https://evil.invalid/pull/777",
            }},
            {"pull_request": {
                "number": 777,
                "html_url": "https://github.com/kinoko34077/devflow/pull/777",
                "base": {"repo": {"full_name": "another/repo"}},
                "merged": True, "merged_at": "2026-10-22T01:00:00Z",
            }},
            {"pull_request": {
                "number": 777,
                "html_url": "https://github.com/kinoko34077/devflow/pull/777",
                "base": {"repo": {"full_name": target.REPOSITORY}},
                "merged": True, "merged_at": None,
            }},
        ):
            with self.subTest(corrupted=corrupted):
                case = event()
                case.update(corrupted)
                result, read, check = self.verify(
                    "UNKNOWN", event_value=case
                )
                read.assert_not_called()
                check.assert_not_called()

    def test_nonmerged_close_skipped_not_aligned(self):
        result, read, check = self.verify(
            "NOT_APPLICABLE", event_value=event(merged=False)
        )
        self.assertEqual(result["reason"], "CLOSED_UNMERGED_NOT_IN_SCOPE")
        read.assert_not_called()
        check.assert_not_called()

    def test_bad_control_identity_or_heading_returns_unknown(self):
        for change in (
            {"number": 17},
            {"title": "[REPO] other"},
            {"html_url": "https://elsewhere.invalid"},
            {"state": "closed"},
            {"body": "## Next Action\nfoo\n## Next Action\nbar\n"},
        ):
            with self.subTest(change=change):
                c = control()
                c.update(change)
                result, _, check = self.verify("UNKNOWN", body=c)
                self.assertEqual(result["reason"], "CURRENT_CONTROL_NOT_PROVEN")
                check.assert_not_called()

    def test_exact_link_with_unclear_stage_is_unknown_not_skipped(self):
        result, _, check = self.verify("UNKNOWN", checked="UNKNOWN")
        self.assertEqual(result["reason"], "EXPLICIT_REFERENCE_BUT_STAGE_NOT_PROVEN")
        check.assert_called_once()

    def test_api_unavailable_returns_unknown(self):
        with patch.object(target.pilot, "_read_json", return_value=None):
            result = target.check_native_postmerge_once(
                event(), target.REPOSITORY
            )
        self.assertEqual(result["status"], "UNKNOWN")

    def test_historical_current_section_reference_not_active(self):
        c = control()
        c["body"] = c["body"].replace(
            "## Next Action\n\n", "## Next Action\n\n**HISTORICAL**\n"
        )
        result, _, check = self.verify("NOT_APPLICABLE", body=c)
        check.assert_not_called()

    def test_cli_exit_categories_and_sanitized_json(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "event.json"
            p.write_text(json.dumps(event()), encoding="utf-8")
            for state, expected_code in (
                ("ALIGNED", 0),
                ("NOT_APPLICABLE", 0),
                ("POTENTIAL_MISMATCH", 2),
                ("UNKNOWN", 3),
            ):
                with self.subTest(state=state):
                    output = StringIO()
                    with patch.object(
                        target, "check_native_postmerge_once",
                        return_value={"status": state, "reason": "fixture"},
                    ):
                        with redirect_stdout(output):
                            code = target.main([
                                "--event-path", str(p),
                                "--repository", target.REPOSITORY,
                            ])
                    self.assertEqual(code, expected_code)
                    self.assertEqual(json.loads(output.getvalue())["status"], state)

    def test_missing_event_fails_closed(self):
        with redirect_stdout(StringIO()):
            code = target.main([
                "--event-path", "/does/not/exist.json",
                "--repository", target.REPOSITORY,
            ])
        self.assertEqual(code, 3)


if __name__ == "__main__":
    unittest.main()
