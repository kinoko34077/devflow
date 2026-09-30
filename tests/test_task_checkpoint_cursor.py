import unittest

from tools.task_checkpoint_cursor import (
    SENTINEL,
    CursorFormatError,
    CursorState,
    advance_cursor,
    compare_cursor,
    initialize_cursor,
    inspect_cursor_comments,
    parse_cursor_comment,
    reconcile_cursor,
    render_cursor_comment,
    verify_post_write,
)


TASK = "kinoko34077/devflow#233"
HEAD = "a" * 40
STAMP = "2026-09-30T04:30:00Z"


def state(**overrides):
    values = {
        "schema_version": 1,
        "task": TASK,
        "revision": 7,
        "last_completed": "S1.2",
        "first_unfinished": "S1.3",
        "head": HEAD,
        "evidence": ("https://github.com/kinoko34077/devflow/actions/runs/123",),
        "updated_at": STAMP,
    }
    values.update(overrides)
    return CursorState(**values)


def comment(body, association="OWNER", login="kinoko34077"):
    return {
        "body": body,
        "author_association": association,
        "user": {"login": login},
    }


class CursorFormatTests(unittest.TestCase):
    def test_render_parse_round_trip(self):
        original = state()
        body = render_cursor_comment(original)
        self.assertIn(SENTINEL, body)
        self.assertEqual(parse_cursor_comment(body), original)

    def test_terminal_first_unfinished_round_trips(self):
        original = state(first_unfinished=None, last_completed="S1.9")
        self.assertEqual(parse_cursor_comment(render_cursor_comment(original)), original)

    def test_parse_rejects_duplicate_key(self):
        body = render_cursor_comment(state()).replace("revision: 7", "revision: 7\nrevision: 8")
        with self.assertRaises(CursorFormatError):
            parse_cursor_comment(body)

    def test_parse_rejects_unknown_key(self):
        body = render_cursor_comment(state()).replace("updated_at: 2026-09-30T04:30:00Z", "extra: nope\nupdated_at: 2026-09-30T04:30:00Z")
        with self.assertRaises(CursorFormatError):
            parse_cursor_comment(body)

    def test_parse_rejects_invalid_schema(self):
        body = render_cursor_comment(state()).replace("schema_version: 1", "schema_version: 2")
        with self.assertRaises(CursorFormatError):
            parse_cursor_comment(body)

    def test_parse_rejects_nonpositive_revision(self):
        body = render_cursor_comment(state()).replace("revision: 7", "revision: 0")
        with self.assertRaises(CursorFormatError):
            parse_cursor_comment(body)

    def test_parse_rejects_wrong_task_identity(self):
        body = render_cursor_comment(state()).replace(TASK, "not-a-task")
        with self.assertRaises(CursorFormatError):
            parse_cursor_comment(body)

    def test_parse_rejects_invalid_checkpoint_token(self):
        body = render_cursor_comment(state()).replace("first_unfinished: S1.3", "first_unfinished: bad checkpoint")
        with self.assertRaises(CursorFormatError):
            parse_cursor_comment(body)

    def test_parse_rejects_short_head(self):
        body = render_cursor_comment(state()).replace(HEAD, "deadbeef")
        with self.assertRaises(CursorFormatError):
            parse_cursor_comment(body)

    def test_parse_rejects_non_utc_timestamp(self):
        body = render_cursor_comment(state()).replace(STAMP, "2026-09-30T13:30:00+09:00")
        with self.assertRaises(CursorFormatError):
            parse_cursor_comment(body)

    def test_parse_rejects_scalar_evidence(self):
        body = render_cursor_comment(state()).replace(
            "evidence:\n  - https://github.com/kinoko34077/devflow/actions/runs/123",
            "evidence: nope",
        )
        with self.assertRaises(CursorFormatError):
            parse_cursor_comment(body)


class CursorInspectionTests(unittest.TestCase):
    def test_missing_marker(self):
        result = inspect_cursor_comments([comment("ordinary")], TASK)
        self.assertEqual(result.code, "NO_MARKER")
        self.assertIsNone(result.cursor)
        self.assertEqual(result.warnings, ())

    def test_untrusted_only_marker_is_noise(self):
        result = inspect_cursor_comments(
            [comment(render_cursor_comment(state()), association="CONTRIBUTOR", login="someone")],
            TASK,
        )
        self.assertEqual(result.code, "NO_MARKER")
        self.assertIn("WARN_UNTRUSTED_MARKER", result.warnings)

    def test_trusted_cursor_survives_untrusted_copy(self):
        body = render_cursor_comment(state())
        result = inspect_cursor_comments(
            [comment(body), comment(body, association="CONTRIBUTOR", login="someone")],
            TASK,
        )
        self.assertEqual(result.code, "OK_CURSOR")
        self.assertEqual(result.cursor, state())
        self.assertIn("WARN_UNTRUSTED_MARKER", result.warnings)

    def test_github_actions_bot_is_trusted(self):
        body = render_cursor_comment(state())
        result = inspect_cursor_comments(
            [comment(body, association="NONE", login="github-actions[bot]")],
            TASK,
        )
        self.assertEqual(result.code, "OK_CURSOR")
        self.assertEqual(result.cursor, state())

    def test_duplicate_trusted_markers_require_reconcile(self):
        body = render_cursor_comment(state())
        result = inspect_cursor_comments([comment(body), comment(body)], TASK)
        self.assertEqual(result.code, "WARN_DUPLICATE_MARKER")
        self.assertIsNone(result.cursor)

    def test_trusted_malformed_marker_is_typed_warning(self):
        result = inspect_cursor_comments([comment(f"{SENTINEL}\n```yaml\nnope: x\n```")], TASK)
        self.assertEqual(result.code, "WARN_MALFORMED_MARKER")
        self.assertIsNone(result.cursor)

    def test_cursor_for_other_task_is_malformed_for_owner(self):
        result = inspect_cursor_comments(
            [comment(render_cursor_comment(state(task="kinoko34077/devflow#999")))],
            TASK,
        )
        self.assertEqual(result.code, "WARN_MALFORMED_MARKER")


class CursorTransitionTests(unittest.TestCase):
    def test_exact_compare_matches(self):
        live = state()
        result = compare_cursor(live, 7, "S1.3")
        self.assertEqual(result.code, "OK_MATCH")
        self.assertEqual(result.live, live)

    def test_checkpoint_drift_takes_precedence(self):
        live = state(revision=8, first_unfinished="S1.4")
        result = compare_cursor(live, 7, "S1.3")
        self.assertEqual(result.code, "WARN_CHECKPOINT_DRIFT")
        self.assertEqual(result.live, live)

    def test_revision_drift_when_checkpoint_same(self):
        live = state(revision=8)
        result = compare_cursor(live, 7, "S1.3")
        self.assertEqual(result.code, "WARN_REVISION_DRIFT")
        self.assertEqual(result.live, live)

    def test_initialize_starts_revision_one(self):
        cursor = initialize_cursor(
            task=TASK,
            last_completed=None,
            first_unfinished="BOOTSTRAP",
            head=None,
            evidence=(),
            updated_at=STAMP,
        )
        self.assertEqual(cursor.revision, 1)
        self.assertIsNone(cursor.last_completed)
        self.assertEqual(cursor.first_unfinished, "BOOTSTRAP")

    def test_normal_advance_increments_and_moves_frontier(self):
        live = state()
        result = advance_cursor(
            live,
            expected_revision=7,
            expected_first_unfinished="S1.3",
            completed_checkpoint="S1.3",
            next_first_unfinished="S1.4",
            head="b" * 40,
            evidence=("https://github.com/kinoko34077/devflow/pull/999",),
            updated_at="2026-09-30T04:31:00Z",
        )
        self.assertEqual(result.code, "OK_PREPARED")
        self.assertEqual(result.cursor.revision, 8)
        self.assertEqual(result.cursor.last_completed, "S1.3")
        self.assertEqual(result.cursor.first_unfinished, "S1.4")

    def test_advance_with_drift_prepares_no_replacement(self):
        live = state(revision=8, first_unfinished="S1.4")
        result = advance_cursor(
            live,
            expected_revision=7,
            expected_first_unfinished="S1.3",
            completed_checkpoint="S1.3",
            next_first_unfinished="S1.4",
            head=None,
            evidence=(),
            updated_at="2026-09-30T04:31:00Z",
        )
        self.assertEqual(result.code, "WARN_CHECKPOINT_DRIFT")
        self.assertIsNone(result.cursor)
        self.assertEqual(result.live, live)

    def test_advance_requires_completed_checkpoint_to_equal_expected_frontier(self):
        with self.assertRaises(ValueError):
            advance_cursor(
                state(),
                expected_revision=7,
                expected_first_unfinished="S1.3",
                completed_checkpoint="S1.2",
                next_first_unfinished="S1.4",
                head=None,
                evidence=(),
                updated_at="2026-09-30T04:31:00Z",
            )

    def test_identical_post_write_is_clean(self):
        written = state(revision=8, last_completed="S1.3", first_unfinished="S1.4")
        result = verify_post_write(written, written)
        self.assertEqual(result.code, "OK_ADVANCED")
        self.assertEqual(result.cursor, written)

    def test_different_post_write_warns(self):
        written = state(revision=8, last_completed="S1.3", first_unfinished="S1.4")
        observed = state(revision=9, last_completed="S1.4", first_unfinished="S1.5")
        result = verify_post_write(written, observed)
        self.assertEqual(result.code, "WARN_POST_WRITE_DRIFT")
        self.assertEqual(result.live, observed)

    def test_reconcile_may_move_backward_and_increments_revision(self):
        live = state(revision=10, last_completed="S1.5", first_unfinished="S1.6")
        reconciled = reconcile_cursor(
            live,
            last_completed="S1.2",
            first_unfinished="S1.3",
            head="c" * 40,
            evidence=("https://github.com/kinoko34077/devflow/issues/233#reconcile",),
            updated_at="2026-09-30T04:32:00Z",
        )
        self.assertEqual(reconciled.revision, 11)
        self.assertEqual(reconciled.last_completed, "S1.2")
        self.assertEqual(reconciled.first_unfinished, "S1.3")


if __name__ == "__main__":
    unittest.main()
