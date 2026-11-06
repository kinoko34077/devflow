"""Opt-in local public KAEP scan cursor: no unwarranted mutation or authority."""
from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path
from unittest import TestCase, mock

from tools import kaep_public_incremental_cli as inc


REPO = "kinoko34077/devflow"


def report(head: int = 100, status: str = "BOUNDED_INCREMENTAL_READ"):
    return inc._basic(
        status=status, mode="INCREMENTAL", requests=2, repo_count=1,
        locators=[], incomplete=[],
        checkpoint=inc._checkpoint({REPO: head})
        if status == "BOUNDED_INCREMENTAL_READ" else None)


class LocalCursorTests(TestCase):
    def call(self, argv, result):
        with (mock.patch.object(inc, "discover_incremental", return_value=result) as discover,
              mock.patch("sys.stdout", new_callable=io.StringIO) as output):
            code = inc.main(argv)
        return code, json.loads(output.getvalue()), discover

    def test_explicit_state_file_is_written_atomically_and_loaded_next_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "public-head.json"
            rc, out, first = self.call(["--state-file", str(f)], report(100))
            self.assertEqual(rc, 0)
            self.assertTrue(out["local_cursor_persisted"])
            self.assertTrue(f.is_file())
            self.assertEqual(json.loads(f.read_text())["heads"], {REPO: 100})
            self.assertIsNone(first.call_args.kwargs["prior"])
            rc, out, second = self.call(["--state-file", str(f)], report(200))
            self.assertEqual(rc, 0)
            self.assertEqual(second.call_args.kwargs["prior"]["heads"], {REPO: 100})
            self.assertEqual(json.loads(f.read_text())["heads"], {REPO: 200})
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_partial_does_not_mutate_saved_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "head.json"
            cursor = inc._checkpoint({REPO: 777})
            f.write_text(json.dumps(cursor))
            old = f.read_bytes()
            partial = report(status="PARTIAL_UNKNOWN")
            code, out, _ = self.call(["--state-file", str(f)], partial)
            self.assertEqual(code, 2)
            self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
            self.assertEqual(f.read_bytes(), old)

    def test_failed_local_update_is_partial_and_preserves_old_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "head.json"
            old = inc._checkpoint({REPO: 100})
            f.write_text(json.dumps(old))
            old_bytes = f.read_bytes()
            with (mock.patch.object(inc, "_persist_cursor_file",
                                    side_effect=OSError("private filesystem debug")),
                  mock.patch.object(inc, "discover_incremental", return_value=report(200)),
                  mock.patch("sys.stdout", new_callable=io.StringIO) as output):
                code = inc.main(["--state-file", str(f)])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 2)
            self.assertEqual(data["status"], "PARTIAL_UNKNOWN")
            self.assertFalse(data["cursor_advanced"])
            self.assertIsNone(data["next_cursor"])
            self.assertFalse(data["local_cursor_persisted"])
            self.assertIn("LOCAL_CURSOR_WRITE_FAILED",
                          [x["reason_code"] for x in data["incomplete_scopes"]])
            self.assertEqual(f.read_bytes(), old_bytes)
            self.assertNotIn("private filesystem debug", output.getvalue())

    def test_concurrent_mutation_is_detected_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "head.json"
            old = json.dumps(inc._checkpoint({REPO: 100})).encode()
            f.write_bytes(old)
            f.write_text(json.dumps(inc._checkpoint({REPO: 150})))
            with self.assertRaisesRegex(Exception, "CURSOR_CHANGED_ON_DISK"):
                inc._persist_cursor_file(f, inc._checkpoint({REPO: 200}), old)
            self.assertEqual(json.loads(f.read_text())["heads"][REPO], 150)
            self.assertEqual(list(Path(tmp).glob(".kaep-public-cursor-*.tmp")), [])

    def test_nonregular_cursor_and_corrupted_cursor_are_blocked_before_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            dirpath = Path(tmp) / "cursor-dir"
            dirpath.mkdir()
            with (mock.patch.object(inc, "discover_incremental") as reader,
                  mock.patch("sys.stdout", new_callable=io.StringIO) as output):
                code = inc.main(["--state-file", str(dirpath)])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["status"], "BLOCKED")
            reader.assert_not_called()

            f = Path(tmp) / "bad.json"
            f.write_text('{"owner":"kinoko34077","owner":"kinoko34077"}')
            with (mock.patch.object(inc, "discover_incremental") as reader,
                  mock.patch("sys.stdout", new_callable=io.StringIO) as output):
                code = inc.main(["--state-file", str(f)])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["status"], "BLOCKED")
            reader.assert_not_called()

    def test_explicit_cursor_in_never_mutates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            cursor = inc._checkpoint({REPO: 100})
            path.write_text(json.dumps(cursor))
            before = path.read_bytes()
            code, _out, reader = self.call(["--cursor-in", str(path)], report(200))
            self.assertEqual(code, 0)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(reader.call_args.kwargs["prior"], cursor)


if __name__ == "__main__":
    import unittest
    unittest.main()
