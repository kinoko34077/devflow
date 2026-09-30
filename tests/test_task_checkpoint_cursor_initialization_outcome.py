import unittest

from tools.task_checkpoint_cursor import initialize_cursor


class CursorInitializationOutcomeTests(unittest.TestCase):
    def test_initialize_returns_ok_initialized_result(self):
        result = initialize_cursor(
            task="kinoko34077/devflow#233",
            last_completed=None,
            first_unfinished="BOOTSTRAP",
            head=None,
            evidence=(),
            updated_at="2026-09-30T05:00:00Z",
        )
        self.assertEqual(result.code, "OK_INITIALIZED")
        self.assertEqual(result.cursor.revision, 1)
        self.assertEqual(result.cursor.first_unfinished, "BOOTSTRAP")


if __name__ == "__main__":
    unittest.main()
