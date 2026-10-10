"""Offline G2A G1-integrated preflight and SQLite reservation negatives."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from tools.safe_dispatch_contract import CATALOG_SCHEMA, REQUEST_SCHEMA
from tools.safe_dispatch_g2a import (
    ObservedReadContext,
    ReadPreflight,
    SQLiteReservationPrototype,
    inspect_read_request,
)

REPO = "kinoko34077/devflow"
HEAD = "a" * 40
CATALOG_SHA = "b" * 40


def setup():
    catalog = {
        "schema": CATALOG_SCHEMA, "operator": "kinoko34077",
        "actions": {
            "repo.status": {
                "repository": REPO, "backend": "github_api",
                "executor": "github.repository_metadata", "ref": "main",
                "effects": "read", "human_gate": False, "inputs": {},
            },
        },
    }
    request = {
        "schema": REQUEST_SCHEMA, "request_id": "req_g2a_0001",
        "repository": REPO, "action": "repo.status",
        "ref": "main", "head_sha": HEAD, "inputs": {},
    }
    observation = ObservedReadContext(
        principal_id=79015263, actor_login="kinoko34077",
        repository=REPO, default_branch="main", actual_head_sha=HEAD,
        visibility="public", can_read=True, handler="github.repository_metadata",
    )
    return request, catalog, observation


def assess(request=None, catalog=None, obs=None, sha=CATALOG_SHA):
    r, c, o = setup()
    return inspect_read_request(
        r if request is None else request,
        c if catalog is None else catalog,
        catalog_commit_sha=sha,
        observation=o if obs is None else obs,
    )


class PreflightTests(unittest.TestCase):
    def test_integrated_g1_valid_read_only_passes_without_executing(self):
        result = assess()
        self.assertEqual(result.status, "PREFLIGHT_ONLY")
        self.assertEqual(result.reason, "READ_CHECKS_MATCH_NOT_EXECUTED")
        self.assertEqual(result.request_id, "req_g2a_0001")
        self.assertEqual(len(result.request_digest), 64)

    def test_untrusted_actor_denied_via_actual_g1(self):
        r, c, o = setup()
        self.assertEqual(assess(obs=replace(o, actor_login="intruder")).reason, "G1_DID_NOT_ADMIT")

    def test_actor_id_bool_rejected(self):
        r, c, o = setup()
        self.assertEqual(assess(obs=replace(o, principal_id=True)).reason, "INVALID_OBSERVATION")

    def test_catalog_commit_pin_required(self):
        self.assertEqual(assess(sha="main").reason, "CATALOG_COMMIT_NOT_PINNED")

    def test_malformed_catalog_denied_through_g1(self):
        r, c, o = setup()
        c["actions"]["repo.status"]["effects"] = "write"
        self.assertEqual(assess(catalog=c).reason, "G1_DID_NOT_ADMIT")

    def test_human_gated_denied_through_g1(self):
        r, c, o = setup()
        c["actions"]["repo.status"]["human_gate"] = True
        self.assertEqual(assess(catalog=c).reason, "G1_DID_NOT_ADMIT")

    def test_action_backend_not_allowlisted(self):
        r, c, o = setup()
        c["actions"]["repo.status"].update({
            "backend": "github_actions", "executor": ".github/workflows/required.yml",
            "reviewed_workflow_sha": "c" * 40,
        })
        self.assertEqual(assess(catalog=c).reason, "NON_ALLOWLISTED_HANDLER")

    def test_unapproved_api_handler_denied(self):
        r, c, o = setup()
        c["actions"]["repo.status"]["executor"] = "github.issues.write"
        self.assertEqual(assess(catalog=c).reason, "NON_ALLOWLISTED_HANDLER")

    def test_repo_mismatch(self):
        r, c, o = setup()
        self.assertEqual(assess(obs=replace(o, repository="somebody/repo")).reason, "REPOSITORY_MISMATCH")

    def test_ref_mismatch(self):
        r, c, o = setup()
        self.assertEqual(assess(obs=replace(o, default_branch="dev")).reason, "BRANCH_MISMATCH")

    def test_head_movement(self):
        r, c, o = setup()
        self.assertEqual(assess(obs=replace(o, actual_head_sha="c" * 40)).reason, "HEAD_MISMATCH")

    def test_private_without_pull_permission(self):
        r, c, o = setup()
        self.assertEqual(assess(obs=replace(o, visibility="private", can_read=False)).reason,
                         "CONNECTOR_READ_NOT_PROVEN")

    def test_private_permission_snapshot_not_proof_of_private_run(self):
        r, c, o = setup()
        self.assertEqual(assess(obs=replace(o, visibility="private")).status, "PREFLIGHT_ONLY")

    def test_unknown_visibility_and_capability(self):
        r, c, o = setup()
        self.assertEqual(assess(obs=replace(o, visibility="internal")).status, "BLOCKED")
        self.assertEqual(assess(obs=replace(o, handler="github.workflow_dispatch")).status, "BLOCKED")

    def test_reject_request_injected_backend_actor_and_shell(self):
        r, c, o = setup()
        for key, value in (("actor", "kinoko34077"), ("backend", "github_api"),
                           ("shell", "echo unsafe")):
            with self.subTest(key=key):
                self.assertEqual(assess(request={**r, key: value}).reason, "G1_DID_NOT_ADMIT")

    def test_ref_and_request_head_cannot_be_self_reported(self):
        r, c, o = setup()
        self.assertEqual(assess(request={**r, "head_sha": "d" * 40}).reason, "HEAD_MISMATCH")

    def test_digest_rejects_non_json_and_nan(self):
        r, c, o = setup()
        self.assertEqual(assess(request={**r, "inputs": {"limit": float("nan")}}).reason,
                         "INVALID_REQUEST_DIGEST")

    def test_untrusted_unknown_input_denied_by_g1(self):
        r, c, o = setup()
        self.assertEqual(assess(request={**r, "inputs": {"evil": "shell"}}).reason,
                         "G1_DID_NOT_ADMIT")

    def test_nonmatching_repo_request_denied(self):
        r, c, o = setup()
        self.assertEqual(assess(request={**r, "repository": "other/repo"}).reason,
                         "G1_DID_NOT_ADMIT")

    def test_reject_non_observation_object(self):
        self.assertEqual(assess(obs={"actor_login": "kinoko34077"}).reason, "INVALID_OBSERVATION")


class ReservationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.filename = Path(tmp.name) / "reservations.db"
        self.store = SQLiteReservationPrototype(self.filename)
        self.proof = assess()

    def test_reserve_once_and_replay_never_releases(self):
        self.assertEqual(self.store.reserve(self.proof).status, "RESERVED_NOT_EXECUTED")
        self.assertEqual(SQLiteReservationPrototype(self.filename).reserve(self.proof).status,
                         "REPLAY_LOCKED")

    def test_conflicting_payload_fails_closed(self):
        self.store.reserve(self.proof)
        forged = replace(self.proof, request_digest="c" * 64)
        self.assertEqual(self.store.reserve(forged).status, "REQUEST_ID_CONFLICT")

    def test_catalog_change_same_id_conflicts(self):
        self.store.reserve(self.proof)
        self.assertEqual(
            self.store.reserve(replace(self.proof, catalog_commit_sha="c" * 40)).status,
            "REQUEST_ID_CONFLICT",
        )

    def test_repository_change_same_id_conflicts(self):
        self.store.reserve(self.proof)
        self.assertEqual(
            self.store.reserve(replace(self.proof, repository="other/repo")).status,
            "REQUEST_ID_CONFLICT",
        )

    def test_denied_cannot_reserve(self):
        self.assertEqual(self.store.reserve(assess(sha="bad")).status, "DENIED")

    def test_malformed_proof_rejected(self):
        self.assertEqual(self.store.reserve(replace(self.proof, request_digest="bad")).status,
                         "DENIED")
        self.assertEqual(self.store.reserve(replace(self.proof, principal_id=True)).status,
                         "DENIED")
        self.assertEqual(self.store.reserve({"status": "PREFLIGHT_ONLY"}).status, "DENIED")

    def test_concurrent_connections_one_winner(self):
        stores = [SQLiteReservationPrototype(self.filename) for _ in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda x: x.reserve(self.proof).status, stores))
        self.assertCountEqual(outcomes, ["RESERVED_NOT_EXECUTED", "REPLAY_LOCKED"])

    def test_principal_id_namespaces_different_actor_reservations(self):
        self.store.reserve(self.proof)
        other = replace(self.proof, principal_id=99999)
        self.assertEqual(self.store.reserve(other).status, "RESERVED_NOT_EXECUTED")


if __name__ == "__main__":
    unittest.main()
