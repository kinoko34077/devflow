"""Real SDK stdio fixtures for connection-local replacement; no GitHub/auth."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tools import devflow_mcp_stable_launcher as selector
from tools.devflow_mcp_connection import Launch, serve_connection


WORKER = """from mcp.server import MCPServer
mcp = MCPServer("fixture")
@mcp.tool()
def {name}() -> dict[str, str]:
    return {{"version": "{version}"}}
mcp.run()
"""


def prepare(root, sha, version, name="read_version"):
    directory = root / "releases" / sha
    script = directory / "tools" / "devflow_mcp.py"
    script.parent.mkdir(parents=True)
    script.write_text(WORKER.format(name=name, version=version), encoding="utf-8")
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
        def revision():
            marker = root / "active.json"
            if marker.stat().st_size > 4096:
                raise ValueError("marker too large")
            return hashlib.sha256(marker.read_bytes()).hexdigest()

        def launch():
            script = selector.selected_script(str(root / "absent.py"), root=root)
            env = {**clean_env(), "PYTHONPATH": str(script.parent.parent),
                   "PYTHONDONTWRITEBYTECODE": "1"}
            return Launch(script.parent.parent.name, StdioServerParameters(
                command=sys.executable, args=["-B", str(script)], env=env))

        await serve_connection(revision, launch, expected_tools=1,
                               smoke_name="read_version", smoke_arguments={})
    asyncio.run(run())


class ConnectionRestartTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_stdio_session_explicit_automatic_and_rejected_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = prepare(root, "a" * 40, "A")
            b = prepare(root, "b" * 40, "B")
            c = prepare(root, "c" * 40, "C")
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
                                         {"read_version", "restart_mcp"})

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
                        self.assertEqual(await read(), "C")
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
                        self.assertEqual(await read(), "A")
                        self.assertEqual({t.name for t in (await client.list_tools()).tools},
                                         {"read_version", "restart_mcp"})


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--front":
        launch_front(Path(sys.argv[2]))
    else:
        unittest.main()
