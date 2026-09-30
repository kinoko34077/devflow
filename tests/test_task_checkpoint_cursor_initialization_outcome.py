import unittest

from tools.task_checkpoint_cursor import initialize_cursor, verify_initialization


class CursorInitializationOutcomeTests(unittest.TestCase):
    def test_matching_initial_write_is_ok_initialized(self):
        written = initialize_cursor(
            task="kinoko34077/devflow#233",
            last_completed=None,
            first_unfinished="BOOTSTRAP",
            head=None,
            evidence=(),
            updated_at="2026-09-30T05:00:00Z",
        )
        result = verify_initialization(written, written)
        self.assertEqual(result.code, "OK_INITIALIZED")
        self.assertEqual(result.cursor, written)
        self.assertEqual(result.live, written)

    def test_initial_write_drift_is_post_write_warning(self):
        written = initialize_cursor(
            task="kinoko34077/devflow#233",
            last_completed=None,
            first_unfinished="BOOTSTRAP",
            head=None,
            evidence=(),
            updated_at="2026-09-30T05:00:00Z",
        )
        observed = initialize_cursor(
            task="kinoko34077/devflow#233",
            last_completed=None,
            first_unfinished="OTHER",
            head=None,
            evidence=(),
            updated_at="2026-09-30T05:00:01Z",
        )
        result = verify_initialization(written, observed)
        self.assertEqual(result.code, "WARN_POST_WRITE_DRIFT")
        self.assertEqual(result.live, observed)


if __name__ == "__main__":
    unittest.main()
