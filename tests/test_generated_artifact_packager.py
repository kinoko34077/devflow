"""Read-only producer packager acceptance and rejection tests."""
import copy
import hashlib
import json
import pathlib
import tempfile
import unittest

from tests.test_generated_artifact_contract import fixture
from tools.generated_artifact_contract import ArtifactRejected, validate_and_plan
from tools.generated_artifact_packager import canonical_manifest_json, package_approved_outputs


class GeneratedArtifactPackagerTests(unittest.TestCase):
    def setUp(self):
        self.policy, self.admission, self.manifest, self.files = fixture()

    def prepare(self, root):
        for path, content in self.files.items():
            p = root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)

    def test_packaging_is_byte_exact_and_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.prepare(root)
            m1, z1 = package_approved_outputs(self.policy, self.admission, root)
            m2, z2 = package_approved_outputs(self.policy, self.admission, root)
            self.assertEqual(m1, self.manifest)
            self.assertEqual(m1, m2)
            self.assertEqual(z1, z2)
            self.assertEqual(canonical_manifest_json(m1), canonical_manifest_json(m2))
            plan = validate_and_plan(self.policy, self.admission, m1, z1,
                                     observed_head=self.admission["expected_head"],
                                     existing_files={})
            self.assertEqual([i["path"] for i in plan["changes"]], sorted(self.files))

    def test_generated_path_cannot_be_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.prepare(root)
            target = root / "dist/table.bin"
            target.unlink()
            target.symlink_to(root / "dist/output.json")
            with self.assertRaises(ArtifactRejected):
                package_approved_outputs(self.policy, self.admission, root)

    def test_generated_path_cannot_be_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.prepare(root)
            target = root / "dist/table.bin"
            target.chmod(0o755)
            with self.assertRaises(ArtifactRejected):
                package_approved_outputs(self.policy, self.admission, root)

    def test_generated_parent_cannot_escape_by_symlink(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = pathlib.Path(directory)
            other = pathlib.Path(outside)
            root.mkdir(exist_ok=True)
            (other / "output.json").write_bytes(self.files["dist/output.json"])
            (other / "table.bin").write_bytes(self.files["dist/table.bin"])
            (root / "dist").symlink_to(other, target_is_directory=True)
            with self.assertRaises(ArtifactRejected):
                package_approved_outputs(self.policy, self.admission, root)

    def test_oversize_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.prepare(root)
            policy = copy.deepcopy(self.policy)
            policy["limits"]["max_file_bytes"] = 1
            with self.assertRaises(ArtifactRejected):
                package_approved_outputs(policy, self.admission, root)

    def test_mismatched_untrusted_recipe_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.prepare(root)
            admission = dict(self.admission, recipe_id="danger")
            with self.assertRaises(ArtifactRejected):
                package_approved_outputs(self.policy, admission, root)


if __name__ == "__main__":
    unittest.main()
