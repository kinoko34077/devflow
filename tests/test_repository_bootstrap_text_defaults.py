from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.test_repository_bootstrap import issue_body
from tests.test_repository_bootstrap_executor import FakeApi, context
from tools import repository_bootstrap as rb


ROOT = Path(__file__).resolve().parents[1]
FULL_NAME = "kinoko34077/example-repo"
ATTRIBUTES = ".gitattributes"
EDITORCONFIG = ".editorconfig"
MARKER = "portable-text-v1"


def request(marker=None, *, managed=True):
    payload = rb.parse_request_body(issue_body())
    payload["bootstrap"]["devflow_managed"] = managed
    payload["devflow"]["create_control"] = managed
    if marker is not None:
        payload["bootstrap"]["text_defaults"] = marker
    return rb.normalize_request(payload, "[REPO CREATE] example-repo")


class BootstrapTextDefaultsTests(unittest.TestCase):
    def test_opt_in_installs_exact_versioned_root_files(self):
        req = request(MARKER)
        repository, devflow = FakeApi(), FakeApi()
        result = rb.BootstrapExecutor(repository, devflow).execute(req, context())

        self.assertEqual(req.text_defaults, MARKER)
        for target, template in rb.TEXT_DEFAULTS_FILES:
            expected = (ROOT / "templates/bootstrap" / template).read_text(encoding="utf-8")
            self.assertEqual(repository.files[(FULL_NAME, target)], expected)
            self.assertIn(f"file:{target}", result.resources)
            self.assertTrue(expected.endswith("\n"))
            self.assertNotIn("\r", expected)

        attrs = repository.files[(FULL_NAME, ATTRIBUTES)]
        self.assertIn("* text=auto eol=lf\n", attrs)
        self.assertIn("*.bat text eol=crlf\n", attrs)
        self.assertIn("*.cmd text eol=crlf\n", attrs)
        editor = repository.files[(FULL_NAME, EDITORCONFIG)]
        for required in (
            "root = true",
            "charset = utf-8",
            "insert_final_newline = true",
            "[*.md]",
            "trim_trailing_whitespace = false",
            "[*.go]",
            "[*.{bat,cmd}]",
            "end_of_line = crlf",
        ):
            self.assertIn(required, editor)

    def test_historical_request_does_not_seed_new_files_on_first_run_or_retry(self):
        req = request()
        self.assertIsNone(req.text_defaults)
        repository, devflow = FakeApi(), FakeApi()
        executor = rb.BootstrapExecutor(repository, devflow)
        executor.execute(req, context())
        executor.execute(req, context())
        self.assertNotIn((FULL_NAME, ATTRIBUTES), repository.files)
        self.assertNotIn((FULL_NAME, EDITORCONFIG), repository.files)

    def test_opt_in_retry_is_idempotent(self):
        req = request(MARKER)
        repository, devflow = FakeApi(), FakeApi()
        executor = rb.BootstrapExecutor(repository, devflow)
        executor.execute(req, context())
        before = dict(repository.files)
        executor.execute(req, context())
        self.assertEqual(repository.files, before)

    def test_user_modified_attributes_fail_closed_without_overwrite(self):
        req = request(MARKER)
        repository, devflow = FakeApi(), FakeApi()
        executor = rb.BootstrapExecutor(repository, devflow)
        executor.execute(req, context())
        key = (FULL_NAME, ATTRIBUTES)
        repository.files[key] += "# local adjustment\n"
        before = dict(repository.files)

        with self.assertRaises(rb.BootstrapFailure) as raised:
            executor.execute(req, context())

        self.assertEqual(raised.exception.stage, "SEED")
        self.assertEqual(raised.exception.safe_retry, "after-human-decision")
        self.assertEqual(repository.files, before)

    def test_user_modified_editorconfig_fail_closed_without_overwrite(self):
        req = request(MARKER)
        repository = FakeApi()
        executor = rb.BootstrapExecutor(repository, FakeApi())
        executor.execute(req, context())
        key = (FULL_NAME, EDITORCONFIG)
        repository.files[key] += "# local override\n"
        before = dict(repository.files)

        with self.assertRaises(rb.BootstrapFailure) as raised:
            executor.execute(req, context())

        self.assertEqual(raised.exception.stage, "SEED")
        self.assertEqual(repository.files, before)

    def test_invalid_and_unmanaged_markers_are_rejected_before_mutation(self):
        for marker, managed in (
            ("unknown-v1", True),
            ("portable-text-v1", False),
        ):
            with self.subTest(marker=marker, managed=managed), self.assertRaises(rb.BootstrapError):
                request(marker, managed=managed)

    def test_documentary_schema_and_agent_entry_match_runtime_policy(self):
        schema = json.loads((ROOT / "schemas/repository-bootstrap.v1.schema.json").read_text(encoding="utf-8"))
        marker = schema["properties"]["bootstrap"]["properties"]["text_defaults"]
        self.assertEqual(marker["const"], rb.TEXT_DEFAULTS_POLICY)
        for path in (
            "AGENTS.md",
            "docs/spec/REPOSITORY_BOOTSTRAP.md",
            "docs/operations/REPOSITORY_BOOTSTRAP.md",
        ):
            with self.subTest(path=path):
                self.assertIn(
                    'text_defaults: "portable-text-v1"',
                    (ROOT / path).read_text(encoding="utf-8"),
                )


if __name__ == "__main__":
    unittest.main()
