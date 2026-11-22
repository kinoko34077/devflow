#!/usr/bin/env python3
"""Read-only, isolated Codex app-server MCP recovery diagnostic.

Reproduces initial startup failure and post-initialization transport loss.
It starts its own app-server with a temporary CODEX_HOME and a mock MCP server.
It never calls a model, changes user credentials, or touches an existing chat.

Usage:
  python tools/diagnostics/codex_mcp_recovery_probe.py --codex path/to/codex
  python tools/diagnostics/codex_mcp_recovery_probe.py --codex path/to/codex --require-auto

Default exit 0 means the fixture ran and explicit recovery worked; it DOES NOT
mean automatic recovery is implemented. --require-auto enforces that contract.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time


MOCK_SERVER = '''
import json
import os
import sys

for line in sys.stdin:
    try:
        request = json.loads(line)
        if "id" not in request:
            continue
        method = request.get("method")
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "recovery-fixture", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": [
                {"name": name, "description": name,
                 "inputSchema": {"type": "object", "properties": {}}}
                for name in ("ping", "drop")
            ]}
        elif method == "tools/call":
            if request.get("params", {}).get("name") == "drop":
                os._exit(43)
            result = {"content": [{"type": "text", "text": "pong"}],
                      "isError": False}
        else:
            result = {}
        sys.stdout.write(json.dumps(
            {"jsonrpc": "2.0", "id": request["id"], "result": result}
        ) + "\\n")
        sys.stdout.flush()
    except (ValueError, TypeError, KeyError):
        continue
'''

FAIL_ONCE = '''
import pathlib
import subprocess
import sys

directory = pathlib.Path(__file__).parent
stamp = directory / "initial_failure.flag"
if not stamp.exists():
    stamp.write_text("initial failure injected", encoding="utf-8")
    sys.exit(71)
sys.exit(subprocess.call([sys.executable, str(directory / "mock_mcp.py")]))
'''


class AppServer:
    def __init__(self, codex: str, home: Path):
        self.process = subprocess.Popen(
            [codex, "app-server", "--stdio"],
            env={**os.environ, "CODEX_HOME": str(home)},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self.responses: queue.Queue[dict] = queue.Queue()
        self.next_id = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict) and "id" in message:
                self.responses.put(message)

    def send(self, message: dict):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def request(self, method: str, params=None, timeout: float = 20):
        self.next_id += 1
        number = self.next_id
        message = {"jsonrpc": "2.0", "id": number, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                response = self.responses.get(
                    timeout=min(0.5, max(0.01, deadline - time.monotonic()))
                )
            except queue.Empty:
                continue
            if response.get("id") == number:
                return response
        raise TimeoutError(f"{method} did not respond in {timeout}s")

    def start_thread(self, home: Path):
        response = self.request("initialize", {
            "clientInfo": {"name": "codex-mcp-recovery-probe", "version": "1.0"},
            "capabilities": {"experimentalApi": True},
        })
        if not response.get("result"):
            raise RuntimeError("app-server initialize failed")
        self.send({"jsonrpc": "2.0", "method": "initialized"})
        response = self.request(
            "thread/start", {"cwd": str(home), "ephemeral": True}
        )
        thread = response.get("result", {}).get("thread", {})
        if not thread.get("id"):
            raise RuntimeError("thread/start failed")
        return thread["id"]

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=4)
        if self.process.stdin:
            self.process.stdin.close()


def tools_count(client: AppServer, thread: str) -> int:
    response = client.request("mcpServerStatus/list", {
        "threadId": thread, "serverName": "recovery_fixture",
        "detail": "full",
    })
    for server in response.get("result", {}).get("data", []):
        if server.get("name") == "recovery_fixture":
            return len(server.get("tools") or [])
    return 0


def call(client: AppServer, thread: str, name: str) -> bool:
    response = client.request("mcpServer/tool/call", {
        "threadId": thread, "server": "recovery_fixture",
        "tool": name, "arguments": {},
    })
    result = response.get("result") or {}
    return (not bool(response.get("error"))
            and result.get("isError") is False
            and any(item.get("text") == "pong"
                    for item in result.get("content", [])
                    if isinstance(item, dict)))


def one_scenario(codex: str, scenario: str) -> dict:
    directory = Path(tempfile.mkdtemp(prefix="codex-mcp-recovery-probe-"))
    server = directory / "mock_mcp.py"
    wrapper = directory / "fail_once.py"
    server.write_text(MOCK_SERVER.replace("\\\\n", "\\n"), encoding="utf-8")
    wrapper.write_text(FAIL_ONCE, encoding="utf-8")
    entry = wrapper if scenario == "startup" else server
    config = (
        "mcp_optional_startup_grace_ms = 0\n"
        "[mcp_servers.recovery_fixture]\n"
        + "command = " + json.dumps(sys.executable) + "\n"
        + "args = " + json.dumps([str(entry)]) + "\n"
        + "startup_timeout_sec = 12\n"
        + "tool_timeout_sec = 10\n"
    )
    (directory / "config.toml").write_text(config, encoding="utf-8")
    client = None
    try:
        client = AppServer(codex, directory)
        thread = client.start_thread(directory)
        initial = tools_count(client, thread)
        if scenario == "startup":
            before = tools_count(client, thread)
            auto = before > 0 and call(client, thread, "ping")
        else:
            if initial != 2 or not call(client, thread, "ping"):
                raise AssertionError("healthy MCP could not answer ping")
            call(client, thread, "drop")
            auto = call(client, thread, "ping")
            before = tools_count(client, thread)

        if not auto:
            client.request("config/mcpServer/reload", timeout=20)
        after = tools_count(client, thread)
        recovered = after == 2 and call(client, thread, "ping")
        return {
            "scenario": scenario,
            "initial_tools": initial,
            "before_reload_tools": before,
            "automatic_recovery": auto,
            "eventual_read_only_tool_success": recovered,
            "explicit_reload_needed": not auto,
        }
    finally:
        if client is not None:
            client.close()
        try:
            shutil.rmtree(directory)
        except OSError:
            # Windows may keep SQLite shared-memory handles open briefly.
            # Never kill unrelated Codex processes to force deletion.
            print(json.dumps({"cleanup_deferred": str(directory)}), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default=shutil.which("codex"))
    parser.add_argument("--scenario", choices=("startup", "drop", "all"),
                        default="all")
    parser.add_argument("--require-auto", action="store_true")
    args = parser.parse_args()
    if not args.codex or not Path(args.codex).is_file():
        parser.error("--codex must specify an existing Codex executable")
    scenarios = ("startup", "drop") if args.scenario == "all" else (args.scenario,)
    failed = False
    for scenario in scenarios:
        result = one_scenario(args.codex, scenario)
        print(json.dumps(result, sort_keys=True), flush=True)
        failed |= not result["eventual_read_only_tool_success"]
        if args.require_auto:
            failed |= not result["automatic_recovery"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
