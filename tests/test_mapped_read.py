"""Common mapped-read contract: real Reader fixtures, no network or new auth."""
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlsplit, parse_qs

from tools.devflow_mcp_core import GitHubReader
from tools.mapped_github_read import github_source_maps
from devflow_mapped_read import MappedReadError, SourceMap, SourceObservation, read_mapped

REPO = "kinoko34077/devflow"
OTHER = "kinoko34077/example"
LOW = "2026-11-20T00:00:00Z"
HIGH = "2026-11-21T00:00:00Z"


def query(dataset="github.issue", repos=None):
    return {
        "schema_version": "mapped-read.v1",
        "time": {"field": "github.updated_at", "from_inclusive": LOW, "to_exclusive": HIGH},
        "target": {"dataset": dataset, "repositories": repos or [REPO]},
        "response": {"fields": ["id", "updated_at"]},
        "budget": {"per_page": 10, "max_pages": 2},
    }


class MappedReadTests(unittest.TestCase):
    def reader(self, *, fail_repo=None):
        calls = []
        def transport(url, headers):
            u = urlsplit(url)
            repo = "/".join(u.path.split("/")[2:4])
            calls.append((u.path, parse_qs(u.query)))
            if repo == fail_repo:
                raise RuntimeError("private failure detail")
            base = "https://api.github.com/repos/" + repo
            row = {"id": 1, "updated_at": LOW, "body": "never returned"}
            if u.path.endswith("/comments"):
                row["issue_url"] = base + "/issues/1"
            else:
                row.update(number=1, state="open", repository_url=base)
            return [row]
        return github_source_maps(GitHubReader(transport=transport)), calls

    def test_live_issue_and_comment_use_same_contract_and_reader(self):
        sources, calls = self.reader()
        for dataset in ("github.issue", "github.issue_comment"):
            result = read_mapped(query(dataset), sources=sources,
                                 allowed_repositories={REPO})
            self.assertEqual(result["items"], [{"repository": REPO,
                "record": {"id": 1, "updated_at": LOW}}])
            self.assertEqual(result["coverage"]["status"], "BOUNDED_READ")
            self.assertFalse(result["can_authorize_execution"])
            self.assertFalse(result["complete_source_universe"])
            self.assertTrue(result["requires_source_revalidation"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1]["direction"], ["asc"])
        self.assertIn("/issues/comments", calls[1][0])

    def test_multi_repo_failure_is_local_and_does_not_prove_absence(self):
        sources, calls = self.reader(fail_repo=REPO)
        result = read_mapped(query(repos=[REPO, OTHER]), sources=sources,
                             allowed_repositories={REPO, OTHER})
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["coverage"]["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(result["coverage"]["repositories"][0]["status"], "BLOCKED")
        self.assertEqual(result["items"][0]["repository"], OTHER)
        self.assertNotIn("private failure detail", repr(result))

    def test_missing_projection_is_local_and_never_returns_prefix(self):
        def prepare(lower, upper, filters, budget):
            def read(repo):
                rows = ({"id": 1}, {"other": 2}) if repo == REPO else ({"id": 3},)
                return SourceObservation(rows, "BOUNDED_READ", "FIXTURE_READ", read_units=1)
            return read
        packet = query("fixture", [REPO, OTHER])
        packet["time"] = None
        packet["response"]["fields"] = ["id"]
        sources = {"fixture": SourceMap("fixture", None, frozenset({"id"}), prepare)}
        result = read_mapped(packet, sources=sources, allowed_repositories={REPO, OTHER})
        self.assertEqual(result["items"], [{"repository": OTHER, "record": {"id": 3}}])
        self.assertEqual(result["coverage"]["status"], "PARTIAL_UNKNOWN")
        bad = result["coverage"]["repositories"][0]
        self.assertEqual(bad["reason_codes"], ["MISSING_SOURCE_FIELD"])
        self.assertEqual(bad["read_units"], 1)

    def test_invalid_metadata_is_not_exposed(self):
        def transport(url, headers):
            return [{"id": 1, "number": 1, "state": "open", "repository_url":
                     "https://api.github.com/repos/" + REPO, "updated_at": LOW,
                     "title": {"body": "must not be returned"}}]
        sources = github_source_maps(GitHubReader(transport=transport))
        packet = query()
        packet["response"]["fields"] = ["title"]
        result = read_mapped(packet, sources=sources, allowed_repositories={REPO})
        self.assertEqual(result["items"], [])
        self.assertEqual(result["coverage"]["status"], "BLOCKED")
        self.assertNotIn("must not be returned", repr(result))
        self.assertEqual(result["coverage"]["repositories"][0]["reason_codes"],
                         ["INVALID_GITHUB_METADATA"])

    def test_external_checkout_import_does_not_depend_on_tools_namespace(self):
        # The foreign repository owns its own tools package. Import the one
        # canonical module from the verified devflow checkout, not a copy.
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            foreign = Path(tmp)
            (foreign / "tools").mkdir()
            (foreign / "tools" / "__init__.py").write_text("FOREIGN = True\n", encoding="utf-8")
            env = dict(os.environ, PYTHONPATH=str(root))
            script = (
                "import pathlib,tools,devflow_mapped_read as m;"
                "assert tools.FOREIGN;"
                "assert pathlib.Path(m.__file__).resolve().parent.parent == "
                "pathlib.Path(__import__('os').environ['PYTHONPATH']).resolve();"
                "assert m.SCHEMA == 'mapped-read.v1';"
                "assert m.parse_utc_timestamp('2026-11-20T00:00:00Z').year == 2026"
            )
            subprocess.run([sys.executable, "-c", script], cwd=foreign, env=env,
                           check=True, capture_output=True, timeout=30)

    def test_response_limit_is_not_complete(self):
        sources, calls = self.reader()
        packet = query(repos=[REPO, OTHER])
        packet["response"]["limit"] = 1
        result = read_mapped(packet, sources=sources,
                             allowed_repositories={REPO, OTHER})
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["coverage"]["matched"], 2)
        self.assertTrue(result["coverage"]["response_limited"])
        self.assertEqual(result["coverage"]["status"], "PARTIAL_UNKNOWN")

    def test_invalid_requests_never_get(self):
        cases = [
            ("target", {"dataset": "unregistered", "repositories": [REPO]}),
            ("target", {"dataset": "github.issue", "repositories": [REPO, OTHER]}),
            ("target", {"dataset": "github.issue", "repositories": [REPO, REPO]}),
            ("target", {"dataset": "github.issue", "repositories": ["../devflow"]}),
            ("target", {"dataset": "github.issue", "repositories": [REPO], "filters": {"unknown": 1}}),
            ("response", {"fields": ["body"]}),
            ("response", {"fields": ["id", "id"]}),
            ("response", {"fields": ["id"], "limit": True}),
            ("time", {"field": "archive.edited_at", "from_inclusive": LOW}),
            ("time", {"field": "github.updated_at", "from_inclusive": HIGH, "to_exclusive": LOW}),
            ("time", {"field": "github.updated_at", "from_inclusive": "2026-11-20T00:00:00.1Z"}),
            ("budget", {"max_pages": 0}),
            ("budget", {"bytes": 1}),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                sources, calls = self.reader()
                packet = query()
                packet[key] = value
                with self.assertRaises(MappedReadError):
                    read_mapped(packet, sources=sources, allowed_repositories={REPO})
                self.assertEqual(calls, [])

    def test_saved_and_index_fixture_use_distinct_time_meanings(self):
        calls = []
        def prepare(lower, upper, filters, budget):
            self.assertEqual((lower, upper), (LOW, HIGH))
            def read(repo):
                calls.append(repo)
                return SourceObservation(({"edit_id": "E1"},), "BOUNDED_READ",
                                         "BOUNDED_SAVED_READ", source_revision="fixed-fixture")
            return read
        sources = {"archive.saved-edits": SourceMap("archive", "archive.edited_at",
                     frozenset({"edit_id"}), prepare),
                   "issue-index.catalog": SourceMap("index", None, frozenset({"id"}), prepare)}
        packet = query("archive.saved-edits")
        packet["time"]["field"] = "archive.edited_at"
        packet["response"]["fields"] = ["edit_id"]
        packet["budget"] = {}
        result = read_mapped(packet, sources=sources, allowed_repositories={REPO})
        self.assertEqual(result["items"][0]["record"], {"edit_id": "E1"})
        self.assertEqual(result["coverage"]["repositories"][0]["source_revision"], "fixed-fixture")
        wrong = copy.deepcopy(packet)
        wrong["target"]["dataset"] = "issue-index.catalog"
        wrong["response"]["fields"] = ["id"]
        with self.assertRaisesRegex(MappedReadError, "UNSUPPORTED_TIME_FIELD"):
            read_mapped(wrong, sources=sources, allowed_repositories={REPO})
        self.assertEqual(calls, [REPO])


if __name__ == "__main__":
    unittest.main()
