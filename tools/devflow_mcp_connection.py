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
from typing import Any, Callable, Mapping

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server

if __package__:
    from .devflow_mcp_catalog import (CatalogError, RESTART_TOOL, REQUIRED_CALLS,
                                     admit_catalog, arguments_supported, publication_schema)
else:
    from devflow_mcp_catalog import (CatalogError, RESTART_TOOL, REQUIRED_CALLS,
                                    admit_catalog, arguments_supported, publication_schema)

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
    """Detect a publication change; never use equality for admission."""
    result = {}
    for tool in tools:
        data = tool.model_dump(by_alias=True, exclude_none=True)
        for key in ("title", "description"):
            data.pop(key, None)
        for key in ("inputSchema", "outputSchema"):
            if key in data:
                data[key] = publication_schema(data[key])
        result[tool.name] = data
    return result


def _reply(payload: dict[str, Any], *, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload))],
        isError=error,
    )


class Worker:
    """Own the child SDK context in one task, for its whole lifetime."""

    def __init__(self, launch: Launch, required_calls: Mapping[str, Mapping[str, Any]]):
        self.launch = launch
        self.required_calls = required_calls
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
            await self.close(abort=True)
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
                        admit_catalog(listing.tools, next_cursor=listing.next_cursor,
                                      required_calls=self.required_calls)
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
        except CatalogError:
            if not self.ready.done():
                self.ready.set_exception(CatalogError("worker catalog rejected"))
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

    def submit(self, name: str, arguments: dict[str, Any]) -> asyncio.Future:
        """Enqueue synchronously while the routing lock still owns selection."""
        future = asyncio.get_running_loop().create_future()
        if not self.usable():
            future.set_result(_reply({"status": "WORKER_UNAVAILABLE"}, error=True))
        else:
            self.queue.put_nowait((name, arguments, future))
        return future

    async def call(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        return await self.submit(name, arguments)

    async def close(self, *, abort: bool = False) -> None:
        if self.task is not None:
            if not self.task.done():
                if abort:
                    self.task.cancel()
                else:
                    self.queue.put_nowait(None)
            await asyncio.gather(self.task, return_exceptions=True)


class Connection:
    """Keep the outer SDK session stable and swap only a compatible child.

    revision() returns an opaque observation of the existing verified marker.
    launch() resolves and verifies that marker using the installed selector.
    Both are host-controlled, never MCP inputs. No fetch or promotion occurs.
    """

    def __init__(self, revision: Callable[[], str], launch: Callable[[], Launch],
                 *, smoke_name: str, smoke_arguments: dict[str, Any],
                 required_calls: Mapping[str, Mapping[str, Any]] = REQUIRED_CALLS,
                 updates_held: Callable[[], bool] = lambda: False,
                 rollback_epoch: Callable[[], str] = lambda: "INITIAL"):
        self.revision = revision
        self.updates_held = updates_held
        self.rollback_epoch = rollback_epoch
        self.launch = launch
        self.required_calls = required_calls
        self.smoke_name = smoke_name
        self.smoke_arguments = smoke_arguments
        self.lock = asyncio.Lock()
        self.worker: Worker | None = None
        self.current_revision: str | None = None
        self.current_epoch: str | None = None
        self.rejected_revision: str | None = None
        self.rejected_epoch: str | None = None
        self.refresh_task: asyncio.Task | None = None
        self.retry_revision: str | None = None
        self.retry_epoch: str | None = None
        self.retry_count = 0
        self.retry_at = 0.0
        self.last_status = "STARTING"
        self.closed = False
        self.tools: list[types.Tool] = []
        self.contract: dict[str, Any] = {}
        self.pending: tuple[str, Worker, list[types.Tool], str] | None = None
        self.session = None
        self.retired: dict[asyncio.Task, Worker] = {}
        self.stale_contract: dict[str, Any] | None = None

    async def start(self) -> Any:
        epoch = self.rollback_epoch()
        revision = self.revision()
        worker = Worker(await asyncio.to_thread(self.launch), self.required_calls)
        try:
            init, tools = await worker.start()
            if self.revision() != revision or self.rollback_epoch() != epoch:
                raise RuntimeError("marker changed during initialization")
            # The generation is written before rollback changes selection.
            # A new connection must not capture the old selection in that gap.
            if (epoch != "INITIAL" and self.updates_held()
                    and epoch.partition(":")[2] != worker.launch.version):
                raise RuntimeError("rollback selection is not yet active")
            self.worker = worker
            self.current_revision = revision
            self.current_epoch = epoch
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
        state = {"status": status, "running_version": self.version()}
        if status in {"AWAITING_CATALOG_REFRESH", "CATALOG_REFRESH_REQUIRED"}:
            state["action"] = "REFRESH_TOOLS_LIST"
        return state

    def _retire(self, worker: Worker | None) -> None:
        """Transfer cleanup ownership before any cancellable await."""
        if worker is not None:
            task = asyncio.create_task(worker.close())
            self.retired[task] = worker
            task.add_done_callback(lambda done: self.retired.pop(done, None))

    def _discard_pending(self) -> None:
        if self.pending is not None:
            self._retire(self.pending[1])
            self.pending = None

    def _held_selection_differs(self) -> bool:
        # A known unchanged selection remains safe regardless of hold state.
        # If selection is unknown or changed, an unobservable hold cannot
        # authorize continued use of a potentially superseded worker.
        try:
            if self.rollback_epoch() != self.current_epoch:
                return True
        except Exception:
            return True
        try:
            if self.revision() == self.current_revision:
                return False
        except Exception:
            pass
        try:
            return self.updates_held()
        except Exception:
            return True

    def _commit_pending_rollback(self, revision: str) -> bool:
        if self.pending is None:
            return False
        selected, worker, tools, epoch = self.pending
        try:
            still_selected = self.revision() == revision and self.rollback_epoch() == epoch
        except Exception:
            return False
        if selected != revision or not worker.usable() or not still_selected:
            return False
        if self.stale_contract is None:
            self.stale_contract = self.contract
        self.pending = None
        previous, _ = self._commit(revision, worker, tools, epoch)
        self._retire(previous)
        self._state("CATALOG_REFRESH_REQUIRED")
        return True

    def _schedule_refresh(self, *, explicit: bool):
        """Under routing lock, start at most one connection-local candidate task."""
        if self.closed:
            return None, self._state("CONNECTION_CLOSED")
        if self.refresh_task is not None and not self.refresh_task.done():
            return self.refresh_task, self._state("PREPARING")
        try:
            revision = self.revision()
            epoch = self.rollback_epoch()
        except Exception:
            self._discard_pending()
            return None, self._state("INVALID_SELECTION")
        if self.pending is not None and (
            self.pending[0] != revision or self.pending[3] != epoch
            or not self.pending[1].usable()
        ):
            self._discard_pending()
        if epoch != self.current_epoch and revision == self.current_revision:
            try:
                if self.updates_held():
                    return None, self._state("ROLLBACK_SELECTION_UNAVAILABLE")
            except Exception:
                return None, self._state("ROLLBACK_SELECTION_UNAVAILABLE")
        if self._held_selection_differs() and self._commit_pending_rollback(revision):
            return None, self._state("CATALOG_REFRESH_REQUIRED")
        healthy = self.worker is not None and self.worker.usable()
        if (self.pending is not None and self.pending[0] == revision
                and self.pending[1].usable()):
            return None, self._state("AWAITING_CATALOG_REFRESH")
        if not explicit and healthy and revision == self.current_revision and epoch == self.current_epoch:
            return None, self._state("CATALOG_REFRESH_REQUIRED" if self.stale_contract is not None else "UP_TO_DATE")
        if not explicit and revision == self.rejected_revision and epoch == self.rejected_epoch:
            return None, self._state("PREVIOUSLY_REJECTED")
        if revision != self.retry_revision or epoch != self.retry_epoch:
            self.retry_revision = revision
            self.retry_epoch = epoch
            self.retry_count = 0
            self.retry_at = 0.0
        now = time.monotonic()
        if not explicit and now < self.retry_at:
            return None, self._state("RETRY_DEFERRED")
        if self.retry_count >= MAX_RETRY_BURST:
            self.retry_count = 0
        self.refresh_task = asyncio.create_task(self._refresh(revision, epoch))
        return self.refresh_task, self._state("PREPARING")

    def _commit(self, revision, worker, tools, epoch):
        previous = self.worker
        self.worker = worker
        self.current_revision = revision
        self.current_epoch = epoch
        self.rejected_revision = None
        self.rejected_epoch = None
        self.retry_count = 0
        self.retry_at = 0.0
        self.tools = tools
        self.contract = catalog_contract(tools)
        return previous, self._state("RESTARTED")

    async def _refresh(self, revision: str, epoch: str) -> dict[str, Any]:
        """Prepare outside routing lock; publish changed catalogs on re-list."""
        candidate = None
        try:
            async with self.lock:
                self._discard_pending()
            candidate = Worker(await asyncio.to_thread(self.launch), self.required_calls)
            _, tools = await candidate.start()
            if self.smoke_name not in {tool.name for tool in tools}:
                raise CatalogError("missing smoke tool")
            result = await candidate.call(self.smoke_name, self.smoke_arguments)
            if result.is_error or not candidate.usable():
                raise ValueError("candidate smoke failed")
            async with self.lock:
                if (self.closed or self.revision() != revision
                        or self.rollback_epoch() != epoch or not candidate.usable()):
                    raise ValueError("selection changed or candidate unavailable")
                if epoch != self.current_epoch and revision == self.current_revision and self.updates_held():
                    raise ValueError("rollback selection has not changed")
                if catalog_contract(tools) != self.contract:
                    self.pending = (revision, candidate, tools, epoch)
                    candidate = None
                    if (self._held_selection_differs()
                            and self._commit_pending_rollback(revision)):
                        state = self._state("CATALOG_REFRESH_REQUIRED")
                    else:
                        state = self._state("AWAITING_CATALOG_REFRESH")
                else:
                    previous, state = self._commit(revision, candidate, tools, epoch)
                    candidate = None
                    self._retire(previous)
            if state["status"] in {"AWAITING_CATALOG_REFRESH", "CATALOG_REFRESH_REQUIRED"} and self.session is not None:
                try:
                    await asyncio.wait_for(self.session.send_tool_list_changed(), 5)
                except Exception:
                    # Keep the old catalog/worker until an actual list request.
                    pass
            return state
        except asyncio.CancelledError:
            raise
        except Exception as error:
            incompatible = isinstance(error, CatalogError)
            async with self.lock:
                if incompatible:
                    self.rejected_revision = revision
                    self.rejected_epoch = epoch
                else:
                    self.retry_count += 1
                    delay = (RETRY_COOLDOWN if self.retry_count >= MAX_RETRY_BURST
                             else RETRY_DELAY * 2 ** (self.retry_count - 1))
                    self.retry_at = time.monotonic() + delay
                return self._state("CANDIDATE_REJECTED" if incompatible else "RETRY_DEFERRED")
        finally:
            if candidate is not None:
                self._retire(candidate)

    def _with_runtime_status(self, result: types.CallToolResult, *, served_version=None) -> types.CallToolResult:
        """Keep domain content unchanged; publish explicit runtime metadata."""
        payload = result.model_dump(by_alias=True, exclude_none=True)
        meta = dict(payload.get("_meta") or {})
        meta["kinotch.devflow.runtime"] = {
            "status": self.last_status,
            "running_version": self.version(),
        }
        if served_version is not None:
            meta["kinotch.devflow.runtime"]["served_version"] = served_version
        payload["_meta"] = meta
        return types.CallToolResult.model_validate(payload)

    async def list_tools(self, context, _params):
        async with self.lock:
            self.session = context.session
            if self.pending is not None:
                revision, worker, tools, epoch = self.pending
                try:
                    current = self.revision()
                    current_epoch = self.rollback_epoch()
                except Exception:
                    current = None
                    current_epoch = None
                if worker.usable() and current == revision and current_epoch == epoch:
                    self.pending = None
                    previous, _ = self._commit(revision, worker, tools, epoch)
                    self._retire(previous)
                else:
                    self._discard_pending()
            self._schedule_refresh(explicit=False)
            self.stale_contract = None
            result = types.ListToolsResult(tools=[*self.tools, types.Tool(
                name=RESTART_TOOL,
                description=("Restart this MCP connection's worker on the locally selected "
                             "verified release, without restarting the AI. No GitHub write, "
                             "fetch, arbitrary command, or other connection is affected."),
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
            )])
        return result

    def _validate_call(self, params):
        tool = next((tool for tool in self.tools if tool.name == params.name), None)
        if (tool is None or not arguments_supported(tool, params.arguments or {})
                or (self.stale_contract is not None and
                    self.stale_contract.get(params.name) != self.contract.get(params.name))):
            return _reply({"status": "TOOL_CONTRACT_UNAVAILABLE", "action": "REFRESH_TOOLS_LIST"}, error=True)
        return None

    async def call_tool(self, context, params):
        self.session = context.session
        if params.name == RESTART_TOOL:
            if params.arguments:
                return _reply({"status": "INVALID_ARGUMENTS"}, error=True)
            # A coalesced refresh can have committed a different revision
            # before this request arrived (e.g. while closing its old child).
            # Re-evaluate once, rather than claim an unrelated restart succeeded.
            for _ in range(2):
                async with self.lock:
                    task, state = self._schedule_refresh(explicit=True)
                if task is not None:
                    state = await asyncio.shield(task)
                if state["status"] != "RESTARTED":
                    return _reply(state, error=True)
                async with self.lock:
                    try:
                        selected = self.revision()
                    except Exception:
                        return _reply(self._state("INVALID_SELECTION"), error=True)
                    if (self.worker is not None and self.worker.usable()
                            and selected == self.current_revision):
                        return _reply(self._state("RESTARTED"))
            return _reply(self._state("SELECTION_CHANGED"), error=True)

        worker = None
        future = None
        # Selection and enqueue are one atomic routing operation. The child
        # processes its existing queue before its retirement sentinel; no
        # request is sent to it after the swap. Never await a domain call here.
        for attempt in range(2):
            async with self.lock:
                if self.closed:
                    return _reply(self._state("CONNECTION_CLOSED"), error=True)
                task, state = self._schedule_refresh(explicit=False)
                if (self.worker is not None and self.worker.usable()
                        and not self._held_selection_differs()):
                    invalid = self._validate_call(params)
                    if invalid is not None:
                        return self._with_runtime_status(invalid)
                    worker = self.worker
                    future = worker.submit(params.name, params.arguments or {})
                    break
                if task is None or attempt:
                    if self._held_selection_differs():
                        return _reply(self._state("ROLLBACK_SELECTION_UNAVAILABLE"), error=True)
                    if state["status"] == "AWAITING_CATALOG_REFRESH":
                        return _reply(state, error=True)
                    return _reply(self._state("WORKER_UNAVAILABLE"), error=True)
            # Only an unsent request may wait for recovery.
            await asyncio.shield(task)

        assert worker is not None and future is not None
        result = await future
        async with self.lock:
            if worker is self.worker and not worker.usable():
                self._schedule_refresh(explicit=False)
            # The served version is not necessarily the current routing version.
            # A sent request is never replayed.
            return self._with_runtime_status(result, served_version=worker.launch.version)

    async def close(self):
        async with self.lock:
            self.closed = True
            task = self.refresh_task
            worker = self.worker
            pending = self.pending
            self.pending = None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        # EOF closes this connection only. Cancel outstanding child I/O; an
        # uncertain submitted request is not replayed. Normal swaps still drain.
        children = set(self.retired.values())
        if pending is not None:
            children.add(pending[1])
        if worker is not None:
            children.add(worker)
        await asyncio.gather(*(child.close(abort=True) for child in children),
                             return_exceptions=True)
        if self.retired:
            await asyncio.gather(*tuple(self.retired), return_exceptions=True)


async def serve_connection(revision: Callable[[], str], launch: Callable[[], Launch],
                           *, smoke_name: str, smoke_arguments: dict[str, Any],
                           required_calls: Mapping[str, Mapping[str, Any]] = REQUIRED_CALLS,
                           updates_held: Callable[[], bool] = lambda: False,
                           rollback_epoch: Callable[[], str] = lambda: "INITIAL") -> None:
    """Isolated pilot; the production installer is deliberately unchanged."""
    connection = Connection(revision, launch, required_calls=required_calls,
                            smoke_name=smoke_name, smoke_arguments=smoke_arguments,
                            updates_held=updates_held, rollback_epoch=rollback_epoch)
    try:
        initial = await connection.start()
        server = Server(
            initial.server_info.name, version=initial.server_info.version,
            instructions=initial.instructions,
            on_list_tools=connection.list_tools, on_call_tool=connection.call_tool,
        )
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options(NotificationOptions(tools_changed=True)))
    finally:
        await connection.close()
