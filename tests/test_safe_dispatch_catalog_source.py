"""Adversarial synthetic Git-object fixtures; no API, token, or private data."""
import hashlib
import json
import unittest
from dataclasses import replace

from tools.safe_dispatch_catalog_source import CatalogSourcePin, verify_catalog_source


def oid(kind: bytes, raw: bytes) -> str:
    return hashlib.sha1(kind + b" " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def entry(mode: bytes, name: bytes, h: str) -> bytes:
    return mode + b" " + name + b"\0" + bytes.fromhex(h)


def valid_catalog():
    return {"schema": "dispatch-catalog.v1", "operator": "kinoko34077", "actions": {
        "repo.status": {"repository": "kinoko34077/kinotch-default-canary", "backend": "github_api",
                        "executor": "github.repository_metadata", "ref": "main", "effects": "read",
                        "human_gate": False, "inputs": {}}
    }}


def setup(*, data=None, tree_mode=b"100644"):
    if data is None:
        data = json.dumps(valid_catalog(), sort_keys=True, separators=(",", ":")).encode()
    blob_sha = oid(b"blob", data)
    folder = entry(tree_mode, b"catalog.json", blob_sha)
    folder_sha = oid(b"tree", folder)
    root = entry(b"40000", b"tools", folder_sha)
    root_sha = oid(b"tree", root)
    commit = f"tree {root_sha}\nauthor T <t@invalid> 1 +0000\ncommitter T <t@invalid> 1 +0000\n\ntest\n".encode()
    pin = CatalogSourcePin(314, oid(b"commit", commit), "tools/catalog.json", blob_sha,
                           hashlib.sha256(data).hexdigest())
    return pin, commit, {root_sha: root, folder_sha: folder}, {blob_sha: data}


class CatalogSourceTests(unittest.TestCase):
    def check(self, expected, pin=None, commit=None, trees=None, blobs=None):
        default = setup()
        result = verify_catalog_source(pin if pin is not None else default[0],
                                       commit_bytes=commit if commit is not None else default[1],
                                       trees_by_oid=trees if trees is not None else default[2],
                                       blobs_by_oid=blobs if blobs is not None else default[3])
        self.assertEqual(result.reason if expected != "OK" else result.status,
                         expected if expected != "OK" else "OFFLINE_SOURCE_MATCHED")
        if expected != "OK":
            self.assertIsNone(result.catalog)
        return result

    def test_valid_synthetic_git_graph_not_execution(self):
        r = self.check("OK")
        self.assertEqual(r.reason, "BYTES_MATCH_PINS_NOT_AUTHENTICATED")
        self.assertEqual(r.catalog["operator"], "kinoko34077")

    def test_invalid_or_forgeable_pin(self):
        p, c, t, b = setup()
        self.check("INVALID_BUILD_PIN", replace(p, source_repo_id=True), c, t, b)
        self.check("INVALID_BUILD_PIN", replace(p, commit_sha=p.commit_sha.upper()), c, t, b)
        for path in ("/tools/catalog.json", "tools/../catalog.json", "tools//catalog.json",
                     "tools/./catalog.json", "tools/catalog.json/", "tools\\catalog.json",
                     "tools/a.lock", "a/"*9+"catalog.json"):
            self.check("INVALID_BUILD_PIN", replace(p, catalog_path=path), c, t, b)

    def test_commit_hash_changed(self):
        p, c, t, b = setup()
        self.check("COMMIT_OID_MISMATCH", p, c+b"x", t, b)

    def test_commit_bad_header_with_correct_hash(self):
        p, c, t, b = setup()
        for corrupt in (b"author X\n\nM", b"tree not-an-oid\n\nM",
                        b"tree "+b"a"*40+b"\ntree "+b"b"*40+b"\n\nM"):
            self.check("INVALID_COMMIT_TREE", replace(p, commit_sha=oid(b"commit",corrupt)), corrupt,t,b)

    def test_missing_and_modified_tree(self):
        p,c,t,b=setup()
        self.check("MISSING_OR_LARGE_TREE",p,c,{},b)
        broken=dict(t);root=next(iter(t));broken[root]=t[root]+b"z"
        self.check("TREE_OID_MISMATCH",p,c,broken,b)

    def test_root_path_mismatch(self):
        p,c,t,b=setup()
        self.check("CATALOG_PATH_MISSING",replace(p,catalog_path="other/catalog.json"),c,t,b)
        self.check("CATALOG_PATH_MISSING",replace(p,catalog_path="tools/other.json"),c,t,b)

    def test_catalog_file_mode_rejection(self):
        for mode in (b"120000",b"160000",b"100755",b"40000"):
            p,c,t,b=setup(tree_mode=mode)
            self.check("CATALOG_NOT_REGULAR_FILE",p,c,t,b)

    def test_tree_duplicate_name_and_case_alias(self):
        p,c,t,b=setup()
        sha=p.blob_sha
        for raw in (entry(b"100644",b"catalog.json",sha)*2,
                    entry(b"100644",b"catalog.json",sha)+entry(b"100644",b"CATALOG.JSON",sha)):
            folder_oid=oid(b"tree",raw)
            root=entry(b"40000",b"tools",folder_oid)
            root_oid=oid(b"tree",root)
            commit=f"tree {root_oid}\n\nM".encode()
            self.check("INVALID_TREE_ENTRIES",replace(p,commit_sha=oid(b"commit",commit)),commit,
                       {root_oid:root,folder_oid:raw},b)

    def test_tree_truncation_and_invalid_mode(self):
        p,c,t,b=setup()
        for raw in (b"100644 catalog.json\x00"+b"z"*5,
                    b"000000 catalog.json\x00"+bytes.fromhex(p.blob_sha),
                    b"100644 ../catalog.json\x00"+bytes.fromhex(p.blob_sha)):
            folder_oid=oid(b"tree",raw)
            root=entry(b"40000",b"tools",folder_oid)
            root_oid=oid(b"tree",root)
            commit=f"tree {root_oid}\n\nM".encode()
            self.check("INVALID_TREE_ENTRIES",replace(p,commit_sha=oid(b"commit",commit)),commit,
                       {root_oid:root,folder_oid:raw},b)

    def test_blob_oid_and_sha256(self):
        p,c,t,b=setup()
        self.check("MISSING_OR_LARGE_CATALOG",p,c,t,{})
        self.check("BLOB_OID_MISMATCH",p,c,t,{p.blob_sha:b[p.blob_sha]+b" "})
        self.check("CATALOG_SHA256_MISMATCH",replace(p,content_sha256="f"*64),c,t,b)
        self.check("CATALOG_BLOB_NOT_PINNED",replace(p,blob_sha="f"*40),c,t,b)

    def test_bad_json_and_bad_schema(self):
        for raw, expected in ((b'{"a":1,"a":2}',"CATALOG_JSON_INVALID"),
                              (b'{"operator": 1}',"CATALOG_SCHEMA_INVALID")):
            p,c,t,b=setup(data=raw)
            self.check(expected,p,c,t,b)

    def test_oversized_objects_and_unsupported_maps(self):
        p,c,t,b=setup()
        self.check("INVALID_COMMIT_BYTES",p,b"z"*33000,t,b)
        self.check("INVALID_OBJECT_MAP",p,c,[],b)
        self.check("UNEXPECTED_OBJECT_COUNT",p,c,dict.fromkeys(["a"*39+str(i) for i in range(9)],b""),b)
        self.check("MISSING_OR_LARGE_CATALOG",p,c,t,{p.blob_sha:b"x"*8193})


if __name__ == "__main__":
    unittest.main()
