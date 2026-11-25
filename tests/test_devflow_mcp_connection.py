"""Real SDK stdio fixtures for connection-local replacement; no GitHub/auth."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tools import devflow_mcp_stable_launcher as selector
from tools import devflow_mcp_release_manager as manager
from tools.devflow_mcp_connection import serve_connection


WORKER = """import os
import time
from pathlib import Path
from mcp import types
from mcp.server import MCPServer
mcp = MCPServer("fixture")
@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def {name}() -> dict[str, str]:
    return {{"version": "{version}"}}
@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def crash_worker() -> dict[str, str]:
    os._exit(9)
@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def slow_read() -> dict[str, str]:
    root = Path(__file__).parents[3]
    (root / "slow-started").touch()
    deadline = time.monotonic() + 15
    while not (root / "slow-finish").exists():
        if time.monotonic() > deadline: raise RuntimeError("fixture timeout")
        time.sleep(0.05)
    return {{"version": "{version}"}}
mcp.run()
"""


def prepare(root, sha, version, name="read_version", gate=None, extra=False):
    directory = root / "releases" / sha
    script = directory / "tools" / "devflow_mcp.py"
    script.parent.mkdir(parents=True)
    prefix = ""
    if gate is not None:
        prefix = (
            "import time\nfrom pathlib import Path\n"
            f"gate = Path({str(gate)!r})\n"
            "deadline = time.monotonic() + 15\n"
            "while not gate.exists():\n"
            "    if time.monotonic() > deadline: raise RuntimeError('fixture gate timeout')\n"
            "    time.sleep(0.05)\n"
        )
    body = WORKER.format(name=name, version=version)
    if extra:
        body = body.replace("mcp.run()", '''@mcp.tool(annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def new_read(value: str = "default") -> dict[str, str]:
    return {"value": value}
mcp.run()''')
    script.write_text(prefix + body, encoding="utf-8")
    return {"schema_version": 2, "sha": sha,
            "tree_sha256": selector.release_tree_digest(directory)}


def select(root, state):
    temp = root / "next.json"
    temp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(temp, root / "active.json")


def clean_env():
    return {k: v for k, v in os.environ.items()
            if not any(s in k.upper() for s in ("TOKEN", "API_KEY", "SECRET", "PASSWORD"))}


def launch_front(root):
    async def run():
        from types import SimpleNamespace
        from unittest.mock import patch

        def launch():
            # Same selector and environment path as the installed front;
            # substitute only the credential acquisition for this fixture.
            with patch.object(selector.subprocess, "run", return_value=SimpleNamespace(
                    returncode=0, stdout="fixture-token")):
                return selector.launch_parameters("fixture-gh", str(root / "absent.py"),
                                                  root=root)

        await serve_connection(lambda: selector.selection_revision(root), launch,
                               required_calls={"read_version": {}},
                               smoke_name="read_version", smoke_arguments={},
                               updates_held=lambda: manager.updates_held(root))
    asyncio.run(run())


class ConnectionRestartTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_stdio_session_explicit_automatic_and_rejected_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = prepare(root, "a" * 40, "A")
            b = prepare(root, "b" * 40, "B")
            gate = root / "allow-c"
            c = prepare(root, "c" * 40, "C", gate=gate)
            bad = prepare(root, "d" * 40, "D", "wrong_tool")
            select(root, a)
            env = {**clean_env(), "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                   "PYTHONDONTWRITEBYTECODE": "1"}
            front = StdioServerParameters(
                command=sys.executable,
                args=["-B", "-m", "tests.test_devflow_mcp_connection", "--front", str(root)],
                env=env,
            )
            with open(os.devnull, "w") as log:
                async with stdio_client(front, errlog=log) as (rd, wr):
                    async with ClientSession(rd, wr) as client:
                        await asyncio.wait_for(client.initialize(), 35)
                        listing = await asyncio.wait_for(client.list_tools(), 15)
                        self.assertEqual({t.name for t in listing.tools},
                                         {"read_version", "crash_worker", "slow_read", "restart_mcp"})

                        async def read():
                            result = await asyncio.wait_for(client.call_tool("read_version", {}), 35)
                            self.assertFalse(result.is_error)
                            return json.loads(result.content[0].text)["version"]

                        self.assertEqual(await read(), "A")
                        select(root, b)
                        restart = await asyncio.wait_for(client.call_tool("restart_mcp", {}), 35)
                        self.assertFalse(restart.is_error)
                        self.assertEqual(json.loads(restart.content[0].text),
                                         {"status": "RESTARTED", "running_version": "b" * 40})
                        self.assertEqual(await read(), "B")
                        select(root, c)
                        # C cannot initialize before the test opens its gate.
                        # A synchronous refresh would hang/fail instead of returning B.
                        old_result = await asyncio.wait_for(client.call_tool("read_version", {}), 5)
                        self.assertFalse(old_result.is_error)
                        self.assertEqual(json.loads(old_result.content[0].text)["version"], "B")
                        self.assertEqual(old_result.model_dump(by_alias=True)["_meta"]
                                         ["kinotch.devflow.runtime"]["status"], "PREPARING")
                        gate.touch()

                        async def eventually(version):
                            async def observe():
                                while await read() != version:
                                    await asyncio.sleep(0.05)
                            await asyncio.wait_for(observe(), 30)

                        await eventually("C")
                        invalid = await client.call_tool("restart_mcp", {"command": "anything"})
                        self.assertTrue(invalid.is_error)
                        select(root, bad)
                        self.assertEqual(await read(), "C")
                        self.assertEqual(await read(), "C")
                        rejected = await asyncio.wait_for(client.call_tool("restart_mcp", {}), 35)
                        self.assertTrue(rejected.is_error)
                        self.assertEqual(json.loads(rejected.content[0].text)["running_version"], "c" * 40)
                        self.assertEqual(await read(), "C")
                        select(root, a)
                        await eventually("A")
                        # Complete an explicit restart so no previous swap is pending.
                        self.assertFalse((await client.call_tool("restart_mcp", {})).is_error)
                        crash = await asyncio.wait_for(client.call_tool("crash_worker", {}), 35)
                        self.assertTrue(crash.is_error)
                        # Same marker, same session. The failed call is not replayed.
                        self.assertEqual(await read(), "A")
                        self.assertEqual({t.name for t in (await client.list_tools()).tools},
                                         {"read_version", "crash_worker", "slow_read", "restart_mcp"})


    async def test_changed_catalog_notification_and_scoped_refresh(self):
        from mcp import types
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = prepare(root, "a" * 40, "A")
            b = prepare(root, "b" * 40, "B", extra=True)
            select(root, a)
            env = {**clean_env(), "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                   "PYTHONDONTWRITEBYTECODE": "1"}
            front = StdioServerParameters(
                command=sys.executable,
                args=["-B", "-m", "tests.test_devflow_mcp_connection", "--front", str(root)],
                env=env,
            )
            notice = asyncio.Event()

            async def observe(message):
                if isinstance(message, types.ToolListChangedNotification):
                    notice.set()

            with open(os.devnull, "w") as log:
                async with stdio_client(front, errlog=log) as (rd, wr):
                    async with ClientSession(rd, wr, message_handler=observe) as client:
                        initialized = await asyncio.wait_for(client.initialize(), 35)
                        self.assertTrue(initialized.capabilities.tools.list_changed)
                        original = await client.list_tools()
                        self.assertNotIn("new_read", {t.name for t in original.tools})
                        select(root, b)
                        restart = await asyncio.wait_for(client.call_tool("restart_mcp", {}), 35)
                        self.assertTrue(restart.is_error)
                        self.assertEqual(json.loads(restart.content[0].text)["status"],
                                         "AWAITING_CATALOG_REFRESH")
                        self.assertEqual(json.loads(restart.content[0].text)["action"], "REFRESH_TOOLS_LIST")
                        await asyncio.wait_for(notice.wait(), 5)
                        old = await client.call_tool("read_version", {})
                        self.assertFalse(old.is_error)
                        self.assertEqual(json.loads(old.content[0].text)["version"], "A")
                        # An oversized marker must not break the old list or worker,
                        # even while a changed catalog is pending publication.
                        (root / "active.json").write_bytes(b"x" * 4097)
                        retained = await client.list_tools()
                        self.assertNotIn("new_read", {t.name for t in retained.tools})
                        retained_read = await client.call_tool("read_version", {})
                        self.assertFalse(retained_read.is_error)
                        self.assertEqual(json.loads(retained_read.content[0].text)["version"], "A")
                        self.assertEqual(retained_read.model_dump(by_alias=True)["_meta"]
                                         ["kinotch.devflow.runtime"]["status"], "INVALID_SELECTION")
                        notice.clear()
                        select(root, b)
                        self.assertFalse((await client.call_tool("read_version", {})).is_error)
                        await asyncio.wait_for(notice.wait(), 30)
                        changed = await client.list_tools()
                        self.assertIn("new_read", {t.name for t in changed.tools})
                        current = await client.call_tool("read_version", {})
                        self.assertEqual(json.loads(current.content[0].text)["version"], "B")
                        extra = await client.call_tool("new_read", {"value": "fresh"})
                        self.assertFalse(extra.is_error)
                        self.assertEqual(json.loads(extra.content[0].text), {"value": "fresh"})
                        invalid = await client.call_tool("new_read", {"value": []})
                        self.assertTrue(invalid.is_error)
                        self.assertEqual(json.loads(invalid.content[0].text)["action"],
                                         "REFRESH_TOOLS_LIST")
                        notice.clear()
                        select(root, a)
                        old_result = await client.call_tool("read_version", {})
                        self.assertFalse(old_result.is_error)
                        await asyncio.wait_for(notice.wait(), 30)
                        refreshed = await client.list_tools()
                        self.assertNotIn("new_read", {t.name for t in refreshed.tools})
                        missing = await client.call_tool("new_read", {})
                        self.assertTrue(missing.is_error)
                        stable = await client.call_tool("read_version", {})
                        self.assertFalse(stable.is_error)
                        self.assertEqual(json.loads(stable.content[0].text)["version"], "A")


    async def test_restart_and_list_do_not_wait_for_inflight_old_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = prepare(root, "a" * 40, "A")
            b = prepare(root, "b" * 40, "B")
            select(root, a)
            env = {**clean_env(), "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                   "PYTHONDONTWRITEBYTECODE": "1"}
            front = StdioServerParameters(
                command=sys.executable,
                args=["-B", "-m", "tests.test_devflow_mcp_connection", "--front", str(root)],
                env=env,
            )
            async def observe_start():
                while not (root / "slow-started").exists():
                    await asyncio.sleep(0.05)
            with open(os.devnull, "w") as log:
                async with stdio_client(front, errlog=log) as (rd, wr):
                    async with ClientSession(rd, wr) as client:
                        await asyncio.wait_for(client.initialize(), 35)
                        await client.list_tools()
                        slow = asyncio.create_task(client.call_tool("slow_read", {}))
                        try:
                            await asyncio.wait_for(observe_start(), 5)
                            self.assertFalse(slow.done())
                            listing = await asyncio.wait_for(client.list_tools(), 3)
                            self.assertIn("restart_mcp", {t.name for t in listing.tools})
                            select(root, b)
                            restart = await asyncio.wait_for(client.call_tool("restart_mcp", {}), 12)
                            self.assertFalse(restart.is_error)
                            new = await asyncio.wait_for(client.call_tool("read_version", {}), 3)
                            self.assertEqual(json.loads(new.content[0].text)["version"], "B")
                            self.assertFalse(slow.done())
                        finally:
                            (root / "slow-finish").touch()
                        old = await asyncio.wait_for(slow, 5)
                        self.assertFalse(old.is_error)
                        self.assertEqual(json.loads(old.content[0].text)["version"], "A")
                        runtime = old.model_dump(by_alias=True)["_meta"]["kinotch.devflow.runtime"]
                        self.assertEqual(runtime["served_version"], "a" * 40)
                        self.assertEqual(runtime["running_version"], "b" * 40)


    async def test_held_rollback_without_relist_preserves_only_unchanged_calls(self):
        from mcp import types
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = prepare(root, "a" * 40, "A")
            b = prepare(root, "b" * 40, "B", extra=True)
            manager.write_marker(root, b["sha"], a["sha"],
                                 tree_sha256=b["tree_sha256"],
                                 previous_tree_sha256=a["tree_sha256"])
            front = StdioServerParameters(
                command=sys.executable,
                args=["-B", "-m", "tests.test_devflow_mcp_connection", "--front", str(root)],
                env={**clean_env(), "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                     "PYTHONDONTWRITEBYTECODE": "1"},
            )
            notice = asyncio.Event()

            async def observe(message):
                if isinstance(message, types.ToolListChangedNotification):
                    notice.set()

            with open(os.devnull, "w") as log:
                async with stdio_client(front, errlog=log) as (rd, wr):
                    async with ClientSession(rd, wr, message_handler=observe) as first:
                        await asyncio.wait_for(first.initialize(), 35)
                        self.assertIn("new_read", {t.name for t in (await first.list_tools()).tools})
                        async with stdio_client(front, errlog=log) as (rd2, wr2):
                            async with ClientSession(rd2, wr2) as second:
                                await asyncio.wait_for(second.initialize(), 35)
                                before = await second.call_tool("read_version", {})
                                self.assertEqual(json.loads(before.content[0].text)["version"], "B")
                                self.assertEqual(manager.rollback(root, root / "unused.py"),
                                                 "ROLLED_BACK " + a["sha"])
                                # Neither client has relisted. The held selection is
                                # authoritative; safe unchanged calls must use A.
                                for client in (first, second):
                                    result = await asyncio.wait_for(client.call_tool("read_version", {}), 35)
                                    self.assertFalse(result.is_error)
                                    self.assertEqual(json.loads(result.content[0].text)["version"], "A")
                                    rejected = await client.call_tool("new_read", {})
                                    self.assertTrue(rejected.is_error)
                                    self.assertEqual(json.loads(rejected.content[0].text)["action"],
                                                     "REFRESH_TOOLS_LIST")
                                await asyncio.wait_for(notice.wait(), 5)
                                self.assertNotIn("new_read", {t.name for t in (await first.list_tools()).tools})
                                self.assertTrue(manager.updates_held(root))
                            # EOF on second client cannot terminate first.
                        stable = await first.call_tool("read_version", {})
                        self.assertFalse(stable.is_error)
                        self.assertEqual(json.loads(stable.content[0].text)["version"], "A")


    async def test_cancelled_call_does_not_replay_or_block_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = prepare(root, "a" * 40, "A")
            b = prepare(root, "b" * 40, "B")
            select(root, a)
            front = StdioServerParameters(
                command=sys.executable,
                args=["-B", "-m", "tests.test_devflow_mcp_connection", "--front", str(root)],
                env={**clean_env(), "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                     "PYTHONDONTWRITEBYTECODE": "1"},
            )
            async def started():
                while not (root / "slow-started").exists():
                    await asyncio.sleep(0.05)
            with open(os.devnull, "w") as log:
                async with stdio_client(front, errlog=log) as (rd, wr):
                    async with ClientSession(rd, wr) as client:
                        await asyncio.wait_for(client.initialize(), 35)
                        await client.list_tools()
                        slow = asyncio.create_task(client.call_tool("slow_read", {}))
                        try:
                            await asyncio.wait_for(started(), 5)
                            slow.cancel()
                            with self.assertRaises(asyncio.CancelledError):
                                await slow
                            select(root, b)
                            restart = await asyncio.wait_for(client.call_tool("restart_mcp", {}), 12)
                            self.assertFalse(restart.is_error)
                            new = await asyncio.wait_for(client.call_tool("read_version", {}), 3)
                            self.assertEqual(json.loads(new.content[0].text)["version"], "B")
                        finally:
                            (root / "slow-finish").touch()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--front":
        launch_front(Path(sys.argv[2]))
    else:
        unittest.main()
