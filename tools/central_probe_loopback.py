"""F3B ephemeral *loopback only* HTTP trigger for the F3A public fixed CPU proof.

TEST-ONLY HMAC is not GitHub/App/OIDC authentication; request and output are NOT
production authority. Never bind to a public address, persist a credential,
accept arbitrary recipes or let this handler grant a Claim/GitHub check.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import socket
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer

from tools.central_runner_probe import ProbeDenied, run_fixed_probe

_MAX_BODY = 4096
_PATH = "/f3b/probe"
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_DOMAIN = b"devflow-f3b-local-loopback-test-v1\n"


def sign_test_request(body: bytes, *, test_key: bytes) -> str:
    """Local fixture helper, never a real GitHub principal or bearer token."""
    if type(test_key) is not bytes or len(test_key) < 32:
        raise ValueError("INVALID_TEST_KEY")
    if type(body) is not bytes or len(body) > _MAX_BODY:
        raise ValueError("INVALID_TEST_BODY")
    return hmac.new(test_key, _DOMAIN + body, hashlib.sha256).hexdigest()


def make_test_loopback_server(*, expected_source_sha: str,
                              test_key: bytes, timeout_seconds: float = 3.0) -> HTTPServer:
    """Return a one-shot 127.0.0.1-only server; caller MUST handle and close it."""
    if (type(expected_source_sha) is not str or
            _SHA1.fullmatch(expected_source_sha) is None or
            type(test_key) is not bytes or len(test_key) < 32 or
            type(timeout_seconds) not in (float, int) or
            not 0.1 <= timeout_seconds <= 5.0):
        raise ValueError("INVALID_LOCAL_TEST_CONFIG")
    trusted_key = bytes(test_key)
    pinned_sha = expected_source_sha

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # No body, signature, host address, private path or token logs.
            return

        def _reply(self, status, obj):
            raw = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("ascii")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self._reply(405, {"status": "HOLD", "reason": "METHOD_DENIED"})

        def do_POST(self):
            if self.path != _PATH:
                return self._reply(404, {"status": "HOLD", "reason": "ROUTE_DENIED"})
            if self.headers.get("Content-Type") != "application/json":
                return self._reply(415, {"status": "HOLD", "reason": "TYPE_DENIED"})
            raw_length = self.headers.get("Content-Length", "")
            if not raw_length.isascii() or not raw_length.isdecimal():
                return self._reply(411, {"status": "HOLD", "reason": "SIZE_DENIED"})
            length = int(raw_length)
            if length < 1 or length > _MAX_BODY:
                return self._reply(413, {"status": "HOLD", "reason": "SIZE_DENIED"})
            signature = self.headers.get("X-Devflow-Test-Signature", "")
            if _HEX.fullmatch(signature) is None:
                return self._reply(403, {"status": "HOLD", "reason": "TEST_SIGNATURE_DENIED"})
            try:
                body = self.rfile.read(length)
            except (OSError, socket.timeout):
                return self._reply(408, {"status": "HOLD", "reason": "INPUT_TIMEOUT"})
            if len(body) != length:
                return self._reply(400, {"status": "HOLD", "reason": "BODY_TRUNCATED"})
            expected = sign_test_request(body, test_key=trusted_key)
            if not hmac.compare_digest(signature, expected):
                return self._reply(403, {"status": "HOLD", "reason": "TEST_SIGNATURE_DENIED"})
            try:
                result = run_fixed_probe(body, expected_source_sha=pinned_sha)
            except ProbeDenied:
                return self._reply(422, {"status": "HOLD", "reason": "FIXED_JOB_DENIED"})
            return self._reply(200, asdict(result))

    class LoopbackHTTPServer(HTTPServer):
        allow_reuse_address = False

    server = LoopbackHTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = float(timeout_seconds)
    server.socket.settimeout(float(timeout_seconds))
    return server


def run_once(*, expected_source_sha: str, test_key: bytes,
             on_listen=None, timeout_seconds: float = 3.0) -> None:
    """Serves at most one local HTTP request, never a resident service.

    on_listen is a test coordination callback, NOT a GitHub webhook callback.
    """
    with make_test_loopback_server(
        expected_source_sha=expected_source_sha, test_key=test_key,
        timeout_seconds=timeout_seconds,
    ) as server:
        if on_listen is not None:
            on_listen(server.server_address[1])
        server.handle_request()
