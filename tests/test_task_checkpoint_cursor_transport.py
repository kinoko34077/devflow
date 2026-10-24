"""Fake authenticated transport tests for cursor writer v1 (#576)."""
import unittest
from tools.task_checkpoint_cursor import CursorState, render_cursor_comment
from tools.task_checkpoint_cursor_transport import apply_cursor_write

TASK = "kinoko34077/devflow#576"
STAMP = "2026-10-15T13:40:00Z"


def state(rev=1, previous=None, current="M1"):
    return CursorState(1, TASK, rev, previous, current, "a" * 40,
                       ("https://github.com/kinoko34077/devflow/issues/576",), STAMP)


class MemoryTransport:
    def __init__(self, comments=()):
        self.comments = list(comments)
        self.calls = []
    def list_comments(self, task):
        assert task == TASK
        return [dict(c) for c in self.comments]
    def create_comment(self, task, body):
        self.calls.append("create")
        self.comments.append({"id": 19, "body": body, "author_association": "OWNER",
                              "user": {"id": 79015263, "login": "kinoko34077"}})
    def update_comment(self, task, comment_id, body):
        self.calls.append(("update", comment_id))
        for c in self.comments:
            if c.get("id") == comment_id:
                c["body"] = body
                return
        raise ValueError("no such cursor")


def saved(cursor):
    return {"id": 19, "body": render_cursor_comment(cursor),
            "author_association": "OWNER",
            "user": {"id": 79015263, "login": "kinoko34077"}}


class TransportTests(unittest.TestCase):
    def test_initialization_and_no_duplicate(self):
        t = MemoryTransport()
        self.assertEqual(apply_cursor_write(t, task=TASK, proposed=state(),
                         expected_revision=None, expected_first_unfinished=None).code, "OK_INITIALIZED")
        self.assertEqual(t.calls, ["create"])
        r = apply_cursor_write(t, task=TASK, proposed=state(),
                               expected_revision=None, expected_first_unfinished=None)
        self.assertEqual(r.code, "WARN_REVISION_DRIFT")
        self.assertEqual(t.calls, ["create"])

    def test_advance_same_comment_and_verified(self):
        t = MemoryTransport([saved(state())])
        proposal = state(2, "M1", "M2")
        r = apply_cursor_write(t, task=TASK, proposed=proposal,
                               expected_revision=1, expected_first_unfinished="M1")
        self.assertEqual(r.code, "OK_ADVANCED")
        self.assertEqual(t.calls, [("update", 19)])

    def test_stale_worker_does_not_write(self):
        t = MemoryTransport([saved(state(2, "M1", "M2"))])
        r = apply_cursor_write(t, task=TASK, proposed=state(2, "M1", "M2"),
                               expected_revision=1, expected_first_unfinished="M1")
        self.assertEqual(r.code, "WARN_CHECKPOINT_DRIFT")
        self.assertEqual(t.calls, [])

    def test_competing_duplicate_refuses_mutation(self):
        t = MemoryTransport([saved(state()), dict(saved(state()), id=20)])
        r = apply_cursor_write(t, task=TASK, proposed=state(2, "M1", "M2"),
                               expected_revision=1, expected_first_unfinished="M1")
        self.assertEqual(r.code, "WARN_DUPLICATE_MARKER")
        self.assertEqual(t.calls, [])

    def test_reconcile_needs_explicit_reason(self):
        t = MemoryTransport([saved(state())])
        with self.assertRaises(ValueError):
            apply_cursor_write(t, task=TASK, proposed=state(2, "other", "M2"),
                               expected_revision=1, expected_first_unfinished="M1")
        r = apply_cursor_write(t, task=TASK, proposed=state(2, "other", "M2"),
                               expected_revision=1, expected_first_unfinished="M1",
                               reconcile_reason="accepted new durable evidence on #576")
        self.assertEqual(r.code, "OK_ADVANCED")

    def test_untrusted_marker_never_triggers_automatic_create(self):
        alien = saved(state())
        alien["author_association"] = "CONTRIBUTOR"
        alien["user"] = {"login": "untrusted"}
        t = MemoryTransport([alien])
        outcome = apply_cursor_write(
            t, task=TASK, proposed=state(),
            expected_revision=None, expected_first_unfinished=None,
        )
        self.assertEqual(outcome.code, "WARN_UNTRUSTED_MARKER")
        self.assertEqual(t.calls, [])

    def test_untrusted_competing_marker_blocks_effectful_update(self):
        trusted = saved(state())
        alien = dict(saved(state()), id=20)
        alien["author_association"] = "CONTRIBUTOR"
        alien["user"] = {"login": "untrusted"}
        t = MemoryTransport([trusted, alien])
        outcome = apply_cursor_write(
            t, task=TASK, proposed=state(2, "M1", "M2"),
            expected_revision=1, expected_first_unfinished="M1",
        )
        self.assertEqual(outcome.code, "WARN_UNTRUSTED_MARKER")
        self.assertEqual(t.calls, [])

    def test_wrong_task_never_written(self):
        t = MemoryTransport()
        other = CursorState(1, "kinoko34077/devflow#999", 1, None, "M1", None, (), STAMP)
        with self.assertRaises(ValueError):
            apply_cursor_write(t, task=TASK, proposed=other,
                               expected_revision=None, expected_first_unfinished=None)
        self.assertEqual(t.calls, [])


if __name__ == "__main__":
    unittest.main()
