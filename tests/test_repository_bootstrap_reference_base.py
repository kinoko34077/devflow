import json
import unittest

from tools import repository_bootstrap as rb
from tests.test_repository_bootstrap import request_payload
from tests.test_repository_bootstrap_executor import FakeApi, context
from tests.test_repository_bootstrap_main_protection import ProtectionApi

NAME = "kinoko34077/example-repo"
SPEC = "# Explicit Project specification\n"
MANIFEST = {"schema_version": 1, "project": {"name": "example-repo", "type": "library"}}
DEFAULTS = {"schema_version": 1, "packs": {}}


def request(visibility="private", **overrides):
    payload = request_payload()
    payload["repository"]["visibility"] = visibility
    payload["initial_content"]["specification"] = SPEC
    payload["bootstrap"] = {
        "main_protection": "public-only-v1",
        "reference_base": {"manifest": MANIFEST, "defaults": DEFAULTS},
        **overrides,
    }
    return rb.normalize_request(payload, "[REPO CREATE] example-repo")


def fixture_seed(req, _ctx):
    # Deliberately synthetic provider, never installed or executed in GitHub.
    return {
        "AGENTS.md": "# Central entry fixture\n",
        "knt.cmd": "@rem fixture only\n",
        ".github/workflows/verify.yml": "# synthetic trusted Verify fixture\n",
        "project/project.json": json.dumps(req.reference_base["manifest"]),
        "project/defaults.json": json.dumps(req.reference_base["defaults"]),
        "project/docs/INDEX.md": "# Index\n",
        "project/docs/CURRENT_STATE.md": "# Initial state\n",
        "project/docs/SPEC.md": req.specification,
        "project/contracts/actions.json": '{"schema_version":1,"actions":[]}',
        "project/contracts/surfaces.json": '{"schema_version":1,"surfaces":{}}',
    }


class ReferenceBaseBootstrapTests(unittest.TestCase):
    def test_provider_unavailable_before_repository_creation(self):
        repo, devflow = FakeApi(), FakeApi()
        with self.assertRaises(rb.BootstrapFailure) as error:
            rb.BootstrapExecutor(repo, devflow).execute(request(), context())
        self.assertEqual(error.exception.stage, "VALIDATION")
        self.assertFalse(repo.repos)
        self.assertFalse(repo.files)

    def test_reference_adoption_and_exact_retry(self):
        repo, devflow = ProtectionApi(), FakeApi()
        executor = rb.BootstrapExecutor(repo, devflow, reference_seed_provider=fixture_seed)
        req = request()
        first = executor.execute(req, context())
        self.assertEqual(set(fixture_seed(req, context())) - {p for n, p in repo.files if n == NAME}, set())
        self.assertNotIn((NAME, "docs/SPECIFICATION.md"), repo.files)
        self.assertFalse(any(p.startswith(".kinotch/") for n, p in repo.files))
        self.assertEqual(repo.protection_calls, [])
        self.assertEqual(repo.files[(NAME, "project/docs/SPEC.md")], SPEC)
        self.assertIn("project/project.json", devflow.issues["kinoko34077/devflow"][0]["body"])
        before = dict(repo.files)
        second = executor.execute(req, context())
        self.assertEqual(repo.files, before)
        self.assertEqual(first.head_sha, second.head_sha)
        self.assertEqual(len(repo.issues[NAME]), 1)

    def test_public_protection_uses_same_seed_verify(self):
        repo, devflow = ProtectionApi(), FakeApi()
        req = request("public")
        rb.BootstrapExecutor(repo, devflow, reference_seed_provider=fixture_seed).execute(req, context())
        verify = fixture_seed(req, context())[".github/workflows/verify.yml"]
        self.assertEqual(repo.files[(NAME, ".github/workflows/verify.yml")], verify)
        self.assertEqual(repo.protection_payloads[0]["required_status_checks"]["contexts"], ["verify"])
        self.assertLess(repo.events.index(("create_file", "project/project.json")), repo.events.index(("create_file", ".github/workflows/verify.yml")))
        self.assertLess(repo.events.index(("create_file", ".github/workflows/verify.yml")), repo.events.index(("set_branch_protection", "main")))

    def test_invalid_seed_has_no_repository_side_effect(self):
        for mutation in (
            lambda f: f.update({".kinotch/copied.ps1": "forbidden"}),
            lambda f: f.pop("knt.cmd"),
            lambda f: f.pop("project/contracts/actions.json"),
            lambda f: f.update({"project/project.json": '{"project":{"name":"other"}}'}),
            lambda f: f.update({"project/docs/SPEC.md": "# Changed"}),
        ):
            with self.subTest(mutation=mutation):
                repo, devflow = FakeApi(), FakeApi()
                def provider(req, ctx):
                    files = fixture_seed(req, ctx)
                    mutation(files)
                    return files
                with self.assertRaises(rb.BootstrapFailure):
                    rb.BootstrapExecutor(repo, devflow, reference_seed_provider=provider).execute(request(), context())
                self.assertFalse(repo.repos)
                self.assertFalse(repo.files)

    def test_conflicting_existing_reference_seed_preserved(self):
        repo, devflow = ProtectionApi(), FakeApi()
        executor = rb.BootstrapExecutor(repo, devflow, reference_seed_provider=fixture_seed)
        req = request()
        executor.execute(req, context())
        repo.files[(NAME, "AGENTS.md")] = "# Custom\n"
        del repo.files[(NAME, "knt.cmd")]
        before = dict(repo.files)
        with self.assertRaises(rb.BootstrapFailure):
            executor.execute(req, context())
        self.assertEqual(repo.files, before)

    def test_legacy_never_invokes_reference_provider(self):
        repo, devflow = FakeApi(), FakeApi()
        def forbidden(*_args):
            raise AssertionError("legacy path selected reference provider")
        legacy = rb.normalize_request(request_payload(), "[REPO CREATE] example-repo")
        rb.BootstrapExecutor(repo, devflow, reference_seed_provider=forbidden).execute(legacy, context())
        self.assertNotIn((NAME, "AGENTS.md"), repo.files)

    def test_request_cannot_choose_authority_or_other_project(self):
        with self.assertRaises(rb.BootstrapError):
            request(reference_base={"manifest": MANIFEST, "defaults": DEFAULTS, "commit": "a" * 40})
        with self.assertRaises(rb.BootstrapError):
            request(reference_base={"manifest": {"project": {"name": "other"}}, "defaults": DEFAULTS})
        with self.assertRaises(rb.BootstrapError):
            request(devflow_managed=False)
