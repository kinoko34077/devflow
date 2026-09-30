import unittest

from tools.task_checkpoint_cursor import (
    SENTINEL,
    CursorFormatError,
    CursorState,
    advance_cursor,
    parse_cursor_comment,
    render_cursor_comment,
)


TASK = "kinoko34077/devflow#260"
STAMP = "2026-09-30T06:20:00Z"


def state(**overrides):
    values = {
        "schema_version": 1,
        "task": TASK,
        "revision": 7,
        "last_completed": "S1.2",
        "first_unfinished": "S1.3",
        "head": "a" * 40,
        "evidence": ("https://github.com/kinoko34077/devflow/issues/260",),
        "updated_at": STAMP,
    }
    values.update(overrides)
    return CursorState(**values)


class CursorEvidenceCanonicalityTests(unittest.TestCase):
    def test_state_rejects_evidence_containing_cursor_sentinel(self):
        with self.assertRaises(CursorFormatError):
            state(evidence=(f"note {SENTINEL}",))

    def test_state_rejects_evidence_starting_with_fence_token(self):
        with self.assertRaises(CursorFormatError):
            state(evidence=("```yaml",))


class CursorIntegerCanonicalityTests(unittest.TestCase):
    def test_parser_rejects_noncanonical_revision_integer_tokens(self):
        canonical = render_cursor_comment(state())
        for token in ("1_0", "+7", " 7", "7 "):
            with self.subTest(token=token):
                body = canonical.replace("revision: 7", f"revision: {token}")
                with self.assertRaises(CursorFormatError):
                    parse_cursor_comment(body)

    def test_parser_rejects_noncanonical_schema_integer_tokens(self):
        canonical = render_cursor_comment(state())
        for token in ("0_1", "+1", " 1", "1 "):
            with self.subTest(token=token):
                body = canonical.replace("schema_version: 1", f"schema_version: {token}")
                with self.assertRaises(CursorFormatError):
                    parse_cursor_comment(body)


class CursorAdvanceCanonicalityTests(unittest.TestCase):
    def test_normal_advance_rejects_noop_frontier(self):
        live = state()
        with self.assertRaises(ValueError):
            advance_cursor(
                live,
                expected_revision=7,
                expected_first_unfinished="S1.3",
                completed_checkpoint="S1.3",
                next_first_unfinished="S1.3",
                head="b" * 40,
                evidence=(),
                updated_at="2026-09-30T06:21:00Z",
            )

    def test_stale_drift_precedes_noop_frontier_rejection(self):
        live = state(revision=8, first_unfinished="S1.4")
        result = advance_cursor(
            live,
            expected_revision=7,
            expected_first_unfinished="S1.3",
            completed_checkpoint="S1.3",
            next_first_unfinished="S1.3",
            head="b" * 40,
            evidence=(),
            updated_at="2026-09-30T06:21:00Z",
        )
        self.assertEqual(result.code, "WARN_CHECKPOINT_DRIFT")
        self.assertIsNone(result.cursor)
        self.assertEqual(result.live, live)


if __name__ == "__main__":
    unittest.main()
