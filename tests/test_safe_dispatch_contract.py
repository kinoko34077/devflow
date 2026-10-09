"""Offline negative/positive tests for G1 ChatGPT-safe dispatch admission."""
import copy
import json
import unittest

from tools.safe_dispatch_contract import (
    CATALOG_SCHEMA,
    REQUEST_SCHEMA,
    admit_dispatch,
    parse_json_object,
)

SHA = "a" * 40
REPO = "kinoko34077/devflow"


def catalog():
    return {
        "schema": CATALOG_SCHEMA,
        "operator": "kinoko34077",
        "actions": {
            "repo.status": {
                "repository": REPO,
                "backend": "github_api",
                "executor": "github.repository_metadata",
                "ref": "main",
                "effects": "read",
                "human_gate": False,
                "inputs": {},
            },
            "ci.verify": {
                "repository": REPO,
                "backend": "github_actions",
                "executor": ".github/workflows/required.yml",
                "ref": "main",
                "effects": "read",
                "human_gate": False,
                "inputs": {
                    "mode": {
                        "type": "choice",
                        "required": True,
                        "choices": ["verify", "inspect"],
                    },
                    "details": {"type": "boolean", "required": False},
                    "limit": {
                        "type": "integer",
                        "required": False,
                        "minimum": 0,
                        "maximum": 20,
                    },
                },
            },
            "sync.reconcile": {
                "repository": REPO,
                "backend": "github_actions",
                "executor": ".github/workflows/project-sync.yml",
                "ref": "main",
                "effects": "write",
                "human_gate": True,
                "inputs": {},
            },
        },
    }


def request(action="repo.status", **overrides):
    base = {
        "schema": REQUEST_SCHEMA,
        "request_id": "req_g1_00000001",
        "repository": REPO,
        "action": action,
        "ref": "main",
        "head_sha": SHA,
        "inputs": {"mode": "verify"} if action == "ci.verify" else {},
    }
    base.update(overrides)
    return base


def run(req=None, cat=None, actor="kinoko34077"):
    return admit_dispatch(request() if req is None else req, catalog() if cat is None else cat, verified_actor=actor)


class PositiveTests(unittest.TestCase):
    def test_read_only_direct_api_request_admitted_but_not_executed(self):
        result = run()
        self.assertEqual(result.status, "ADMITTED")
        self.assertEqual(result.reason, "POLICY_ADMITTED_NOT_EXECUTED")
        self.assertEqual(result.backend, "github_api")
        self.assertEqual(result.executor, "github.repository_metadata")
        self.assertEqual(result.head_sha, SHA)

    def test_pinned_reviewed_workflow_allowed(self):
        result = run(request("ci.verify"))
        self.assertEqual(result.status, "ADMITTED")
        self.assertEqual(result.backend, "github_actions")
        self.assertEqual(result.executor, ".github/workflows/required.yml")

    def test_valid_optional_inputs(self):
        result = run(request("ci.verify", inputs={"mode": "verify", "details": False, "limit": 0}))
        self.assertEqual(result.status, "ADMITTED")

    def test_write_reaches_human_gate_not_execution(self):
        result = run(request("sync.reconcile"))
        self.assertEqual(result.status, "NEEDS_HUMAN")
        self.assertEqual(result.reason, "HUMAN_GATE_REQUIRED")

    def test_inputs_are_not_interpolated_or_returned_as_shell(self):
        result = run(request("ci.verify"))
        self.assertEqual(set(vars(result)), {
            "status", "reason", "request_id", "repository", "action",
            "backend", "executor", "ref", "head_sha",
        })


class RequestRejectTests(unittest.TestCase):
    def assert_denied(self, req, reason=None, cat=None, actor="kinoko34077"):
        result = run(req, cat=cat, actor=actor)
        self.assertEqual(result.status, "DENIED")
        if reason:
            self.assertEqual(result.reason, reason)
        self.assertIsNone(result.executor)

    def test_unknown_action_fails_closed(self):
        self.assert_denied(request(action="gh.arbitrary"), "UNKNOWN_ACTION")

    def test_action_name_shell_metacharacters_rejected(self):
        self.assert_denied(request(action="ci.verify; echo TOKEN"), "INVALID_ACTION")

    def test_request_cannot_override_executor_or_backend(self):
        req = request(backend="github_api")
        self.assert_denied(req, "INVALID_REQUEST_SCHEMA")
        req = request(executor=".github/workflows/arbitrary.yml")
        self.assert_denied(req, "INVALID_REQUEST_SCHEMA")

    def test_claimed_actor_in_request_is_never_authority(self):
        self.assert_denied(request(actor="kinoko34077"), "INVALID_REQUEST_SCHEMA")
        self.assert_denied(request(), "UNTRUSTED_ACTOR", actor="attacker")

    def test_repository_is_catalog_bound(self):
        self.assert_denied(request(repository="kinoko34077/other"), "REPOSITORY_NOT_ALLOWED")
        self.assert_denied(request(repository="../devflow"), "INVALID_REPOSITORY")

    def test_strict_head_and_ref(self):
        self.assert_denied(request(ref="feature/head"), "REF_OR_HEAD_INVALID")
        self.assert_denied(request(head_sha="main"), "REF_OR_HEAD_INVALID")
        self.assert_denied(request(head_sha="A" * 40), "REF_OR_HEAD_INVALID")

    def test_boolean_is_not_integer(self):
        self.assert_denied(request("ci.verify", inputs={"mode": "verify", "limit": True}), "INVALID_INPUTS")

    def test_required_input_missing(self):
        self.assert_denied(request("ci.verify", inputs={}), "INVALID_INPUTS")

    def test_unknown_input_or_bad_choice(self):
        self.assert_denied(request("ci.verify", inputs={"mode": "verify", "run": "shell"}), "INVALID_INPUTS")
        self.assert_denied(request("ci.verify", inputs={"mode": "rm -rf /"}), "INVALID_INPUTS")

    def test_out_of_range_input_and_bad_boolean(self):
        self.assert_denied(request("ci.verify", inputs={"mode": "verify", "limit": 999}), "INVALID_INPUTS")
        self.assert_denied(request("ci.verify", inputs={"mode": "verify", "details": "true"}), "INVALID_INPUTS")

    def test_invalid_schema_and_request_id(self):
        self.assert_denied(request(schema="dispatch-request.v2"), "INVALID_REQUEST_SCHEMA")
        self.assert_denied(request(request_id="!"), "INVALID_REQUEST_ID")

    def test_non_dict_and_unknown_key(self):
        self.assert_denied([], "INVALID_REQUEST_SCHEMA")
        self.assert_denied(request(secret="hello"), "INVALID_REQUEST_SCHEMA")


class CatalogRejectTests(unittest.TestCase):
    def assert_bad_catalog(self, mutate):
        item = catalog()
        mutate(item)
        result = run(cat=item)
        self.assertEqual(result.status, "DENIED")
        self.assertEqual(result.reason, "INVALID_TRUSTED_CATALOG")
        self.assertIsNone(result.executor)

    def test_trusted_catalog_version_fails_closed(self):
        self.assert_bad_catalog(lambda x: x.update(schema="dispatch-catalog.v2"))

    def test_unknown_catalog_fields_rejected(self):
        self.assert_bad_catalog(lambda x: x.update(allow_all=True))

    def test_unsafe_workflow_path_rejected(self):
        self.assert_bad_catalog(lambda x: x["actions"]["ci.verify"].update(executor="../../bad.yml"))

    def test_unknown_backend_rejected(self):
        self.assert_bad_catalog(lambda x: x["actions"]["repo.status"].update(backend="shell"))

    def test_unreviewed_write_without_gate_is_invalid(self):
        self.assert_bad_catalog(lambda x: x["actions"]["sync.reconcile"].update(human_gate=False))

    def test_undeclared_executor_options_rejected(self):
        self.assert_bad_catalog(lambda x: x["actions"]["repo.status"].update(url="https://attacker.example"))

    def test_bad_choice_schema_rejected(self):
        def mutate(x):
            x["actions"]["ci.verify"]["inputs"]["mode"]["choices"] = ["verify", "verify"]
        self.assert_bad_catalog(mutate)

    def test_unsafe_schema_type_fails_closed_not_exception(self):
        def mutate(x):
            x["actions"]["ci.verify"]["inputs"]["mode"]["type"] = []
        self.assert_bad_catalog(mutate)

    def test_trusted_operator_must_be_structurally_valid(self):
        self.assert_bad_catalog(lambda x: x.update(operator="someone\nelse"))


class JsonBoundariesTests(unittest.TestCase):
    def test_parses_valid_object(self):
        payload = json.dumps(request(), separators=(",", ":"))
        self.assertEqual(parse_json_object(payload), request())

    def test_rejects_duplicate_top_level_and_nested_keys(self):
        for text in ('{"x":1,"x":2}', '{"outer":{"a":1,"a":2}}'):
            with self.assertRaisesRegex(ValueError, "DUPLICATE_JSON_KEY"):
                parse_json_object(text)

    def test_rejects_oversize_invalid_scalar_and_nan(self):
        for text in (" " * 8193, "[]", '{"x":NaN}', '{"x":Infinity}', "not json"):
            with self.subTest(text=text[:15]), self.assertRaises(ValueError):
                parse_json_object(text)

    def test_bool_never_passes_integer_schema(self):
        cat = catalog()
        req = request("ci.verify", inputs={"mode": "verify", "limit": True})
        self.assertEqual(run(req, cat=cat).status, "DENIED")


if __name__ == "__main__":
    unittest.main()
