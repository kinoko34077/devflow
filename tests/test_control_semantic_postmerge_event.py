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
        def native_read(path):
            if path == "repos/kinoko34077/devflow/issues/16":
                return issue, NOW
            if path.startswith("repos/kinoko34077/devflow/pulls/"):
                p = case["pull_request"]
                return {
                    "number": p["number"],
                    "html_url": p["html_url"],
                    "state": "closed", "merged": p["merged"],
                    "merged_at": p["merged_at"], "body": "",
                    "base": {"repo": {"full_name": target.REPOSITORY}},
                }, NOW
            if path == "repos/kinoko34077/devflow/issues/726":
                return {
                    "number": 726, "state": "open",
                    "html_url": "https://github.com/kinoko34077/devflow/issues/726",
                }, NOW
            raise AssertionError("unexpected native GET path: " + path)

        with patch.object(
            target.pilot, "_read_json", side_effect=native_read
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
        self.assertEqual(result["reason"], "NO_PR_OR_OWNER_REFERENCE")
        self.assertEqual(read.call_count, 2)
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
        self.assertEqual(result["reason"], "NO_PR_OR_OWNER_REFERENCE")
        check.assert_not_called()

    def test_owner_link_without_pr_anchor_requires_review_not_mismatch(self):
        case = event()
        c = control(number=775, stage="MERGED")
        c["body"] = c["body"].replace(
            "## Next Action\n\n",
            "## Next Action\n\nNext action for #726 is pending.\n",
        )
        pr = {
            "number": 777,
            "html_url": f"https://github.com/{target.REPOSITORY}/pull/777",
            "state": "closed", "merged": True,
            "merged_at": case["pull_request"]["merged_at"],
            "base": {"repo": {"full_name": target.REPOSITORY}},
            "body": (
                "### Context\nThis PR explains the `Owning-Issue:` marker.\n"
                "- Owning-Issue: #726"
                "\nLegacy: "
                "https://github.com/kinoko34077/devflow/issues/726\n"
            ),
        }
        reads = []

        def lookup(path):
            reads.append(path)
            if path.endswith("/issues/16"):
                return c, NOW
            if path.endswith("/pulls/777"):
                return pr, NOW
            if path.endswith("/issues/726"):
                return {
                    "number": 726, "state": "open",
                    "html_url": "https://github.com/kinoko34077/devflow/issues/726",
                }, NOW
            raise AssertionError(path)

        with patch.object(target.pilot, "_read_json", side_effect=lookup), patch.object(
            target.pilot, "check_pr_transition_once", side_effect=AssertionError(
                "must not invoke exact PR claim checker"
            ),
        ):
            result = target.check_native_postmerge_once(case, target.REPOSITORY)
        self.assertEqual(result["status"], "RECONCILIATION_REVIEW_REQUIRED")
        self.assertEqual(result["reason"], "OWNER_ACTIVE_WITHOUT_PR_LINK")
        self.assertEqual(result["owner_issue_url"],
                         "https://github.com/kinoko34077/devflow/issues/726")
        self.assertEqual(reads, [
            "repos/kinoko34077/devflow/issues/16",
            "repos/kinoko34077/devflow/pulls/777",
            "repos/kinoko34077/devflow/issues/726",
        ])
        self.assertNotIn("body", result)

    def test_owner_outcome_ambiguity_and_absent_scope_fail_closed(self):
        e = event()
        current = control(number=775, stage="MERGED")
        current["body"] = current["body"].replace(
            "## Next Action\n\n", "## Next Action\n\n#726 is current.\n"
        )
        basic = {
            "number": 777,
            "html_url": "https://github.com/kinoko34077/devflow/pull/777",
            "state": "closed", "merged": True,
            "merged_at": e["pull_request"]["merged_at"],
            "base": {"repo": {"full_name": target.REPOSITORY}},
            "body": "Owning-Issue: https://github.com/kinoko34077/devflow/issues/726",
        }
        owner = {
            "number": 726, "state": "open",
            "html_url": "https://github.com/kinoko34077/devflow/issues/726",
        }
        variants = [
            ({"body": basic["body"] + "\n" + basic["body"]}, {}, {}, "UNKNOWN"),
            ({"body": basic["body"] + "\nOwning-Issue: https://invalid.example/issues/726"}, {}, {}, "UNKNOWN"),
            ({"body": "Owning-Issue: https://other.invalid/issues/726"}, {}, {}, "UNKNOWN"),
            ({"body": basic["body"].replace("/726", "/7260")}, {}, {}, "UNKNOWN"),
            ({"merged": False}, {}, {}, "UNKNOWN"),
            ({}, {"body": current["body"].replace("#726 is current", "#7260 is current")}, {}, "UNKNOWN"),
            ({}, {}, {"state": "closed"}, "UNKNOWN"),
            ({}, {}, {"html_url": "https://evil.invalid"}, "UNKNOWN"),
        ]
        for pr_update, control_update, owner_update, status in variants:
            with self.subTest(pr=pr_update, ctl=control_update, owner=owner_update):
                current_case = dict(current, **control_update)
                actual_pr = dict(basic, **pr_update)
                actual_owner = dict(owner, **owner_update)

                def look(path):
                    if path.endswith("/issues/16"):
                        return current_case, NOW
                    if path.endswith("/pulls/777"):
                        return actual_pr, NOW
                    if path.endswith("/issues/726"):
                        return actual_owner, NOW
                    return None

                with patch.object(target.pilot, "_read_json", side_effect=look):
                    result = target.check_native_postmerge_once(e, target.REPOSITORY)
                self.assertEqual(result["status"], status)

    def test_owner_issue_url_prefix_collision_is_unknown(self):
        e = event()
        c = control(number=775)
        c["body"] = c["body"].replace(
            "## Next Action\n\n",
            "## Next Action\n\n"
            "https://github.com/kinoko34077/devflow/issues/7260 is tracked.\n",
        )
        pr = {
            "number": 777,
            "html_url": "https://github.com/kinoko34077/devflow/pull/777",
            "state": "closed", "merged": True,
            "merged_at": e["pull_request"]["merged_at"],
            "base": {"repo": {"full_name": target.REPOSITORY}},
            "body": "Owning-Issue: https://github.com/kinoko34077/devflow/issues/726",
        }
        owner = {
            "number": 726, "state": "open",
            "html_url": "https://github.com/kinoko34077/devflow/issues/726",
        }

        def look(path):
            if path.endswith("/issues/16"):
                return c, NOW
            if path.endswith("/pulls/777"):
                return pr, NOW
            if path.endswith("/issues/726"):
                return owner, NOW
            raise AssertionError(path)

        with patch.object(target.pilot, "_read_json", side_effect=look):
            result = target.check_native_postmerge_once(e, target.REPOSITORY)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason"], "OWNER_NOT_IN_CURRENT_CONTROL")

    def test_owner_marker_accepts_crlf_while_not_loosening_identity(self):
        self.assertEqual(
            target.OWNER_LINE.findall(
                "Intro\r\n- Owning-Issue: "
                "https://github.com/kinoko34077/devflow/issues/726\r\n"
            ),
            ["https://github.com/kinoko34077/devflow/issues/726"],
        )
        self.assertEqual(
            target.OWNER_LINE.findall("Owner note\r\n- Owning-Issue: #726\r\n"),
            ["#726"],
        )

    def test_template_field_is_unique_and_blank_is_not_an_error(self):
        template = (
            Path(__file__).resolve().parents[1] / ".github" / "pull_request_template.md"
        ).read_text(encoding="utf-8")
        self.assertEqual([line for line in template.splitlines() if line.startswith("- Owning-Issue:")], ["- Owning-Issue:"])
        self.assertEqual(target.OWNER_LINE.findall(template), [""])

    def test_template_shorthand_and_legacy_owner_values(self):
        for value in (
            "#726",
            "https://github.com/kinoko34077/devflow/issues/726",
        ):
            with self.subTest(value=value):
                m = target.OWNER_VALUE.fullmatch(value)
                self.assertIsNotNone(m)
                self.assertEqual(int(m.group(1) or m.group(2)), 726)
        for bad in ("#7260suffix", "https://evil.invalid/issues/726",
                    "#0", "devflow #726", "#726; #727"):
            with self.subTest(bad=bad):
                self.assertIsNone(target.OWNER_VALUE.fullmatch(bad))

    def test_owner_source_missing_fails_closed(self):
        c = control(number=775)
        c["body"] = c["body"].replace(
            "## Next Action\n\n", "## Next Action\n\n#726 is current.\n"
        )
        with patch.object(target.pilot, "_read_json", side_effect=[
            (c, NOW), None,
        ]):
            result = target.check_native_postmerge_once(event(), target.REPOSITORY)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason"], "PR_SOURCE_READ_FAILED")

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
                ("RECONCILIATION_REVIEW_REQUIRED", 4),
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
