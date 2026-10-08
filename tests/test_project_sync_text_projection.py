"""Regression for bounded, display-only Project text columns (#382)."""

import unittest

from scripts import project_sync


class ProjectTextDisplayTests(unittest.TestCase):
    def test_short_and_exact_budget_values_unchanged(self):
        self.assertEqual(project_sync._project_text_for_display("short text"), "short text")
        exact = "x" * project_sync.PROJECT_TEXT_MAX_UTF8_BYTES
        self.assertEqual(project_sync._project_text_for_display(exact), exact)

    def test_long_audit_evidence_bounded_with_explicit_marker(self):
        source = "audit proof " * 120
        displayed = project_sync._project_text_for_display(source)
        self.assertLessEqual(
            len(displayed.encode("utf-8")),
            project_sync.PROJECT_TEXT_MAX_UTF8_BYTES,
        )
        self.assertTrue(displayed.endswith(project_sync.PROJECT_TEXT_TRUNCATION_MARKER))
        self.assertTrue(source.startswith(displayed.split(" ... [truncated;", 1)[0]))
        self.assertEqual(project_sync._project_text_for_display(displayed), displayed)

    def test_multibyte_utf8_is_never_split(self):
        source = "監査" * 600
        projected = project_sync._project_text_for_display(source)
        self.assertLessEqual(
            len(projected.encode("utf-8")),
            project_sync.PROJECT_TEXT_MAX_UTF8_BYTES,
        )
        self.assertTrue(projected.endswith(project_sync.PROJECT_TEXT_TRUNCATION_MARKER))
        self.assertEqual(projected.encode("utf-8").decode("utf-8"), projected)

    def test_all_text_fields_project_but_canonical_issue_is_unchanged(self):
        audit_evidence = "long evidence " * 120
        next_action = "N" * 1100
        body = (
            "## Repository\n\nkinoko34077/demo\n\n"
            "## Work Status\n\nAUDITED\n\n"
            f"## Audit Evidence\n\n`{audit_evidence}`\n\n"
            f"## Next Action\n\n`{next_action}`\n"
        )
        issue = {"state": "open", "body": body}
        original = issue["body"]
        fields = project_sync.desired_project_fields(issue)
        self.assertEqual(fields["Status"], "AUDITED")
        self.assertEqual(fields["Managed Repository"], "kinoko34077/demo")
        for name in ("Audit Evidence", "Next Action"):
            self.assertTrue(fields[name].endswith(project_sync.PROJECT_TEXT_TRUNCATION_MARKER))
            self.assertLessEqual(len(fields[name].encode("utf-8")), project_sync.PROJECT_TEXT_MAX_UTF8_BYTES)
        self.assertEqual(issue["body"], original)
        # Verify and mutation planning see the same bounded projection.
        self.assertEqual(project_sync.compare_fields(fields, dict(fields))["Audit Evidence"], "MATCH")
        self.assertNotIn("Audit Evidence", project_sync.plan_field_mutations(fields, dict(fields)))


if __name__ == "__main__":
    unittest.main()
