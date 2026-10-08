"""S2 negative/positive tests for low-trust generated artifact input."""
import copy
import hashlib
import io
import json
import stat
import unittest
import warnings
import zipfile

from tools.generated_artifact_contract import (
    ArtifactRejected, manifest_digest, validate_and_plan,
)

WORKFLOW_REF = "kinoko34077/example/.github/workflows/generate.yml@" + "f" * 40
SOURCE_SHA = "a" * 40
HEAD_SHA = "b" * 40


def fixture():
    files = {"dist/output.json": b'{"ok":true}\n', "dist/table.bin": b"\x00\xff\x01DATA"}
    policy = {
        "schema": "generated-artifacts-policy.v1",
        "repository": "kinoko34077/example",
        "allowed_actors": ["kinoko34077"],
        "default_branch": "main",
        "branch_prefix": "artifact/",
        "forbidden_branches": ["master", "production"],
        "recipe": {
            "id": "canonical-json", "version": "1",
            "paths": sorted(files),
        },
        "producer_workflow_ref": WORKFLOW_REF,
        "limits": {
            "max_files": 4, "max_file_bytes": 1000000,
            "max_total_bytes": 2000000, "max_archive_bytes": 3000000,
            "max_expansion_ratio": 500,
        },
    }
    admission = {
        "repository": "kinoko34077/example",
        "actor": "kinoko34077",
        "branch": "artifact/pilot-1",
        "expected_head": HEAD_SHA,
        "source_sha": SOURCE_SHA,
        "recipe_id": "canonical-json",
        "recipe_version": "1",
        "producer_run_id": 37752814325,
        "producer_run_attempt": 1,
        "producer_workflow_ref": WORKFLOW_REF,
    }
    manifest = {
        "schema": "generated-artifacts.v1",
        "provenance": dict(admission),
        "files": [
            {"path": path, "size": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}
            for path, blob in sorted(files.items())
        ],
    }
    return policy, admission, manifest, files


def zip_bytes(files, *, extra=None, symlink=None, duplicate=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, blob in files.items():
            archive.writestr(path, blob)
        if extra is not None:
            archive.writestr(extra, b"extra")
        if symlink is not None:
            entry = zipfile.ZipInfo(symlink)
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(entry, b"target")
        if duplicate is not None:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr(duplicate, files[duplicate])
    return out.getvalue()


class GeneratedArtifactContractTests(unittest.TestCase):
    def setUp(self):
        self.policy, self.admission, self.manifest, self.files = fixture()
        self.archive = zip_bytes(self.files)

    def plan(self, *, policy=None, admission=None, manifest=None,
             archive=None, observed_head=HEAD_SHA, existing_files=None):
        return validate_and_plan(
            self.policy if policy is None else policy,
            self.admission if admission is None else admission,
            self.manifest if manifest is None else manifest,
            self.archive if archive is None else archive,
            observed_head=observed_head,
            existing_files={} if existing_files is None else existing_files,
        )

    def test_two_binary_exact_changes_dry_run_without_write(self):
        result = self.plan()
        self.assertEqual(result["status"], "CHANGE")
        self.assertEqual([x["path"] for x in result["changes"]], sorted(self.files))
        self.assertEqual(result["total_bytes"], sum(map(len, self.files.values())))
        self.assertEqual(result["manifest_sha256"], manifest_digest(self.manifest))
        self.assertIs(result["writes_performed"], False)

    def test_identical_payload_is_noop(self):
        self.assertEqual(
            self.plan(existing_files=dict(self.files))["status"], "NO_OP"
        )

    def test_only_changed_allowed_bytes_appear_in_plan(self):
        existing = {"dist/table.bin": self.files["dist/table.bin"]}
        self.assertEqual(
            [change["path"] for change in self.plan(existing_files=existing)["changes"]],
            ["dist/output.json"],
        )

    def test_missing_or_spoofed_run_provenance_rejected(self):
        for key, value in [
            ("producer_run_id", 4),
            ("producer_run_attempt", 2),
            ("source_sha", "c" * 40),
            ("producer_workflow_ref", "bad"),
            ("actor", "attacker"),
            ("expected_head", "c" * 40),
        ]:
            with self.subTest(key=key):
                mutated = copy.deepcopy(self.manifest)
                mutated["provenance"][key] = value
                with self.assertRaises(ArtifactRejected):
                    self.plan(manifest=mutated)

    def test_actor_repo_recipe_source_workflow_policy_rejected(self):
        for key, value in [
            ("actor", "fork-actor"),
            ("repository", "kinoko34077/other"),
            ("recipe_id", "run-shell"),
            ("recipe_version", "2"),
            ("producer_workflow_ref", "untrusted.yml@main"),
        ]:
            with self.subTest(key=key):
                a = copy.deepcopy(self.admission)
                a[key] = value
                m = copy.deepcopy(self.manifest)
                m["provenance"] = copy.deepcopy(a)
                with self.assertRaises(ArtifactRejected):
                    self.plan(admission=a, manifest=m)

    def test_moved_head_rejected_even_when_bytes_are_identical(self):
        with self.assertRaisesRegex(ArtifactRejected, "head moved"):
            self.plan(observed_head="c" * 40, existing_files=self.files)

    def test_default_unknown_protected_and_malicious_branches_rejected(self):
        for branch in ["main", "master", "production", "feature/foo",
                       "artifact/", "artifact/../bad", "artifact/.hidden",
                       "artifact/ref lock", "artifact/foo.lock"]:
            with self.subTest(branch=branch):
                a = copy.deepcopy(self.admission)
                a["branch"] = branch
                m = copy.deepcopy(self.manifest)
                m["provenance"] = dict(a)
                with self.assertRaises(ArtifactRejected):
                    self.plan(admission=a, manifest=m)

    def test_digest_mismatch_rejected(self):
        files = dict(self.files)
        files["dist/table.bin"] = b"tamper!"
        with self.assertRaisesRegex(ArtifactRejected, "digest"):
            self.plan(archive=zip_bytes(files))

    def test_zip_extra_omission_and_duplicate_rejected(self):
        for archive in [
            zip_bytes(self.files, extra=".github/workflows/backdoor.yml"),
            zip_bytes(self.files, extra="../escape"),
            zip_bytes({k: v for k, v in self.files.items() if k != "dist/table.bin"}),
            zip_bytes(self.files, duplicate="dist/output.json"),
        ]:
            with self.assertRaises(ArtifactRejected):
                self.plan(archive=archive)

    def test_symlink_member_rejected(self):
        files = {"dist/output.json": self.files["dist/output.json"]}
        with self.assertRaises(ArtifactRejected):
            self.plan(archive=zip_bytes(files, symlink="dist/table.bin"))

    def test_manifest_missing_duplicate_extra_or_unsafe_path_rejected(self):
        variants = []
        m = copy.deepcopy(self.manifest)
        m["files"] = m["files"][:1]
        variants.append(m)
        m = copy.deepcopy(self.manifest)
        m["files"][1] = dict(m["files"][0])
        variants.append(m)
        m = copy.deepcopy(self.manifest)
        m["files"][1]["path"] = ".github/workflows/hack.yml"
        variants.append(m)
        m = copy.deepcopy(self.manifest)
        m["files"][1]["path"] = "../escape"
        variants.append(m)
        m = copy.deepcopy(self.manifest)
        m["files"][1]["path"] = "dist/../escape"
        variants.append(m)
        m = copy.deepcopy(self.manifest)
        m["extra"] = True
        variants.append(m)
        for m in variants:
            with self.subTest(variant=m):
                with self.assertRaises(ArtifactRejected):
                    self.plan(manifest=m)

    def test_size_count_archive_and_expansion_limits_rejected(self):
        for field, value in [("max_file_bytes", 1), ("max_files", 1),
                             ("max_total_bytes", 5), ("max_archive_bytes", 5)]:
            with self.subTest(field=field):
                p = copy.deepcopy(self.policy)
                p["limits"][field] = value
                with self.assertRaises(ArtifactRejected):
                    self.plan(policy=p)

    def test_highly_compressible_payload_refused_without_excessive_extract(self):
        payload = b"x" * 10000
        files = {"dist/output.json": payload, "dist/table.bin": self.files["dist/table.bin"]}
        m = copy.deepcopy(self.manifest)
        m["files"][0]["size"] = len(payload)
        m["files"][0]["sha256"] = hashlib.sha256(payload).hexdigest()
        p = copy.deepcopy(self.policy)
        p["limits"]["max_expansion_ratio"] = 10
        with self.assertRaisesRegex(ArtifactRejected, "expansion"):
            self.plan(policy=p, manifest=m, archive=zip_bytes(files))

    def test_invalid_archive_and_policy_rejected(self):
        with self.assertRaises(ArtifactRejected):
            self.plan(archive=b"not-a-zip")
        for path in ["dist/../out.json", "dist/out\\evil.json", ".github/workflows/x.yml"]:
            p = copy.deepcopy(self.policy)
            p["recipe"]["paths"][0] = path
            with self.assertRaises(ArtifactRejected):
                self.plan(policy=p)

    def test_unknown_observed_worktree_path_or_non_bytes_rejected(self):
        for observed in [{"src/app.py": b"tamper"}, {"dist/table.bin": "not bytes"}]:
            with self.assertRaises(ArtifactRejected):
                self.plan(existing_files=observed)

    def test_cannot_supply_unexpected_force_or_command_field(self):
        a = copy.deepcopy(self.admission)
        a["force"] = True
        m = copy.deepcopy(self.manifest)
        m["provenance"] = dict(a)
        with self.assertRaises(ArtifactRejected):
            self.plan(admission=a, manifest=m)


if __name__ == "__main__":
    unittest.main()
