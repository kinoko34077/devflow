"""Connection-local MCP worker replacement pilot (#1138).

Uses the pinned SDK for both ends. The host supplies a trusted selector and
fixed launch parameters; neither paths nor executable arguments are accepted
from MCP callers. Not yet wired into the installed stable launcher.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server import Server
from mcp.server.stdio import stdio_server

try:
    from .devflow_mcp_release_manager import _compatible_schema
except ImportError:
    from devflow_mcp_release_manager import _compatible_schema


RESTART_TOOL = "restart_mcp"
START_TIMEOUT = 20
LIST_TIMEOUT = 10
CALL_TIMEOUT = 90


@dataclass(frozen=True)
class Launch:
    version: str
    parameters: StdioServerParameters


def catalog_contract(tools: list[types.Tool]) -> dict[str, Any]:
    """Retain callable schema and semantic metadata; ignore documentation."""
    result = {}
    for tool in tools:
        if tool.name in result or tool.name == RESTART_TOOL:
            raise ValueError("invalid worker tool catalog")
        data = tool.model_dump(by_alias=True, exclude_none=True)
        for key in ("title", "description"):
            data.pop(key, None)
        for key in ("inputSchema", "outputSchema"):
            if key in data:
                data[key] = _compatible_schema(data[key])
        result[tool.name] = data
    return result


def _reply(payload: dict[str, Any], *, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload))],
        isError=error,
    )


class Worker:
    """Own the child SDK context in one task, for its whole lifetime."""

    def __init__(self, launch: Launch, expected_tools: int):
        self.launch = launch
        self.expected_tools = expected_tools
        self.queue: asyncio.Queue = asyncio.Queue()
        self.ready = asyncio.get_running_loop().create_future()
        self.task: asyncio.Task | None = None

    async def start(self) -> tuple[Any, list[types.Tool]]:
        self.task = asyncio.create_task(self._run())
        try:
            return await asyncio.shield(self.ready)
        except BaseException:
            await self.close()
            raise

    async def _run(self) -> None:
        try:
            # A release error may contain internal details. Do not emit child
            # stderr or raw exceptions to the outer protocol.
            import os
            with open(os.devnull, "w") as log:
                async with stdio_client(self.launch.parameters, errlog=log) as (rd, wr):
                    async with ClientSession(rd, wr) as client:
                        init = await asyncio.wait_for(client.initialize(), START_TIMEOUT)
                        listing = await asyncio.wait_for(client.list_tools(), LIST_TIMEOUT)
                        if (listing.next_cursor is not None
                                or len(catalog_contract(listing.tools)) != self.expected_tools):
                            raise ValueError("unexpected worker tool catalog")
                        self.ready.set_result((init, listing.tools))
                        while True:
                            entry = await self.queue.get()
                            if entry is None:
                                break
                            name, arguments, future = entry
                            if future.cancelled():
                                continue
                            try:
                                value = await client.call_tool(
                                    name, arguments, read_timeout_seconds=CALL_TIMEOUT,
                                )
                                if not isinstance(value, types.CallToolResult):
                                    raise ValueError("unexpected worker result type")
                            except Exception:
                                value = _reply({"status": "WORKER_CALL_FAILED"}, error=True)
                            if not future.done():
                                future.set_result(value)
        except Exception:
            if not self.ready.done():
                self.ready.set_exception(RuntimeError("worker initialization failed"))
        finally:
            # Never strand an outstanding caller if the child session exits.
            while not self.queue.empty():
                entry = self.queue.get_nowait()
                if entry is not None and not entry[2].done():
                    entry[2].set_result(_reply({"status": "WORKER_UNAVAILABLE"}, error=True))

    async def call(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        if self.task is None or self.task.done():
            return _reply({"status": "WORKER_UNAVAILABLE"}, error=True)
        future = asyncio.get_running_loop().create_future()
        self.queue.put_nowait((name, arguments, future))
        return await future

    async def close(self) -> None:
        if self.task is not None:
            if not self.task.done():
                self.queue.put_nowait(None)
            await self.task


class Connection:
    """Keep the outer SDK session stable and swap only a compatible child.

    revision() returns an opaque observation of the existing verified marker.
    launch() resolves and verifies that marker using the installed selector.
    Both are host-controlled, never MCP inputs. No fetch or promotion occurs.
    """

    def __init__(self, revision: Callable[[], str], launch: Callable[[], Launch],
                 *, expected_tools: int, smoke_name: str, smoke_arguments: dict[str, Any]):
        self.revision = revision
        self.launch = launch
        self.expected_tools = expected_tools
        self.smoke_name = smoke_name
        self.smoke_arguments = smoke_arguments
        self.lock = asyncio.Lock()
        self.worker: Worker | None = None
        self.current_revision: str | None = None
        self.rejected_revision: str | None = None
        self.tools: list[types.Tool] = []
        self.contract: dict[str, Any] = {}

    async def start(self) -> Any:
        revision = self.revision()
        worker = Worker(self.launch(), self.expected_tools)
        try:
            init, tools = await worker.start()
            if self.revision() != revision:
                raise RuntimeError("marker changed during initialization")
            self.worker = worker
            self.current_revision = revision
            self.tools = tools
            self.contract = catalog_contract(tools)
            return init
        except BaseException:
            await worker.close()
            raise

    def version(self) -> str:
        return self.worker.launch.version if self.worker is not None else "UNAVAILABLE"

    async def _refresh(self, *, explicit: bool) -> dict[str, Any]:
        """Called under the connection lock. Failed candidates never replace old."""
        try:
            revision = self.revision()
        except Exception:
            return {"status": "INVALID_SELECTION", "running_version": self.version()}
        if not explicit and revision == self.current_revision:
            return {"status": "UP_TO_DATE", "running_version": self.version()}
        if not explicit and revision == self.rejected_revision:
            return {"status": "PREVIOUSLY_REJECTED", "running_version": self.version()}
        candidate = None
        try:
            candidate = Worker(self.launch(), self.expected_tools)
            _, tools = await candidate.start()
            if catalog_contract(tools) != self.contract:
                raise ValueError("incompatible tool contract")
            if self.smoke_name not in self.contract:
                raise ValueError("missing smoke tool")
            result = await candidate.call(self.smoke_name, self.smoke_arguments)
            if result.is_error:
                raise ValueError("candidate smoke failed")
            if self.revision() != revision:
                raise ValueError("selection changed")
        except asyncio.CancelledError:
            if candidate is not None:
                await candidate.close()
            raise
        except Exception:
            self.rejected_revision = revision
            if candidate is not None:
                await candidate.close()
            return {"status": "CANDIDATE_REJECTED", "running_version": self.version()}

        previous = self.worker
        self.worker = candidate
        self.current_revision = revision
        self.rejected_revision = None
        self.tools = tools
        if previous is not None:
            await previous.close()
        return {"status": "RESTARTED", "running_version": self.version()}

    async def list_tools(self, _context, _params):
        async with self.lock:
            # Catalog remains compatible across worker generations.
            return types.ListToolsResult(tools=[*self.tools, types.Tool(
                name=RESTART_TOOL,
                description=("Restart this MCP connection's worker on the locally selected "
                             "verified release, without restarting the AI. No GitHub write, "
                             "fetch, arbitrary command, or other connection is affected."),
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
            )])

    async def call_tool(self, _context, params):
        async with self.lock:
            if params.name == RESTART_TOOL:
                if params.arguments:
                    return _reply({"status": "INVALID_ARGUMENTS"}, error=True)
                state = await self._refresh(explicit=True)
                return _reply(state, error=state["status"] != "RESTARTED")
            if params.name not in self.contract or self.worker is None:
                return _reply({"status": "UNKNOWN_TOOL"}, error=True)
            await self._refresh(explicit=False)
            # No retry of an already submitted call, even if the worker fails.
            return await self.worker.call(params.name, params.arguments or {})

    async def close(self):
        if self.worker is not None:
            await self.worker.close()


async def serve_connection(revision: Callable[[], str], launch: Callable[[], Launch],
                           *, expected_tools: int, smoke_name: str,
                           smoke_arguments: dict[str, Any]) -> None:
    """Isolated pilot; the production installer is deliberately unchanged."""
    connection = Connection(revision, launch, expected_tools=expected_tools,
                            smoke_name=smoke_name, smoke_arguments=smoke_arguments)
    try:
        initial = await connection.start()
        server = Server(
            initial.server_info.name, version=initial.server_info.version,
            instructions=initial.instructions,
            on_list_tools=connection.list_tools, on_call_tool=connection.call_tool,
        )
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await connection.close()
