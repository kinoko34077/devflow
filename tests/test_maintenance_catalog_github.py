import base64
import json
import unittest

from tools import maintenance_github as mg


BASELINE_PATH = "docs/spec/maintenance/common-baseline.v1.yaml"
CATALOG_PATH = ".devflow/maintenance.yaml"
REPO = "kinoko34077/example"
CONTROL = "kinoko34077/devflow#99"
HEAD = "a" * 40


def issue(number, title, *, association="OWNER", body="", state="open"):
    return {
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "repository_url": f"https://api.github.com/repos/{REPO}",
        "author_association": association,
    }


class FakeTransport:
    def __init__(self, *, baseline, catalog, issues, comments=None):
        self.baseline = baseline
        self.catalog = catalog
        self.issues = issues
        self.comments = comments or {}
        self.file_reads = []

    def get_default_branch(self, repository):
        return {"name": "main", "commit": {"sha": HEAD}}

    def get_repository_file(self, repository, path, ref=None):
        self.file_reads.append((repository, path, ref))
        if repository == "kinoko34077/devflow" and path == BASELINE_PATH:
            return {"content": self.baseline, "sha": "b" * 40}
        if repository == REPO and path == CATALOG_PATH:
            return self.catalog
        raise AssertionError((repository, path, ref))

    def list_issues(self, repository, state="open"):
        self.assert_repo(repository)
        return list(self.issues)

    def list_issue_comments(self, repository, issue_number):
        self.assert_repo(repository)
        return list(self.comments.get(issue_number, []))

    def assert_repo(self, repository):
        if repository != REPO:
            raise AssertionError(repository)


class CatalogCollectionTests(unittest.TestCase):
    def setUp(self):
        self.baseline = json.dumps(mg.default_test_baseline())
        self.catalog = json.dumps(mg.default_test_catalog(REPO))

    def test_transport_repository_file_supports_exact_ref(self):
        seen = []

        class Response:
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self):
                return json.dumps({
                    "type": "file",
                    "sha": "c" * 40,
                    "content": base64.b64encode(b"hello").decode(),
                }).encode()

        def opener(request, timeout=0):
            seen.append(request.full_url)
            return Response()

        transport = mg.GitHubReadTransport("token", opener=opener)
        value = transport.get_repository_file(REPO, ".devflow/maintenance.yaml", ref=HEAD)
        self.assertEqual("hello", value["content"])
        self.assertIn("ref=" + HEAD, seen[0])

    def test_collect_catalog_reads_target_exact_default_head(self):
        transport = FakeTransport(
            baseline=self.baseline,
            catalog={"content": self.catalog, "sha": "d" * 40},
            issues=[issue(7, "[MAINTENANCE] Audit Ledger")],
        )
        observation = mg.collect_maintenance_catalog(transport, REPO, CONTROL)
        self.assertEqual("OK", observation["status"])
        self.assertEqual(HEAD, observation["code_sha"])
        self.assertRegex(observation["catalog_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertIn((REPO, CATALOG_PATH, HEAD), transport.file_reads)

    def test_missing_catalog_is_no_catalog_not_guessed_work(self):
        transport = FakeTransport(
            baseline=self.baseline,
            catalog=None,
            issues=[issue(7, "[MAINTENANCE] Audit Ledger")],
        )
        observation = mg.collect_maintenance_catalog(transport, REPO, CONTROL)
        self.assertEqual(("NO_CATALOG", "CATALOG_NOT_FOUND"), (observation["status"], observation["reason_code"]))

    def test_malformed_catalog_is_needs_evidence(self):
        transport = FakeTransport(
            baseline=self.baseline,
            catalog={"content": "{bad", "sha": "d" * 40},
            issues=[issue(7, "[MAINTENANCE] Audit Ledger")],
        )
        observation = mg.collect_maintenance_catalog(transport, REPO, CONTROL)
        self.assertEqual(("NEEDS_EVIDENCE", "CATALOG_INVALID"), (observation["status"], observation["reason_code"]))

    def test_missing_or_multiple_ledger_is_typed_evidence_failure(self):
        for issues, code in (
            ([], "LEDGER_NOT_FOUND"),
            ([issue(7, "[MAINTENANCE] Audit Ledger"), issue(8, "[MAINTENANCE] Audit Ledger")], "LEDGER_DUPLICATE"),
        ):
            with self.subTest(code=code):
                transport = FakeTransport(
                    baseline=self.baseline,
                    catalog={"content": self.catalog, "sha": "d" * 40},
                    issues=issues,
                )
                result = mg.collect_maintenance_selection(transport, REPO, CONTROL, "2026-10-07T00:00:00Z")
                self.assertEqual(("NEEDS_EVIDENCE", code), (result["status"], result["reason_code"]))

    def test_only_trusted_ledger_comments_contribute_history(self):
        from tools.maintenance_ledger import RunRecord, render_run_comment
        trusted = RunRecord(
            repository=REPO,
            run_id=f"audit:{REPO}:common.correctness:1",
            slot_id="common.correctness",
            generation=1,
            lens="correctness",
            depth="STANDARD",
            fingerprint="sha256:" + "1" * 64,
            result="CLEAN",
            findings_summary="none",
            completed_at="2026-09-01T00:00:00Z",
            next_eligibility_reason=None,
            evidence_refs=(),
        )
        untrusted = mg.replace_run_record(
            trusted,
            generation=2,
            run_id=f"audit:{REPO}:common.correctness:2",
            completed_at="2026-10-01T00:00:00Z",
        )
        transport = FakeTransport(
            baseline=self.baseline,
            catalog={"content": self.catalog, "sha": "d" * 40},
            issues=[issue(7, "[MAINTENANCE] Audit Ledger")],
            comments={
                7: [
                    {"body": render_run_comment(trusted), "author_association": "OWNER"},
                    {"body": render_run_comment(untrusted), "author_association": "NONE"},
                ]
            },
        )
        history = mg.collect_maintenance_history(transport, REPO, 7)
        self.assertEqual((trusted,), history)

    def test_external_observation_changes_fingerprint_without_code_change(self):
        first = mg.build_maintenance_fingerprint(
            HEAD,
            "sha256:" + "2" * 64,
            {"provider_spec": "v1"},
        )
        second = mg.build_maintenance_fingerprint(
            HEAD,
            "sha256:" + "2" * 64,
            {"provider_spec": "v2"},
        )
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
