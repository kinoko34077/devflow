"""Required PR gate for an explicit, unambiguous owning Issue relation."""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from tools import control_semantic_postmerge_event as target


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/project-sync-tests.yml"
OWNER = "kinoko34077/devflow"


def event(body, base_ref="main", default_branch="main", repository=OWNER):
    return {
        "repository": {
            "full_name": repository,
            "default_branch": default_branch,
        },
        "pull_request": {
            "body": body,
            "base": {"ref": base_ref},
        },
    }


class RequiredOwnerMetadataTests(unittest.TestCase):
    def check(self, body, base_ref="main", default_branch="main", repository=OWNER):
        validator = getattr(target, "validate_pr_owner_metadata_event", None)
        self.assertTrue(
            callable(validator),
            "the post-merge owner parser must expose the shared PR metadata validator",
        )
        return validator(event(body, base_ref, default_branch, repository), OWNER)

    def test_required_pr_rejects_missing_owner_relation(self):
        result = self.check("- Closes #\n- Owning-Issue:\n")
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "OWNER_RELATION_REQUIRED"),
        )

    def test_single_owner_declaration_is_valid(self):
        result = self.check("- Closes #\n- Owning-Issue: #726\n")
        self.assertEqual(result["status"], "VALID")

    def test_closing_declaration_alone_is_valid_on_default_branch(self):
        result = self.check("- Closes #726\n- Owning-Issue:\n")
        self.assertEqual(result["status"], "VALID")

    def test_matching_owner_and_closing_declarations_are_valid(self):
        result = self.check("- Closes #726\n- Owning-Issue: #726\n")
        self.assertEqual(result["status"], "VALID")

    def test_duplicate_owner_declarations_are_rejected(self):
        result = self.check(
            "- Owning-Issue: #726\n- Owning-Issue: #726\n"
        )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "AMBIGUOUS_OWNER_MARKER"),
        )

    def test_fenced_examples_do_not_satisfy_required_owner_relation(self):
        result = self.check(
            "```markdown\n"
            "- Owning-Issue: #726\n"
            "- Closes #726\n"
            "```\n"
        )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "OWNER_RELATION_REQUIRED"),
        )

    def test_html_commented_owner_and_closing_examples_do_not_satisfy_gate(self):
        result = self.check(
            "<!--\n"
            "- Owning-Issue: #726\n"
            "- Closes #726\n"
            "-->\n"
        )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "OWNER_RELATION_REQUIRED"),
        )

    def test_backticks_in_html_attributes_do_not_expose_commented_owner(self):
        result = self.check(
            '<span title="`">x</span>\n'
            "<!--\n`\n- Owning-Issue: #726\n-->\n"
        )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "OWNER_RELATION_REQUIRED"),
        )

    def test_owner_and_closing_examples_inside_raw_html_code_do_not_satisfy_gate(self):
        result = self.check(
            "<pre>\n"
            "- Owning-Issue: #726\n"
            "- Closes #726\n"
            "</pre>\n"
        )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "OWNER_RELATION_REQUIRED"),
        )

    def test_fake_raw_html_closer_inside_comment_does_not_expose_owner(self):
        result = self.check(
            "<pre>\n"
            "<!-- fake </pre> close -->\n"
            "- Owning-Issue: #726\n"
            "</pre>\n"
        )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "OWNER_RELATION_REQUIRED"),
        )

    def test_whitespace_after_raw_html_closer_slash_is_not_a_closer(self):
        result = self.check(
            "<pre>\n"
            "</ pre>\n"
            "- Owning-Issue: #726\n"
            "</pre>\n"
        )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "OWNER_RELATION_REQUIRED"),
        )

    def test_plaintext_html_element_consumes_the_remaining_body(self):
        result = self.check(
            "<plaintext>\n"
            "</plaintext>\n"
            "- Owning-Issue: #726\n"
        )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "OWNER_RELATION_REQUIRED"),
        )

    def test_plaintext_self_closing_syntax_still_consumes_the_body(self):
        result = self.check(
            "<plaintext/>\n"
            "- Owning-Issue: #726\n"
        )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "OWNER_RELATION_REQUIRED"),
        )

    def test_textarea_comment_like_text_does_not_hide_owner_after_end_tag(self):
        result = self.check(
            "<textarea>\n"
            "<!--\n"
            "</textarea>\n"
            "- Owning-Issue: #726\n"
        )
        self.assertEqual(result["status"], "VALID")

    def test_raw_code_closer_inside_nested_quoted_attribute_is_ignored(self):
        result = self.check(
            "<pre>\n"
            '<span title="</pre>">x</span>\n'
            "- Owning-Issue: #726\n"
            "</pre>\n"
        )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "OWNER_RELATION_REQUIRED"),
        )

    def test_comment_marker_inside_nested_quoted_attribute_does_not_hide_owner(self):
        result = self.check(
            "<pre>\n"
            '<span title="<!--">x</span>\n'
            "</pre>\n"
            "- Owning-Issue: #726\n"
        )
        self.assertEqual(result["status"], "VALID")

    def test_unclosed_html_tag_suffix_is_scanned_once_and_fails_closed(self):
        body = "<a " * 128 + "\n- Owning-Issue: #726\n"
        with patch.object(
            target, "_html_tag_end", wraps=target._html_tag_end
        ) as tag_end:
            result = self.check(body)
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "OWNER_RELATION_REQUIRED"),
        )
        self.assertEqual(tag_end.call_count, 1)

    def test_html_comment_marker_in_inline_code_does_not_hide_owner(self):
        result = self.check(
            "This change removes the literal `<!--` marker.\n"
            "- Owning-Issue: #726\n"
        )
        self.assertEqual(result["status"], "VALID")

    def test_owner_and_closing_examples_inside_inline_code_do_not_satisfy_gate(self):
        result = self.check(
            "`example\n"
            "- Owning-Issue: #726\n"
            "example`\n"
            "`- Closes #726`\n"
        )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "OWNER_RELATION_REQUIRED"),
        )

    def test_postmerge_reader_does_not_reconcile_html_commented_relations(self):
        merged_at = "2026-11-07T01:00:00Z"
        pr = {
            "number": 777,
            "html_url": f"https://github.com/{OWNER}/pull/777",
            "state": "closed",
            "merged": True,
            "merged_at": merged_at,
            "base": {
                "repo": {"full_name": OWNER, "default_branch": "main"},
                "ref": "main",
            },
            "body": (
                "<!--\n- Owning-Issue: #726\n- Closes #726\n-->\n"
            ),
        }
        with patch.object(
            target.pilot, "_read_json", return_value=(pr, None)
        ) as read:
            result = target._owner_reconciliation_candidate(
                "No owner reference here", 777, merged_at, OWNER
            )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("NOT_APPLICABLE", "NO_PR_OR_OWNER_REFERENCE"),
        )
        read.assert_called_once_with(f"repos/{OWNER}/pulls/777")

    def test_postmerge_reader_preserves_owner_after_inline_comment_marker(self):
        merged_at = "2026-11-07T02:00:00Z"
        pr = {
            "number": 777,
            "html_url": f"https://github.com/{OWNER}/pull/777",
            "state": "closed",
            "merged": True,
            "merged_at": merged_at,
            "base": {
                "repo": {"full_name": OWNER, "default_branch": "main"},
                "ref": "main",
            },
            "body": (
                "This change removes the literal `<!--` marker.\n"
                "- Owning-Issue: #726\n"
            ),
        }
        owner = {
            "number": 726,
            "state": "open",
            "html_url": f"https://github.com/{OWNER}/issues/726",
        }
        with patch.object(
            target.pilot,
            "_read_json",
            side_effect=[(pr, None), (owner, None)],
        ) as read:
            result = target._owner_reconciliation_candidate(
                "Current owner #726 still needs review", 777, merged_at, OWNER
            )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("RECONCILIATION_REVIEW_REQUIRED", "OWNER_ACTIVE_WITHOUT_PR_LINK"),
        )
        read.assert_has_calls([
            call(f"repos/{OWNER}/pulls/777"),
            call(f"repos/{OWNER}/issues/726"),
        ])

    def test_postmerge_reader_ignores_owner_example_inside_inline_code(self):
        merged_at = "2026-11-07T03:00:00Z"
        pr = {
            "number": 777,
            "html_url": f"https://github.com/{OWNER}/pull/777",
            "state": "closed",
            "merged": True,
            "merged_at": merged_at,
            "base": {
                "repo": {"full_name": OWNER, "default_branch": "main"},
                "ref": "main",
            },
            "body": (
                "`example\n"
                "- Owning-Issue: #726\n"
                "example`\n"
            ),
        }
        with patch.object(
            target.pilot, "_read_json", return_value=(pr, None)
        ) as read:
            result = target._owner_reconciliation_candidate(
                "No owner relation in current state", 777, merged_at, OWNER
            )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("NOT_APPLICABLE", "NO_PR_OR_OWNER_REFERENCE"),
        )
        read.assert_called_once_with(f"repos/{OWNER}/pulls/777")

    def test_postmerge_reader_ignores_owner_example_inside_raw_html_code(self):
        merged_at = "2026-11-07T04:00:00Z"
        pr = {
            "number": 777,
            "html_url": f"https://github.com/{OWNER}/pull/777",
            "state": "closed",
            "merged": True,
            "merged_at": merged_at,
            "base": {
                "repo": {"full_name": OWNER, "default_branch": "main"},
                "ref": "main",
            },
            "body": "<pre>\n- Owning-Issue: #726\n</pre>\n",
        }
        with patch.object(
            target.pilot, "_read_json", return_value=(pr, None)
        ) as read:
            result = target._owner_reconciliation_candidate(
                "No owner relation in current state", 777, merged_at, OWNER
            )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("NOT_APPLICABLE", "NO_PR_OR_OWNER_REFERENCE"),
        )
        read.assert_called_once_with(f"repos/{OWNER}/pulls/777")

    def test_postmerge_reader_ignores_fake_raw_closer_inside_html_comment(self):
        merged_at = "2026-11-07T05:00:00Z"
        pr = {
            "number": 777,
            "html_url": f"https://github.com/{OWNER}/pull/777",
            "state": "closed",
            "merged": True,
            "merged_at": merged_at,
            "base": {
                "repo": {"full_name": OWNER, "default_branch": "main"},
                "ref": "main",
            },
            "body": (
                "<pre>\n"
                "<!-- fake </pre> close -->\n"
                "- Owning-Issue: #726\n"
                "</pre>\n"
            ),
        }
        with patch.object(
            target.pilot, "_read_json", return_value=(pr, None)
        ) as read:
            result = target._owner_reconciliation_candidate(
                "No owner relation in current state", 777, merged_at, OWNER
            )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("NOT_APPLICABLE", "NO_PR_OR_OWNER_REFERENCE"),
        )
        read.assert_called_once_with(f"repos/{OWNER}/pulls/777")

    def test_postmerge_reader_treats_plaintext_as_consuming_the_body(self):
        merged_at = "2026-11-07T06:00:00Z"
        pr = {
            "number": 777,
            "html_url": f"https://github.com/{OWNER}/pull/777",
            "state": "closed",
            "merged": True,
            "merged_at": merged_at,
            "base": {
                "repo": {"full_name": OWNER, "default_branch": "main"},
                "ref": "main",
            },
            "body": (
                "<plaintext>\n"
                "</plaintext>\n"
                "- Owning-Issue: #726\n"
            ),
        }
        with patch.object(
            target.pilot, "_read_json", return_value=(pr, None)
        ) as read:
            result = target._owner_reconciliation_candidate(
                "No owner relation in current state", 777, merged_at, OWNER
            )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("NOT_APPLICABLE", "NO_PR_OR_OWNER_REFERENCE"),
        )
        read.assert_called_once_with(f"repos/{OWNER}/pulls/777")

    def test_contradictory_owner_and_closing_issue_are_rejected(self):
        result = self.check("- Closes #725\n- Owning-Issue: #726\n")
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "CONTRADICTORY_OWNER_AND_CLOSING_MARKER"),
        )

    def test_malformed_owner_reference_is_rejected_even_with_valid_closing(self):
        result = self.check(
            "- Closes #726\n- Owning-Issue: https://example.invalid/issues/726\n"
        )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "UNCANONICAL_OWNER_MARKER"),
        )

    def test_multiple_closing_declarations_are_rejected(self):
        result = self.check("- Closes #726\n- Fixes #726\n")
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "AMBIGUOUS_CLOSING_MARKER"),
        )

    def test_closing_relation_requires_the_default_branch(self):
        result = self.check(
            "- Closes #726\n", base_ref="feature", default_branch="main"
        )
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "CLOSING_RELATION_BASE_NOT_PROVEN"),
        )

    def test_event_repository_must_match_the_required_workflow_scope(self):
        result = self.check("- Owning-Issue: #726\n", repository="someone/else")
        self.assertEqual(
            (result["status"], result["reason"]),
            ("INVALID", "PULL_REQUEST_REPOSITORY_MISMATCH"),
        )

    def test_cli_accepts_a_valid_owner_relation_from_the_event_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "event.json"
            path.write_text(
                json.dumps(event("- Owning-Issue: #726\n")),
                encoding="utf-8",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                status = target.main([
                    "--validate-pr-owner-metadata",
                    "--event-path", str(path),
                    "--repository", OWNER,
                ])
        self.assertEqual(status, 0)

    def test_cli_fails_for_missing_owner_relation_from_the_event_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "event.json"
            path.write_text(
                json.dumps(event("- Closes #\n- Owning-Issue:\n")),
                encoding="utf-8",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                status = target.main([
                    "--validate-pr-owner-metadata",
                    "--event-path", str(path),
                    "--repository", OWNER,
                ])
        self.assertEqual(status, 1)


class RequiredOwnerWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_required_verify_rechecks_after_pull_request_body_edits(self):
        self.assertRegex(
            self.text,
            r"(?m)^  pull_request:\s*\n    types: \[opened, synchronize, reopened, edited\]",
        )
        self.assertIn("- name: Validate PR owner metadata", self.text)
        self.assertIn(
            "python -m tools.control_semantic_postmerge_event",
            self.text,
        )
        self.assertIn("--validate-pr-owner-metadata", self.text)
        self.assertIn("--event-path \"$GITHUB_EVENT_PATH\"", self.text)
        self.assertIn("if: github.event_name == 'pull_request'", self.text)
        self.assertNotIn("${{ github.event.pull_request.body }}", self.text)

    def test_pr_template_changes_run_the_main_push_required_gate(self):
        paths = self.text.split("    paths:\n", 1)[1].split("\n\npermissions:", 1)[0]
        self.assertIn("- '.github/pull_request_template.md'", paths)

    def test_template_states_one_required_owning_relation(self):
        template = (ROOT / ".github/pull_request_template.md").read_text(
            encoding="utf-8"
        )
        self.assertRegex(template, r"(?i)every PR must declare exactly one")
        self.assertEqual(
            len(re.findall(r"(?m)^- Owning-Issue:", template)),
            1,
        )


if __name__ == "__main__":
    unittest.main()
