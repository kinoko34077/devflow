"""Adversarial tests for G2B FAKE-provider-only trust seam."""
from dataclasses import replace
from hashlib import sha256
import json
import unittest

from tools.safe_dispatch_g2b_fixture import (
    ActorObservation,
    RepositoryObservation,
    StartupPins,
    verify_offline_metadata_fixture,
)

REPO = "kinoko34077/devflow"
HEAD = "a" * 40
COMMIT = "b" * 40


def catalog():
    return {
        "schema": "dispatch-catalog.v1",
        "operator": "kinoko34077",
        "actions": {"repo.status": {
            "repository": REPO, "backend": "github_api",
            "executor": "github.repository_metadata", "ref": "main",
            "effects": "read", "human_gate": False, "inputs": {},
        }},
    }


def request():
    return {
        "schema": "dispatch-request.v1",
        "request_id": "g2b_fixture_0001",
        "repository": REPO,
        "action": "repo.status", "ref": "main", "head_sha": HEAD,
        "inputs": {},
    }


def js(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class FakeProvider:
    def __init__(self):
        self.actor = ActorObservation(79015263, "kinoko34077")
        self.before = RepositoryObservation("1385584542", REPO, "public", "main", True)
        self.after = self.before
        self.head_before = HEAD
        self.head_after = HEAD
        self.metadata_reads = 0
        self.head_reads = 0
        self.actor_reads = 0
        self.error_at = ""

    def current_actor(self):
        self.actor_reads += 1
        if self.error_at == "actor":
            raise RuntimeError("private: DO NOT LEAK")
        return self.actor

    def repository_metadata(self, fixed_repository):
        assert fixed_repository == REPO
        self.metadata_reads += 1
        if self.error_at == "second_metadata" and self.metadata_reads == 2:
            raise RuntimeError("private: DO NOT LEAK")
        return self.before if self.metadata_reads == 1 else self.after

    def branch_head(self, fixed_repository, fixed_ref):
        assert fixed_repository == REPO and fixed_ref == "main"
        self.head_reads += 1
        if self.error_at == "second_head" and self.head_reads == 2:
            raise RuntimeError("private: DO NOT LEAK")
        return self.head_before if self.head_reads == 1 else self.head_after


def fixture_inputs():
    c = js(catalog())
    pins = StartupPins(
        operator_id=79015263, operator_login="kinoko34077",
        repository_id="1385584542", repository=REPO, ref="main",
        catalog_commit_sha=COMMIT,
        catalog_sha256=sha256(c.encode()).hexdigest(),
    )
    return js(request()), c, pins, FakeProvider()


class G2BFixtureTests(unittest.TestCase):
    def call(self, req=None, cat=None, pins=None, provider=None):
        r, c, p, f = fixture_inputs()
        return verify_offline_metadata_fixture(
            r if req is None else req,
            c if cat is None else cat,
            p if pins is None else pins,
            f if provider is None else provider,
        )

    def test_simulation_only_never_claims_real_execution(self):
        result = self.call()
        self.assertEqual(result.status, "SIMULATION_ONLY")
        self.assertEqual(result.reason, "FAKE_PROVIDER_MATCHED_NOT_EXECUTED")
        self.assertEqual(result.request_id, "g2b_fixture_0001")

    def test_identity_is_from_one_fixture_response(self):
        *_, f = fixture_inputs()
        self.call(provider=f)
        self.assertEqual(f.actor_reads, 1)
        self.assertEqual(f.metadata_reads, 2)
        self.assertEqual(f.head_reads, 2)

    def test_private_fixture_supported_but_not_proof(self):
        r, c, p, f = fixture_inputs()
        f.before = f.after = replace(f.before, visibility="private")
        self.assertEqual(self.call(provider=f).status, "SIMULATION_ONLY")

    def test_actor_id_change_denied(self):
        r, c, p, f = fixture_inputs()
        f.actor = replace(f.actor, id=1234)
        self.assertEqual(self.call(provider=f).reason, "ACTOR_MISMATCH")

    def test_actor_login_change_denied(self):
        r, c, p, f = fixture_inputs()
        f.actor = replace(f.actor, login="attacker")
        self.assertEqual(self.call(provider=f).reason, "ACTOR_MISMATCH")

    def test_actor_id_boolean_denied(self):
        r, c, p, f = fixture_inputs()
        f.actor = replace(f.actor, id=True)
        self.assertEqual(self.call(provider=f).reason, "ACTOR_MISMATCH")

    def test_repo_id_spoof_denied(self):
        r, c, p, f = fixture_inputs()
        f.before = replace(f.before, id="9999")
        self.assertEqual(self.call(provider=f).reason, "TARGET_OR_PERMISSION_MISMATCH")

    def test_repo_name_spoof_denied(self):
        r, c, p, f = fixture_inputs()
        f.before = replace(f.before, full_name="other/repository")
        self.assertEqual(self.call(provider=f).reason, "TARGET_OR_PERMISSION_MISMATCH")

    def test_denied_without_read_permission(self):
        r, c, p, f = fixture_inputs()
        f.before = replace(f.before, can_read=False)
        self.assertEqual(self.call(provider=f).reason, "TARGET_OR_PERMISSION_MISMATCH")

    def test_boolean_permission_must_be_boolean(self):
        r, c, p, f = fixture_inputs()
        f.before = replace(f.before, can_read=1)
        self.assertEqual(self.call(provider=f).reason, "TARGET_OR_PERMISSION_MISMATCH")

    def test_unexpected_visibility_denied(self):
        r, c, p, f = fixture_inputs()
        f.before = replace(f.before, visibility="internal")
        self.assertEqual(self.call(provider=f).reason, "TARGET_OR_PERMISSION_MISMATCH")

    def test_default_branch_mismatch_denied(self):
        r, c, p, f = fixture_inputs()
        f.before = replace(f.before, default_branch="release")
        self.assertEqual(self.call(provider=f).reason, "TARGET_OR_PERMISSION_MISMATCH")

    def test_head_mismatch_to_request_denied_by_g2a(self):
        r, c, p, f = fixture_inputs()
        f.head_before = "c" * 40
        self.assertEqual(self.call(provider=f).reason, "G1_G2A_DID_NOT_ADMIT")

    def test_head_moves_between_reads(self):
        r, c, p, f = fixture_inputs()
        f.head_after = "c" * 40
        self.assertEqual(self.call(provider=f).reason, "STALE_HEAD")

    def test_invalid_second_metadata_denied(self):
        r, c, p, f = fixture_inputs()
        f.after = replace(f.after, id="9999")
        self.assertEqual(self.call(provider=f).reason, "TARGET_CHANGED")

    def test_invalid_head_shape_denied(self):
        r, c, p, f = fixture_inputs()
        f.head_before = "not-a-sha"
        self.assertEqual(self.call(provider=f).reason, "INVALID_HEAD_OBSERVATION")

    def test_trusted_catalog_byte_tamper_denied(self):
        r, c, p, f = fixture_inputs()
        c = c.replace("repo.status", "repo.status2")
        self.assertEqual(self.call(cat=c).reason, "CATALOG_DIGEST_MISMATCH")

    def test_pin_digest_shape_or_value_denied(self):
        r, c, p, f = fixture_inputs()
        self.assertEqual(self.call(pins=replace(p, catalog_sha256="bad")).reason, "INVALID_STARTUP_PINS")
        self.assertEqual(self.call(pins=replace(p, catalog_sha256="f" * 64)).reason, "CATALOG_DIGEST_MISMATCH")

    def test_commit_sha_shape_denied(self):
        r, c, p, f = fixture_inputs()
        self.assertEqual(self.call(pins=replace(p, catalog_commit_sha="main")).reason, "INVALID_STARTUP_PINS")

    def test_request_backend_override_denied_by_g1(self):
        r, c, p, f = fixture_inputs()
        req = js({**request(), "backend": "github_actions"})
        self.assertEqual(self.call(req=req).reason, "G1_G2A_DID_NOT_ADMIT")

    def test_denied_actor_never_touches_target(self):
        r, c, p, f = fixture_inputs()
        f.actor = replace(f.actor, id=1234)
        self.assertEqual(self.call(provider=f).reason, "ACTOR_MISMATCH")
        self.assertEqual(f.actor_reads, 1)
        self.assertEqual(f.metadata_reads, 0)
        self.assertEqual(f.head_reads, 0)

    def test_denied_policy_never_touches_target(self):
        r, c, p, f = fixture_inputs()
        malicious = js({**request(), "backend": "github_actions"})
        self.assertEqual(self.call(req=malicious, provider=f).reason,
                         "G1_G2A_DID_NOT_ADMIT")
        self.assertEqual(f.metadata_reads, 0)
        self.assertEqual(f.head_reads, 0)

    def test_g1_admitted_unallowlisted_handler_never_touches_target(self):
        r, c, p, f = fixture_inputs()
        changed = catalog()
        changed["actions"]["repo.status"]["executor"] = "github.repository_read_other"
        changed_cat = js(changed)
        pinned = replace(p, catalog_sha256=sha256(changed_cat.encode()).hexdigest())
        self.assertEqual(self.call(cat=changed_cat, pins=pinned, provider=f).reason,
                         "NON_ALLOWLISTED_HANDLER")
        self.assertEqual(f.metadata_reads, 0)
        self.assertEqual(f.head_reads, 0)

    def test_rejected_write_catalog_never_touches_target(self):
        r, c, p, f = fixture_inputs()
        changed = catalog()
        changed["actions"]["repo.status"]["effects"] = "write"
        changed["actions"]["repo.status"]["human_gate"] = True
        raw = js(changed)
        pin = replace(p, catalog_sha256=sha256(raw.encode()).hexdigest())
        self.assertEqual(self.call(cat=raw, pins=pin, provider=f).reason,
                         "G1_G2A_DID_NOT_ADMIT")
        self.assertEqual(f.metadata_reads, 0)
        self.assertEqual(f.head_reads, 0)

    def test_request_unknown_action_denied_by_g1(self):
        r, c, p, f = fixture_inputs()
        req = js({**request(), "action": "run.shell"})
        self.assertEqual(self.call(req=req).reason, "G1_G2A_DID_NOT_ADMIT")

    def test_request_duplicate_key_denied(self):
        r, c, p, f = fixture_inputs()
        req = r[:-1] + ',"schema":"dispatch-request.v1"}'
        self.assertEqual(self.call(req=req).reason, "INVALID_OR_DUPLICATE_JSON")

    def test_catalog_duplicate_key_denied_even_with_matching_digest(self):
        r, c, p, f = fixture_inputs()
        c = c[:-1] + ',"schema":"dispatch-catalog.v1"}'
        new_pins = replace(p, catalog_sha256=sha256(c.encode()).hexdigest())
        self.assertEqual(self.call(cat=c, pins=new_pins).reason, "INVALID_OR_DUPLICATE_JSON")

    def test_catalog_write_not_read_denied(self):
        r, c, p, f = fixture_inputs()
        ca = catalog()
        ca["actions"]["repo.status"]["effects"] = "write"
        ca["actions"]["repo.status"]["human_gate"] = True
        c = js(ca)
        pins = replace(p, catalog_sha256=sha256(c.encode()).hexdigest())
        self.assertEqual(self.call(cat=c, pins=pins).reason, "G1_G2A_DID_NOT_ADMIT")

    def test_provider_errors_hide_details(self):
        for stage, expected in (("actor", "FIXTURE_OBSERVATION_FAILED"),
                                ("second_metadata", "SECOND_OBSERVATION_UNKNOWN"),
                                ("second_head", "SECOND_OBSERVATION_UNKNOWN")):
            with self.subTest(stage=stage):
                r, c, p, f = fixture_inputs()
                f.error_at = stage
                outcome = self.call(provider=f)
                self.assertEqual(outcome.reason, expected)
                self.assertNotIn("private:", repr(outcome))

    def test_after_read_permission_revoked(self):
        r, c, p, f = fixture_inputs()
        f.after = replace(f.after, can_read=False)
        self.assertEqual(self.call(provider=f).reason, "TARGET_CHANGED")

    def test_no_replay_or_real_actor_proof_claimed(self):
        r = self.call()
        self.assertNotIn(r.status, {"ADMITTED", "RUNNING", "SUCCEEDED", "RESERVED_NOT_EXECUTED"})
        self.assertEqual(r.catalog_sha256, fixture_inputs()[2].catalog_sha256)


if __name__ == "__main__":
    unittest.main()
