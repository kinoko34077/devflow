"""M4-A protocol-only principal assertions do not become real runtime authority."""
from __future__ import annotations

from dataclasses import asdict
import json
import subprocess
import unittest
import urllib.request
from unittest.mock import patch

from tools.shared_execution_preadmission import project_untrusted_principal

BASE = {
    "schema": "devflow.shared-principal-preadmission.v1",
    "asserted_kind": "USER_DELEGATED",
    "asserted_principal_id": 123,
    "target_repository_id": 456,
    "request_id": "request-m4a001",
    "request_sha256": "a" * 64,
    "source_sha": "b" * 40,
    "catalog_sha256": "c" * 64,
    "nonce": "f3c-0123456789abcdefghij",
    "issued_at": 1792100000,
    "expires_at": 1792100300,
    "effect": "READ_ONLY",
}


def payload(**changes):
    return json.dumps({**BASE, **changes}, separators=(",", ":"))


class PrincipalPreadmissionTests(unittest.TestCase):
    def test_all_four_asserted_kinds_never_authenticate(self):
        for kind in ("USER_DELEGATED", "APP_INSTALLATION_MACHINE",
                     "ACTIONS_OIDC", "LOCAL_UNVERIFIED"):
            with self.subTest(kind=kind):
                x = project_untrusted_principal(payload(asserted_kind=kind))
                self.assertEqual(x.status, "PROTOCOL_ONLY")
                self.assertEqual(x.reason, "ASSERTIONS_PARSED_NOT_AUTHENTICATED")
                self.assertEqual(x.asserted_kind, kind)
                self.assertEqual(x.asserted_principal_id, 123)
                self.assertEqual(x.target_repository_id, 456)
                self.assertEqual(len(x.assertion_digest), 64)
                for flag in ("authenticated", "issuer_verified", "catalog_verified",
                             "clock_verified", "source_verified",
                             "claim_authority", "github_check_authority",
                             "execution_verified"):
                    self.assertIs(getattr(x, flag), False, flag)

    def test_untrusted_forged_authority_fields_rejected(self):
        for injected in (
            {"authenticated": True}, {"issuer_verified": True},
            {"claim_authority": True}, {"status": "EXECUTED_VERIFIED"},
            {"signature": "attacker"}, {"token": "SECRET"},
            {"secret": "SECRET"}, {"backend": "shell"},
            {"issuer": {"verified": True}},
        ):
            with self.subTest(injected=injected):
                x = project_untrusted_principal(payload(**injected))
                self.assertEqual(x.status, "HOLD")
                self.assertIsNone(x.assertion_digest)

    def test_bad_kinds_not_promoted(self):
        for kind in ("VERIFIED", "GITHUB_OWNER", "ISSUE_AUTHOR", "HUMAN", "REVIEWED", "", 1, True, None):
            with self.subTest(kind=kind):
                x = project_untrusted_principal(payload(asserted_kind=kind))
                self.assertEqual(x.reason, "INVALID_PRINCIPAL_KIND")

    def test_numeric_ids_exact_positive_only(self):
        for field in ("asserted_principal_id", "target_repository_id"):
            for value in (0, -1, "123", True, None, 1.2, [], {}):
                with self.subTest(field=field, value=value):
                    self.assertEqual(project_untrusted_principal(
                        payload(**{field: value})).reason, "INVALID_NUMERIC_IDS")

    def test_readonly_only_and_bounded_claimed_window(self):
        self.assertEqual(project_untrusted_principal(payload(effect="WRITE")).reason,
                         "EFFECT_NOT_SUPPORTED")
        for issued, expires in ((0, 1), (100, 100), (101, 99), (100, 401),
                                (True, 101), (100, True), ("100", 200),
                                (100, "200")):
            with self.subTest(issued=issued, expires=expires):
                x = project_untrusted_principal(
                    payload(issued_at=issued, expires_at=expires))
                self.assertEqual(x.reason, "INVALID_ASSERTED_WINDOW")

    def test_catalog_request_nonce_source_pins(self):
        for mutation in (
            {"request_id": "small"}, {"request_id": True},
            {"nonce": "short"}, {"nonce": "f3c-safe/../../evil"},
            {"source_sha": "HEAD"}, {"source_sha": ["b"]},
            {"catalog_sha256": "c" * 63}, {"catalog_sha256": 0},
            {"request_sha256": "z" * 64}, {"request_sha256": False},
        ):
            with self.subTest(mutation=mutation):
                self.assertEqual(project_untrusted_principal(
                    payload(**mutation)).reason, "INVALID_PINS_OR_REQUEST")

    def test_strict_duplicate_unknown_schema_and_nonobject(self):
        base = payload()
        variants = [
            base[:-1] + ',"effect":"READ_ONLY"}',
            base[:-1] + ',"secret":{"a":1,"a":2}}',
            "{bad", "[]", "null", '"text"',
            json.dumps({"schema": BASE["schema"]}),
            payload(schema="devflow.other.v1"),
            " " * 4097 + base,
        ]
        for candidate in variants:
            with self.subTest(sample=candidate[:40]):
                self.assertEqual(project_untrusted_principal(candidate).status, "HOLD")

    def test_domain_digest_binds_kind_repo_and_expiry(self):
        a = project_untrusted_principal(payload())
        b = project_untrusted_principal(json.dumps(dict(reversed(list(BASE.items())))))
        self.assertEqual(a.assertion_digest, b.assertion_digest)
        for changed in (
            {"asserted_kind": "LOCAL_UNVERIFIED"},
            {"target_repository_id": 457},
            {"asserted_principal_id": 124},
            {"expires_at": 1792100299},
            {"nonce": "f3c-0123456789abcdefghik"},
        ):
            with self.subTest(changed=changed):
                self.assertNotEqual(a.assertion_digest, project_untrusted_principal(
                    payload(**changed)).assertion_digest)

    def test_no_secrets_or_raw_payload_in_receipt(self):
        x = project_untrusted_principal(payload())
        shown = json.dumps(asdict(x))
        self.assertNotIn(BASE["nonce"], shown)
        self.assertNotIn(BASE["request_sha256"], shown)
        self.assertNotIn(BASE["source_sha"], shown)
        self.assertNotIn(BASE["catalog_sha256"], shown)

    def test_has_no_filesystem_subprocess_or_network(self):
        with patch.object(subprocess, "run", side_effect=AssertionError("process")), \
             patch.object(urllib.request, "urlopen", side_effect=AssertionError("network")), \
             patch("builtins.open", side_effect=AssertionError("file")):
            self.assertEqual(project_untrusted_principal(
                payload()).status, "PROTOCOL_ONLY")

    def test_wrong_raw_type_holds_without_exception(self):
        for value in (None, b"{}", {}, [], True):
            self.assertEqual(project_untrusted_principal(value).status, "HOLD")


if __name__ == "__main__":
    unittest.main()
