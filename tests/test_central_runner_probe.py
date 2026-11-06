"""Standalone fixed CPU proof does NOT authorize any GitHub or Claim operation."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from dataclasses import asdict

from tools.central_runner_probe import (
    ProbeDenied, _PAYLOAD, _RECIPE_SHA256, run_fixed_probe,
)

PIN = "a" * 40


class StandaloneFixedProbeTests(unittest.TestCase):
    def setUp(self):
        self.request = {
            "schema_version": "devflow.f3a.fixed-readonly.v1",
            "repository": "kinoko34077/devflow",
            "task_ref": "kinoko34077/devflow#601",
            "source_sha": PIN,
            "recipe_id": "sha256-fixed-v1",
            "recipe_sha256": _RECIPE_SHA256,
            "attempt_id": "probe-1",
            "effect": "READ_ONLY",
        }

    def body(self, obj=None):
        return json.dumps(self.request if obj is None else obj,
                          separators=(",", ":")).encode()

    def denial(self, expected, data, pin=PIN):
        with self.assertRaises(ProbeDenied) as cm:
            run_fixed_probe(data, expected_source_sha=pin)
        self.assertEqual(str(cm.exception), expected)

    def test_cpu_hash_is_computed_for_exact_public_fixture(self):
        result = run_fixed_probe(self.body(), expected_source_sha=PIN)
        self.assertEqual(result.status, "LOCAL_READ_ONLY_PROOF")
        self.assertEqual(result.output_sha256,
                         hashlib.sha256(_PAYLOAD).hexdigest())
        self.assertEqual(result.backend, "standalone-local-process")
        for key in ("simulated", "authenticated", "source_verified",
                    "isolated_host_verified", "claim_authority",
                    "github_check_authority"):
            self.assertFalse(getattr(result, key))

    def test_run_as_own_python_process_no_actions_scheduler_call(self):
        command = [sys.executable, "-m", "tools.central_runner_probe",
                   "--expected-source-sha", PIN]
        out = subprocess.run(command, input=self.body(), capture_output=True,
                             timeout=8, check=False)
        self.assertEqual(out.returncode, 0, out.stderr[:250])
        result = json.loads(out.stdout)
        self.assertEqual(result["output_sha256"],
                         hashlib.sha256(_PAYLOAD).hexdigest())
        self.assertFalse(result["claim_authority"])
        self.assertFalse(result["github_check_authority"])
        self.assertNotIn("token", out.stdout.decode().lower())

    def test_process_refuses_forged_source_pin(self):
        command = [sys.executable, "-m", "tools.central_runner_probe",
                   "--expected-source-sha", PIN]
        obj = dict(self.request, source_sha="b" * 40)
        out = subprocess.run(command, input=self.body(obj), capture_output=True,
                             timeout=8, check=False)
        self.assertEqual(out.returncode, 2)
        self.assertEqual(json.loads(out.stdout)["reason"],
                         "FIXED_RECIPE_OR_SOURCE_DENIED")

    def test_other_repo_task_recipe_or_effect_denied(self):
        for change in (
            {"repository": "kinoko34077/private"},
            {"task_ref": "kinoko34077/private#22"},
            {"task_ref": "kinoko34077/devflow#541"},
            {"recipe_id": "shell-script"},
            {"recipe_sha256": "f" * 64},
            {"effect": "WRITE"},
            {"attempt_id": "../../secret"},
            {"source_sha": "b" * 40},
            {"repository": True},
            {"source_sha": ["a"]},
        ):
            with self.subTest(change=change):
                self.denial("FIXED_RECIPE_OR_SOURCE_DENIED",
                            self.body({**self.request, **change}))

    def test_unknown_json_keys_and_oversize_fail(self):
        self.denial("INVALID_REQUEST_SHAPE",
                    self.body({**self.request, "command": "curl evil"}))
        self.denial("INPUT_SIZE_DENIED", b"x" * 4097)
        self.denial("INVALID_JSON", b"{bad json}")
        self.denial("INVALID_JSON", b"\xff")
        self.denial("INVALID_REQUEST_SHAPE", b"null")
        self.denial("INVALID_SOURCE_PIN", self.body(), pin="latest")

    def test_output_never_includes_arbitrary_payload_or_secret(self):
        secret = "NEVER-LEAK-PRIVATE-TOKEN-EXAMPLE"
        obj = dict(self.request, secret=secret)
        command = [sys.executable, "-m", "tools.central_runner_probe",
                   "--expected-source-sha", PIN]
        out = subprocess.run(command, input=self.body(obj), capture_output=True,
                             timeout=8, check=False)
        self.assertEqual(out.returncode, 2)
        self.assertNotIn(secret.encode(), out.stdout + out.stderr)

    def test_digest_deterministic_and_request_bound(self):
        first = run_fixed_probe(self.body(), expected_source_sha=PIN)
        again = run_fixed_probe(self.body(), expected_source_sha=PIN)
        self.assertEqual(asdict(first), asdict(again))
        obj = dict(self.request, attempt_id="probe-2")
        changed = run_fixed_probe(self.body(obj), expected_source_sha=PIN)
        self.assertNotEqual(first.request_sha256, changed.request_sha256)
        self.assertEqual(first.output_sha256, changed.output_sha256)

    def test_hash_cannot_turn_into_production_auth(self):
        proof = run_fixed_probe(self.body(), expected_source_sha=PIN)
        self.assertFalse(proof.authenticated or proof.source_verified)
        self.assertFalse(proof.claim_authority or proof.github_check_authority)


if __name__ == "__main__":
    unittest.main()
