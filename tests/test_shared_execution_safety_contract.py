"""M2 no-effect compatibility tests: never promote input to a trusted executor."""
from __future__ import annotations

import json
import subprocess
import unittest
import urllib.request
from dataclasses import asdict
from unittest.mock import patch

from tools.shared_execution_safety_contract import (
    project_f3c_candidate, project_g1_policy,
)

_PREFIX = "F3C-WSL-PUBLIC-ONCE-V1\n"
_NONCE = "f3c-0123456789abcdefghij"


def legacy(**changes):
    obj = {
        "schema_version": "devflow.f3c.wsl-public-request.v1",
        "repository": "kinoko34077/devflow",
        "task_ref": "kinoko34077/devflow#610",
        "recipe_id": "wsl-fixed-public-v1",
        "effect": "READ_ONLY",
        "nonce": _NONCE,
    }
    obj.update(changes)
    return _PREFIX + json.dumps(obj, separators=(",", ":"))


def g1_request(**changes):
    req = dict(
        schema="dispatch-request.v1",
        request_id="req_m2_public001",
        repository="kinoko34077/devflow",
        action="repo.status", ref="main", head_sha="a" * 40, inputs={},
    )
    req.update(changes)
    return json.dumps(req)


def g1_catalog(*, effect="read", human=False):
    return {
        "schema": "dispatch-catalog.v1",
        "operator": "kinoko34077",
        "actions": {
            "repo.status": {
                "repository": "kinoko34077/devflow",
                "backend": "github_api",
                "executor": "github.repository_metadata",
                "ref": "main",
                "effects": effect,
                "human_gate": human,
                "inputs": {},
            }
        },
    }


class SharedExecutionSafetyContractTests(unittest.TestCase):
    def test_legacy_public_request_is_only_candidate(self):
        d = project_f3c_candidate(legacy(), comment_id=6199274701,
                                  observed_login="kinoko34077")
        self.assertEqual(d.status, "CANDIDATE_ONLY")
        self.assertEqual(d.effect, "READ_ONLY")
        self.assertEqual(d.repository, "kinoko34077/devflow")
        self.assertEqual(d.operation, "wsl-fixed-public-v1")
        self.assertEqual(d.request_id, "gh-comment-6199274701")
        self.assertEqual(len(d.request_digest), 64)
        self.assertEqual(len(d.nonce_digest), 64)
        self.assertNotIn(_NONCE, json.dumps(asdict(d)))
        self.assertEqual(d.backend_candidate, "fixed-public-wsl2")
        self.assertIsNone(d.source_sha)
        self.assertIsNone(d.catalog_sha256)
        for flag in ("authenticated", "source_verified", "claim_authority",
                     "github_check_authority", "independently_executed"):
            self.assertFalse(getattr(d, flag), flag)

    def test_legacy_cannot_promote_spoofed_actor(self):
        denied = project_f3c_candidate(
            legacy(), comment_id=6199274701, observed_login="attacker"
        )
        self.assertEqual(denied.status, "HOLD")
        ok = project_f3c_candidate(legacy(), comment_id=6199274701,
                                   observed_login="kinoko34077")
        self.assertFalse(ok.authenticated)
        self.assertFalse(ok.claim_authority)

    def test_legacy_duplicate_json_key_rejected_even_if_last_value_valid(self):
        raw = legacy()
        duplicate = raw[:-1] + ',"effect":"READ_ONLY"}'
        self.assertEqual(
            project_f3c_candidate(
                duplicate, comment_id=6199274701, observed_login="kinoko34077"
            ).reason, "STRICT_JSON_DENIED",
        )
        duplicate_nested = raw[:-1] + ',"source_sha":{"a":1,"a":2}}'
        self.assertEqual(
            project_f3c_candidate(
                duplicate_nested, comment_id=6199274701,
                observed_login="kinoko34077"
            ).reason, "STRICT_JSON_DENIED",
        )

    def test_legacy_fails_closed_wrong_effect_private_backend_source(self):
        cases = [
            {"effect": "WRITE"},
            {"repository": "kinoko34077/private"},
            {"task_ref": "kinoko34077/private#610"},
            {"recipe_id": "run arbitrary shell"},
            {"nonce": "../../unsafe"},
            {"schema_version": "devflow.any.v2"},
            {"source_sha": "a" * 40},
            {"backend": "external"},
            {"shell": "cmd.exe"},
            {"token": "SECRET"},
            {"effect": True},
            {"recipe_id": None},
            {"nonce": []},
        ]
        for mutation in cases:
            with self.subTest(mutation=mutation):
                out = project_f3c_candidate(
                    legacy(**mutation), comment_id=6199274701,
                    observed_login="kinoko34077"
                )
                self.assertEqual(out.status, "HOLD")
                self.assertIsNone(out.request_digest)
                self.assertFalse(out.authenticated)

    def test_legacy_empty_bad_prefix_comment_id_and_size_denied(self):
        for raw, comment_id, actor in (
            ("", 6199274701, "kinoko34077"),
            (legacy(), 0, "kinoko34077"),
            (legacy(), True, "kinoko34077"),
            (legacy(), 6199274701, "bot"),
            ("ignored\n" + legacy(), 6199274701, "kinoko34077"),
            (legacy() + "x" * 1050, 6199274701, "kinoko34077"),
        ):
            with self.subTest(comment_id=comment_id, actor=actor):
                self.assertEqual(
                    project_f3c_candidate(raw, comment_id=comment_id,
                                          observed_login=actor).status,
                    "HOLD",
                )

    def test_legacy_request_digest_is_canonical_but_comment_identity_distinct(self):
        original = project_f3c_candidate(
            legacy(), comment_id=6199274701, observed_login="kinoko34077")
        reversed_raw = _PREFIX + json.dumps(dict(reversed(
            list(json.loads(legacy()[len(_PREFIX):]).items())
        )))
        order_changed = project_f3c_candidate(
            reversed_raw, comment_id=6199274702, observed_login="kinoko34077")
        self.assertEqual(original.request_digest, order_changed.request_digest)
        self.assertNotEqual(original.request_id, order_changed.request_id)
        changed_nonce = project_f3c_candidate(
            legacy(nonce="f3c-0123456789abcdefghik"),
            comment_id=6199274701, observed_login="kinoko34077")
        self.assertNotEqual(original.nonce_digest, changed_nonce.nonce_digest)
        self.assertNotEqual(original.request_digest, changed_nonce.request_digest)

    def test_existing_g1_policy_admitted_stays_policy_only(self):
        p = project_g1_policy(g1_request(), catalog=g1_catalog(),
                              observed_actor="kinoko34077")
        self.assertEqual(p.status, "POLICY_ONLY")
        self.assertEqual(p.reason, "G1_POLICY_MATCHED_NOT_AUTHENTICATED_OR_EXECUTED")
        self.assertEqual(p.operation, "repo.status")
        self.assertEqual(p.backend_candidate, "github_api")
        self.assertEqual(p.effect, "READ_ONLY")
        for flag in ("authenticated", "source_verified", "claim_authority",
                     "github_check_authority", "independently_executed"):
            self.assertFalse(getattr(p, flag))

    def test_g1_fake_actor_catalog_and_effect_gate_denied(self):
        for actor, catalog in (
            ("attacker", g1_catalog()),
            ("kinoko34077", g1_catalog(effect="write", human=True)),
            ("kinoko34077", g1_catalog(effect="write", human=False)),
            ("kinoko34077", {"schema": "bad"}),
        ):
            with self.subTest(actor=actor, catalog=catalog):
                self.assertEqual(
                    project_g1_policy(g1_request(), catalog=catalog,
                                      observed_actor=actor).status,
                    "HOLD",
                )

    def test_g1_duplicate_and_extra_backend_fields_denied(self):
        raw = g1_request()
        duplicate = raw[:-1] + ',"action":"repo.status"}'
        for bad in (duplicate, g1_request(backend="external"),
                    g1_request(actor="kinoko34077"),
                    g1_request(action="arbitrary.script"),
                    g1_request(inputs={"cmd": "sh"}),
                    "[]", "null", "{bad", " " * 8194):
            with self.subTest(bad=bad[:70]):
                self.assertEqual(
                    project_g1_policy(bad, catalog=g1_catalog(),
                                      observed_actor="kinoko34077").status,
                    "HOLD",
                )

    def test_no_effects_network_subprocess_or_file(self):
        with patch.object(subprocess, "run", side_effect=AssertionError("process")), \
             patch.object(urllib.request, "urlopen", side_effect=AssertionError("network")), \
             patch("builtins.open", side_effect=AssertionError("file")):
            a = project_f3c_candidate(
                legacy(), comment_id=6199274701, observed_login="kinoko34077")
            b = project_g1_policy(
                g1_request(), catalog=g1_catalog(), observed_actor="kinoko34077")
        self.assertEqual(a.status, "CANDIDATE_ONLY")
        self.assertEqual(b.status, "POLICY_ONLY")


if __name__ == "__main__":
    unittest.main()
