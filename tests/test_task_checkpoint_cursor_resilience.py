"""Bounded trust/format regressions for #576 (no live writes)."""
import unittest
from tools.task_checkpoint_cursor import (
    CursorFormatError, CursorState, inspect_cursor_comments,
    parse_cursor_comment, parse_cursor_comment_compatible, render_cursor_comment,
)

TASK = "kinoko34077/devflow#576"
STAMP = "2026-10-15T10:43:10Z"
STATE = CursorState(1, TASK, 7, "M0", "M1", "a" * 40,
    ("https://github.com/kinoko34077/devflow/issues/576",), STAMP)


def comment(body, association="OWNER", login="kinoko34077"):
    return {"body": body, "author_association": association, "user": {"login": login}}


class CompatibleCursorTests(unittest.TestCase):
    def test_canonical_round_trip(self):
        body = render_cursor_comment(STATE)
        parsed, warnings = parse_cursor_comment_compatible(body)
        self.assertEqual(parsed, STATE)
        self.assertEqual(warnings, ())
        self.assertEqual(inspect_cursor_comments([comment(body)], TASK).warnings, ())

    def test_actual_agent_variants(self):
        body = render_cursor_comment(STATE).replace(
            "updated_at: " + STAMP,
            "blocker: review pending, not an authorization\nupdated_at: 2026-10-15T19:43:10.697+09:00")
        parsed, warnings = parse_cursor_comment_compatible(body)
        self.assertEqual(parsed, STATE)
        self.assertIn("WARN_IGNORED_ANNOTATION", warnings)
        self.assertIn("WARN_NORMALIZED", warnings)
        self.assertEqual(inspect_cursor_comments([comment(body)], TASK).code, "OK_CURSOR")

    def test_fractional_utc(self):
        body = render_cursor_comment(STATE).replace(STAMP, "2026-10-15T10:43:10.697Z")
        self.assertEqual(parse_cursor_comment_compatible(body)[0].updated_at, STAMP)

    def test_whitespace_order_crlf_prose(self):
        original = render_cursor_comment(STATE)
        start = original.index("schema_version: 1")
        end = original.index("\n" + chr(96) * 3, start)
        reordered = "\n".join([
            "revision: 7", " schema_version : 1 ", "task : " + TASK,
            "head: " + "a" * 40, "first_unfinished : M1",
            "last_completed: M0", "updated_at: " + STAMP,
            "evidence:", "   - https://github.com/kinoko34077/devflow/issues/576"])
        body = (original[:start] + reordered + original[end] +
            "External note: no new authority.\n").replace("\n", "\r\n")
        parsed, warnings = parse_cursor_comment_compatible(body)
        self.assertEqual(parsed, STATE)
        self.assertIn("WARN_NORMALIZED", warnings)

    def test_strict_v1_stays_available(self):
        body = render_cursor_comment(STATE).replace(STAMP, "2026-10-15T10:43:10.697Z")
        with self.assertRaises(CursorFormatError):
            parse_cursor_comment(body)

    def test_duplicate_keys_rejected(self):
        original = render_cursor_comment(STATE)
        for extra in ("revision: 8", "blocker: earlier\nblocker: later"):
            with self.subTest(extra=extra):
                body = original.replace("updated_at: " + STAMP, extra + "\nupdated_at: " + STAMP)
                with self.assertRaises(CursorFormatError):
                    parse_cursor_comment_compatible(body)

    def test_wrong_task_and_trust_and_duplicates(self):
        body = render_cursor_comment(STATE)
        wrong = body.replace("#576", "#999")
        self.assertEqual(inspect_cursor_comments([comment(wrong)], TASK).code, "WARN_MALFORMED_MARKER")
        self.assertEqual(inspect_cursor_comments([comment(body, "CONTRIBUTOR", "unknown")], TASK).code, "NO_MARKER")
        self.assertEqual(inspect_cursor_comments([comment(body), comment(body)], TASK).code, "WARN_DUPLICATE_MARKER")

    def test_semantic_ambiguity_and_injection_rejected(self):
        base = render_cursor_comment(STATE)
        stamp = "updated_at: " + STAMP
        fence = chr(96) * 3
        candidates = [
            base.replace("first_unfinished: M1", "first_unfinished: OTHER TASK"),
            base.replace("revision: 7", "revision: 1_0"),
            base.replace("revision: 7", "revision: +7"),
            base.replace(stamp, "updated_at: 2026-13-15T10:43:10Z"),
            base.replace(stamp, "updated_at: 2026-10-15T10:43:10"),
            base.replace(stamp, "blocker: !!python/object\n" + stamp),
            base.replace(stamp, "foo:\n  nested: true\n" + stamp),
            base.replace("evidence:", "evidence: !!binary"),
            base.replace(stamp, stamp + "\n" + stamp),
            base + "\n" + fence + "yaml\nkey: value\n" + fence,
            base + "\n<!-- devflow-task-checkpoint-cursor:v1 -->",
        ]
        for body in candidates:
            with self.subTest(body=body[-140:]):
                with self.assertRaises(CursorFormatError):
                    parse_cursor_comment_compatible(body)

    def test_bounded_comment(self):
        with self.assertRaises(CursorFormatError):
            parse_cursor_comment_compatible(render_cursor_comment(STATE) + "x" * 70000)


if __name__ == "__main__":
    unittest.main()
