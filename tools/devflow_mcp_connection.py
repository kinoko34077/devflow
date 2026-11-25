"""Connection-local MCP worker replacement pilot (#1138).

Uses the pinned SDK for both ends. The host supplies a trusted selector and
fixed launch parameters; neither paths nor executable arguments are accepted
from MCP callers. Not yet wired into the installed stable launcher.
"""
from __future__ import annotations

import asyncio
import json
import time
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
RETRY_DELAY = 2
RETRY_COOLDOWN = 60
MAX_RETRY_BURST = 3


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
        self.failed = False

    def usable(self) -> bool:
        return self.task is not None and not self.task.done() and not self.failed

    async def start(self) -> tuple[Any, list[types.Tool]]:
        self.task = asyncio.create_task(self._run())
        try:
            return await asyncio.shield(self.ready)
        except BaseException:
            self.ready.cancel()
            await self.close()
            raise

    async def _run(self) -> None:
        active = None
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
                            active = future
                            try:
                                value = await client.call_tool(
                                    name, arguments, read_timeout_seconds=CALL_TIMEOUT,
                                )
                                if not isinstance(value, types.CallToolResult):
                                    raise ValueError("unexpected worker result type")
                            except Exception:
                                self.failed = True
                                value = _reply({"status": "WORKER_CALL_FAILED"}, error=True)
                            if not future.done():
                                future.set_result(value)
                            active = None
                            if self.failed:
                                break
        except Exception:
            if not self.ready.done():
                self.ready.set_exception(RuntimeError("worker initialization failed"))
        finally:
            self.failed = True
            if not self.ready.done():
                self.ready.set_exception(RuntimeError("worker exited during initialization"))
            if active is not None and not active.done():
                active.set_result(_reply({"status": "WORKER_UNAVAILABLE"}, error=True))
            # Never strand an outstanding caller if the child session exits.
            while not self.queue.empty():
                entry = self.queue.get_nowait()
                if entry is not None and not entry[2].done():
                    entry[2].set_result(_reply({"status": "WORKER_UNAVAILABLE"}, error=True))

    async def call(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        if not self.usable():
            return _reply({"status": "WORKER_UNAVAILABLE"}, error=True)
        future = asyncio.get_running_loop().create_future()
        self.queue.put_nowait((name, arguments, future))
        return await future

    async def close(self) -> None:
        if self.task is not None:
            if not self.task.done():
                self.queue.put_nowait(None)
            await asyncio.gather(self.task, return_exceptions=True)


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
        self.refresh_task: asyncio.Task | None = None
        self.retry_revision: str | None = None
        self.retry_count = 0
        self.retry_at = 0.0
        self.last_status = "STARTING"
        self.closed = False
        self.tools: list[types.Tool] = []
        self.contract: dict[str, Any] = {}

    async def start(self) -> Any:
        revision = self.revision()
        worker = Worker(await asyncio.to_thread(self.launch), self.expected_tools)
        try:
            init, tools = await worker.start()
            if self.revision() != revision:
                raise RuntimeError("marker changed during initialization")
            self.worker = worker
            self.current_revision = revision
            self.tools = tools
            self.contract = catalog_contract(tools)
            self.last_status = "UP_TO_DATE"
            return init
        except BaseException:
            await worker.close()
            raise

    def version(self) -> str:
        return self.worker.launch.version if self.worker is not None else "UNAVAILABLE"

    def _state(self, status: str) -> dict[str, Any]:
        self.last_status = status
        return {"status": status, "running_version": self.version()}

    def _schedule_refresh(self, *, explicit: bool):
        """Under routing lock, start at most one connection-local candidate task."""
        if self.closed:
            return None, self._state("CONNECTION_CLOSED")
        if self.refresh_task is not None and not self.refresh_task.done():
            return self.refresh_task, self._state("PREPARING")
        try:
            revision = self.revision()
        except Exception:
            return None, self._state("INVALID_SELECTION")
        healthy = self.worker is not None and self.worker.usable()
        if not explicit and healthy and revision == self.current_revision:
            return None, self._state("UP_TO_DATE")
        if not explicit and revision == self.rejected_revision:
            return None, self._state("PREVIOUSLY_REJECTED")
        if revision != self.retry_revision:
            self.retry_revision = revision
            self.retry_count = 0
            self.retry_at = 0.0
        now = time.monotonic()
        if not explicit and now < self.retry_at:
            return None, self._state("RETRY_DEFERRED")
        if self.retry_count >= MAX_RETRY_BURST:
            self.retry_count = 0
        self.refresh_task = asyncio.create_task(self._refresh(revision))
        return self.refresh_task, self._state("PREPARING")

    async def _refresh(self, revision: str) -> dict[str, Any]:
        """Prepare outside the routing lock; commit only after in-flight calls."""
        candidate = None
        incompatible = False
        try:
            candidate = Worker(await asyncio.to_thread(self.launch), self.expected_tools)
            _, tools = await candidate.start()
            if catalog_contract(tools) != self.contract:
                incompatible = True
                raise ValueError("incompatible tool contract")
            if self.smoke_name not in self.contract:
                incompatible = True
                raise ValueError("missing smoke tool")
            result = await candidate.call(self.smoke_name, self.smoke_arguments)
            if result.is_error or not candidate.usable():
                raise ValueError("candidate smoke failed")
            async with self.lock:
                if self.closed or self.revision() != revision or not candidate.usable():
                    raise ValueError("selection changed or candidate unavailable")
                previous = self.worker
                self.worker = candidate
                self.current_revision = revision
                self.rejected_revision = None
                self.retry_count = 0
                self.retry_at = 0.0
                self.tools = tools
                state = self._state("RESTARTED")
                candidate = None  # ownership transferred
            if previous is not None:
                await previous.close()
            return state
        except asyncio.CancelledError:
            raise
        except Exception:
            async with self.lock:
                if incompatible:
                    self.rejected_revision = revision
                else:
                    self.retry_count += 1
                    delay = (RETRY_COOLDOWN if self.retry_count >= MAX_RETRY_BURST
                             else RETRY_DELAY * 2 ** (self.retry_count - 1))
                    self.retry_at = time.monotonic() + delay
                return self._state("CANDIDATE_REJECTED" if incompatible else "RETRY_DEFERRED")
        finally:
            if candidate is not None:
                await candidate.close()

    def _with_runtime_status(self, result: types.CallToolResult) -> types.CallToolResult:
        """Keep domain content unchanged; publish explicit runtime metadata."""
        payload = result.model_dump(by_alias=True, exclude_none=True)
        meta = dict(payload.get("_meta") or {})
        meta["kinotch.devflow.runtime"] = {
            "status": self.last_status,
            "running_version": self.version(),
        }
        payload["_meta"] = meta
        return types.CallToolResult.model_validate(payload)

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
        if params.name == RESTART_TOOL:
            if params.arguments:
                return _reply({"status": "INVALID_ARGUMENTS"}, error=True)
            async with self.lock:
                task, state = self._schedule_refresh(explicit=True)
            if task is not None:
                state = await asyncio.shield(task)
            return _reply(state, error=state["status"] != "RESTARTED")

        async with self.lock:
            if params.name not in self.contract:
                return _reply({"status": "UNKNOWN_TOOL"}, error=True)
            task, state = self._schedule_refresh(explicit=False)
            if self.worker is not None and self.worker.usable():
                result = await self.worker.call(params.name, params.arguments or {})
                if not self.worker.usable():
                    self._schedule_refresh(explicit=False)
                # No retry of a call already submitted, even after transport failure.
                return self._with_runtime_status(result)

        # No usable old worker: a not-yet-submitted request may wait for recovery.
        if task is not None:
            await asyncio.shield(task)
        async with self.lock:
            if self.worker is None or not self.worker.usable():
                return _reply(self._state("WORKER_UNAVAILABLE"), error=True)
            return self._with_runtime_status(
                await self.worker.call(params.name, params.arguments or {}),
            )

    async def close(self):
        async with self.lock:
            self.closed = True
            task = self.refresh_task
            worker = self.worker
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if worker is not None:
            await worker.close()


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
