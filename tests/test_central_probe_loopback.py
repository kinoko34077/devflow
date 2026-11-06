"""F3B loopback trigger regression tests. No nonlocal network or hosted service."""
from __future__ import annotations

import hashlib
import http.client
import json
import queue
import subprocess
import sys
import threading
import unittest

from tools.central_runner_probe import _RECIPE_SHA256
from tools.central_probe_loopback import run_once, sign_test_request

PIN = "a" * 40
KEY = b"F3B-TEST-ONLY-NOT-GITHUB-IDENTITY-KEY-32"
PATH = "/f3b/probe"


class TestLoopbackProbe(unittest.TestCase):
    def setUp(self):
        self.request = {
            "schema_version": "devflow.f3a.fixed-readonly.v1",
            "repository": "kinoko34077/devflow",
            "task_ref": "kinoko34077/devflow#601",
            "source_sha": PIN,
            "recipe_id": "sha256-fixed-v1",
            "recipe_sha256": _RECIPE_SHA256,
            "attempt_id": "local-trigger-1",
            "effect": "READ_ONLY",
        }

    def body(self, changes=None):
        return json.dumps({**self.request, **(changes or {})},
                          separators=(",", ":")).encode()

    def invoke(self, *, body=None, sign=True, path=PATH, method="POST",
               content_type="application/json", length=None):
        ports = queue.Queue(maxsize=1)
        errors = []
        def listener():
            try:
                run_once(expected_source_sha=PIN, test_key=KEY,
                         on_listen=ports.put, timeout_seconds=2.0)
            except Exception as exc:
                errors.append(type(exc).__name__)
        thread = threading.Thread(target=listener)
        thread.start()
        port = ports.get(timeout=3)
        payload = self.body() if body is None else body
        headers = {
            "Content-Type": content_type,
            "X-Devflow-Test-Signature":
                sign_test_request(payload, test_key=KEY) if sign else "0" * 64,
        }
        if length is not None:
            headers["Content-Length"] = str(length)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            status, data = response.status, json.loads(response.read())
        finally:
            conn.close()
            thread.join(timeout=3)
        self.assertFalse(thread.is_alive(), "Loopback server must be one-shot")
        self.assertEqual(errors, [])
        return status, data

    def test_fixed_readonly_job_responds_from_local_http_not_actions(self):
        status, result = self.invoke()
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "LOCAL_READ_ONLY_PROOF")
        self.assertEqual(result["backend"], "standalone-local-process")
        self.assertEqual(result["output_sha256"], hashlib.sha256(
            b"devflow-f3a-public-proof-v1\n").hexdigest())
        self.assertFalse(result["authenticated"])
        self.assertFalse(result["claim_authority"])
        self.assertFalse(result["github_check_authority"])
        self.assertFalse(result["isolated_host_verified"])

    def test_invalid_signature_rejected(self):
        self.assertEqual(
            self.invoke(sign=False),
            (403, {"status": "HOLD", "reason": "TEST_SIGNATURE_DENIED"}),
        )

    def test_wrong_route_fails(self):
        self.assertEqual(self.invoke(path="/admin")[0], 404)

    def test_get_never_runs(self):
        self.assertEqual(self.invoke(method="GET")[0], 405)

    def test_wrong_content_type(self):
        self.assertEqual(self.invoke(content_type="text/plain")[0], 415)

    def test_source_and_arbitrary_task_not_accepted_even_if_signed(self):
        for fields in (
            {"source_sha": "b" * 40},
            {"repository": "kinoko34077/private"},
            {"task_ref": "evil/other#1"},
            {"recipe_id": "arbitrary-python"},
            {"effect": "WRITE"},
        ):
            with self.subTest(fields=fields):
                self.assertEqual(
                    self.invoke(body=self.body(fields)),
                    (422, {"status": "HOLD", "reason": "FIXED_JOB_DENIED"}),
                )

    def test_oversized_payload_rejected(self):
        status, body = self.invoke(body=b"x" * 4097, sign=False)
        self.assertEqual((status, body["reason"]), (413, "SIZE_DENIED"))

    def test_malformed_json_signed_still_denied(self):
        self.assertEqual(
            self.invoke(body=b"{bad json"),
            (422, {"status": "HOLD", "reason": "FIXED_JOB_DENIED"}),
        )

    def test_raw_secret_never_reflected(self):
        secret = b"PRIVATE-SECRET-MUST-NOT-BE-ECHOED"
        payload = self.body()[:-1] + b',"secret":"' + secret + b'"}'
        status, result = self.invoke(body=payload)
        self.assertEqual(status, 422)
        self.assertNotIn(secret.decode(), json.dumps(result))

    def test_bad_config_key_denied_without_listening(self):
        with self.assertRaisesRegex(ValueError, "INVALID_LOCAL_TEST_CONFIG"):
            run_once(expected_source_sha=PIN, test_key=b"short")

    def test_fixed_test_signature_binds_raw_bytes(self):
        first = self.body()
        second = self.body({"attempt_id": "local-trigger-2"})
        self.assertNotEqual(sign_test_request(first, test_key=KEY),
                            sign_test_request(second, test_key=KEY))
        with self.assertRaisesRegex(ValueError, "INVALID_TEST_KEY"):
            sign_test_request(first, test_key=b"short")

    def test_separate_short_lived_python_process_receives_http_request(self):
        script = (
            "from tools.central_probe_loopback import run_once; "
            "run_once(expected_source_sha='" + PIN + "', "
            "test_key=" + repr(KEY) + ", "
            "on_listen=lambda port: print(port,flush=True),timeout_seconds=3)"
        )
        proc = subprocess.Popen([sys.executable, "-c", script],
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True)
        try:
            line = proc.stdout.readline().strip()
            self.assertTrue(line.isdecimal(), line)
            conn = http.client.HTTPConnection("127.0.0.1", int(line), timeout=3)
            payload = self.body()
            conn.request("POST", PATH, body=payload, headers={
                "Content-Type": "application/json",
                "X-Devflow-Test-Signature": sign_test_request(payload, test_key=KEY),
            })
            response = conn.getresponse()
            out = json.loads(response.read())
            conn.close()
            self.assertEqual(response.status, 200)
            self.assertEqual(out["status"], "LOCAL_READ_ONLY_PROOF")
            self.assertFalse(out["authenticated"])
        finally:
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
