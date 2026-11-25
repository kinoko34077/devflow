"""Shared artifact bytes tests, without any GitHub Actions producer identity."""
import copy
import unittest

from tools.generated_artifact_contract import ArtifactRejected, validate_payload_and_plan
from tools.generated_artifact_packager import package_generated_bytes


class GeneratedArtifactPayloadTests(unittest.TestCase):
    def setUp(self):
        self.blobs = {"output/catalog.json": b'{"ok":true}', "output/README.md": b"verified"}
        self.paths = sorted(self.blobs)
        self.limits = dict(max_files=4, max_file_bytes=1000, max_total_bytes=2000,
                           max_archive_bytes=4000, max_expansion_ratio=500)
        self.files, self.archive = package_generated_bytes(self.paths, self.limits, self.blobs)

    def plan(self, paths=None, limits=None, items=None, archive=None, existing=None):
        return validate_payload_and_plan(
            self.paths if paths is None else paths, self.limits if limits is None else limits,
            self.files if items is None else items, self.archive if archive is None else archive,
            existing_files={} if existing is None else existing,
        )

    def test_change_and_noop_without_actions_identity(self):
        plan = self.plan()
        self.assertEqual(plan["status"], "CHANGE")
        self.assertEqual(plan["file_count"], 2)
        self.assertIs(plan["writes_performed"], False)
        self.assertNotIn("producer_run_id", plan)
        self.assertEqual(self.plan(existing=self.blobs)["status"], "NO_OP")
        self.assertEqual(len(self.plan(existing={self.paths[0]: self.blobs[self.paths[0]]})["changes"]), 1)

    def test_paths_and_limits_are_independently_checked(self):
        for paths in ([], ["../escape"], self.paths + [self.paths[0]],
                      ["output/readme.md", "output/README.md"]):
            with self.subTest(paths=paths), self.assertRaises(ArtifactRejected):
                self.plan(paths=paths)
        for limits in (dict(self.limits, max_total_bytes=1),
                       dict(self.limits, max_files=1), dict(self.limits, max_archive_bytes=1)):
            with self.subTest(limits=limits), self.assertRaises(ArtifactRejected):
                self.plan(limits=limits)

    def test_manifest_tampering_and_unknown_paths_rejected(self):
        items = copy.deepcopy(self.files)
        items[0]["sha256"] = "0"*64
        with self.assertRaises(ArtifactRejected):
            self.plan(items=items)
        with self.assertRaises(ArtifactRejected):
            self.plan(existing={"outside.md": b""})
        with self.assertRaises(ArtifactRejected):
            package_generated_bytes(self.paths, self.limits, {**self.blobs, "outside.md": b"x"})
        with self.assertRaises(ArtifactRejected):
            package_generated_bytes(self.paths, self.limits, {self.paths[0]: b"x"})

    def test_package_is_deterministic_and_bounded(self):
        self.assertEqual(package_generated_bytes(self.paths, self.limits, self.blobs),
                         (self.files, self.archive))
        with self.assertRaises(ArtifactRejected):
            package_generated_bytes(self.paths, dict(self.limits, max_file_bytes=1), self.blobs)

if __name__ == "__main__":
    unittest.main()
