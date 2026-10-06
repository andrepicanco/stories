"""Ponte MCP: mantém conexões persistentes com servidores MCP e as expõe ao harness como `Tool`.

O SDK do MCP é assíncrono e o harness é síncrono, então as conexões vivem num event loop numa
thread de fundo; as chamadas das tools atravessam para esse loop. Cada servidor tem uma tarefa que
abre o transporte e a sessão e os mantém abertos até `close()`.

Só tools somente-leitura são expostas ao agente: pela anotação `readOnlyHint` do servidor ou, na falta
dela, por uma lista explícita de nomes. Escritas (criar card, editar página) ficam fora do alcance do LLM:
quem cria o card é a interface, com a confirmação do usuário."""
import asyncio
import os
import threading
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .base import Tool
from .ontology import Effect

CONNECT_TIMEOUT = 60
CALL_TIMEOUT = 90

# Estados de conexão
DISABLED, CONNECTING, CONNECTED, ERROR, UNAUTHORIZED = "disabled", "connecting", "connected", "error", "unauthorized"


@dataclass
class ServerSpec:
    """Como conectar a um servidor MCP e como expor suas tools."""
    name: str                                   # id interno (azure_mcp, notion_mcp)
    group: str                                  # grupo de tools / checkbox (azure, notion)
    prefix: str                                 # prefixo dos nomes das tools expostas
    open_transport: Callable[[AsyncExitStack], Awaitable[tuple]]   # devolve (read, write)
    only_names: Optional[frozenset] = None      # se definido, é a lista COMPLETA do que se expõe (curadoria)
    read_only_names: frozenset = frozenset()    # liberadas mesmo sem anotação readOnlyHint
    hidden_names: frozenset = frozenset()       # ocultas (ex.: duplicadas por tools REST)
    fingerprint: str = ""                       # mudou => reconectar


@dataclass
class ServerState:
    spec: Optional[ServerSpec] = None
    state: str = DISABLED
    error: str = ""
    tools: list = field(default_factory=list)   # list[Tool]
    task: Optional[asyncio.Task] = None
    stop: Optional[asyncio.Event] = None
    session: object = None


class McpManager:
    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.servers: dict[str, ServerState] = {}

    # ---------- loop em thread de fundo ----------
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                thread = threading.Thread(target=loop.run_forever, name="mcp-loop", daemon=True)
                thread.start()
                self._loop, self._thread = loop, thread
            return self._loop

    def _run(self, coro, timeout: float):
        return asyncio.run_coroutine_threadsafe(coro, self._ensure_loop()).result(timeout)

    # ---------- configuração ----------
    def configure(self, specs: dict[str, Optional[ServerSpec]], unauthorized: dict[str, str] | None = None) -> None:
        """Alinha as conexões com as configurações atuais. Não bloqueia: conecta em segundo plano.
        `specs[nome] = None` desliga o servidor; `unauthorized[nome]` marca que falta autorização."""
        unauthorized = unauthorized or {}
        for name, spec in specs.items():
            current = self.servers.setdefault(name, ServerState())
            if spec is not None and current.spec is not None and current.spec.fingerprint == spec.fingerprint \
                    and current.state in (CONNECTING, CONNECTED):
                continue                                        # nada mudou
            self._run(self._stop_server(current), 15)
            current.spec, current.tools, current.error = spec, [], ""
            if spec is None:
                current.state = DISABLED
            elif name in unauthorized:
                current.state, current.error = UNAUTHORIZED, unauthorized[name]
            else:
                current.state = CONNECTING
                self._run(self._start_server(name, current), 5)

    def restart(self, name: str) -> None:
        """Reconecta com a configuração já guardada (ex.: depois de autorizar o Notion)."""
        state = self.servers.get(name)
        if state is None or state.spec is None:
            return
        self._run(self._stop_server(state), 15)
        state.tools, state.error, state.state = [], "", CONNECTING
        self._run(self._start_server(name, state), 5)

    async def _start_server(self, name: str, state: ServerState) -> None:
        state.stop = asyncio.Event()
        state.task = asyncio.get_running_loop().create_task(self._serve(name, state))

    async def _stop_server(self, state: ServerState) -> None:
        if state.task is not None:
            state.stop.set()
            try:
                await asyncio.wait_for(state.task, 10)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                state.task.cancel()
            state.task = state.session = None

    async def _serve(self, name: str, state: ServerState) -> None:
        from mcp import ClientSession   # import tardio: o SDK é pesado

        spec = state.spec
        try:
            async with AsyncExitStack() as stack:
                read, write = await asyncio.wait_for(spec.open_transport(stack), CONNECT_TIMEOUT)
                session = await stack.enter_async_context(ClientSession(read, write))
                await asyncio.wait_for(session.initialize(), CONNECT_TIMEOUT)
                listed = (await asyncio.wait_for(session.list_tools(), CONNECT_TIMEOUT)).tools
                state.session = session
                state.tools = self._to_tools(name, spec, listed)
                state.state, state.error = CONNECTED, ""
                await state.stop.wait()          # mantém a conexão aberta até close()/reconfigure
        except asyncio.CancelledError:
            raise
        except BaseException as err:             # noqa: BLE001 - qualquer falha vira estado de erro visível
            from integrations.notion_oauth import NotAuthorized
            cause = _root_cause(err)
            state.state = UNAUTHORIZED if isinstance(cause, NotAuthorized) else ERROR
            state.error = f"{type(cause).__name__}: {cause}"[:300]
            state.tools, state.session = [], None
        finally:
            if state.state == CONNECTED:
                state.state = DISABLED

    # ---------- tools ----------
    def _to_tools(self, name: str, spec: ServerSpec, listed) -> list[Tool]:
        tools = []
        for t in listed:
            if t.name in spec.hidden_names or (spec.only_names is not None and t.name not in spec.only_names):
                continue
            ann = getattr(t, "annotations", None)
            read_only = getattr(ann, "read_only_hint", None) if ann else None
            if read_only is None:
                read_only = t.name in spec.read_only_names
            if not read_only:
                continue                          # escritas nunca chegam ao agente
            tools.append(Tool(
                name=f"{spec.prefix}__{t.name}",
                description=(t.description or t.name)[:1000],
                schema=dict(t.input_schema or {"type": "object", "properties": {}}),
                fn=self._make_caller(name, t.name),
                effect=Effect.READ,
                group=spec.group,
            ))
        return tools

    def _make_caller(self, server: str, tool_name: str) -> Callable[..., str]:
        def call(**args) -> str:
            state = self.servers[server]
            if state.state != CONNECTED or state.session is None:
                raise RuntimeError(f"servidor MCP '{server}' indisponível ({state.state}: {state.error})")
            result = self._run(state.session.call_tool(tool_name, args), CALL_TIMEOUT)
            text = "\n".join(b.text for b in result.content if getattr(b, "text", None))
            if getattr(result, "is_error", False):
                raise RuntimeError(text or "o servidor MCP retornou erro")
            return text
        return call

    def tools(self, server: str) -> list[Tool]:
        state = self.servers.get(server)
        return list(state.tools) if state and state.state == CONNECTED else []

    # ---------- status / ciclo de vida ----------
    def status(self) -> dict[str, dict]:
        return {n: {"state": s.state, "error": s.error, "tools": len(s.tools)} for n, s in self.servers.items()}

    def wait_ready(self, timeout: float = 20.0) -> None:
        """Espera (limitado) as conexões em andamento terminarem, para a primeira geração já ter as tools."""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline and any(s.state == CONNECTING for s in self.servers.values()):
            time.sleep(0.2)

    def close(self) -> None:
        if self._loop is None:
            return
        for state in self.servers.values():
            self._run(self._stop_server(state), 15)
        loop, thread = self._loop, self._thread
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        if not loop.is_running():
            loop.close()
        self._loop = self._thread = None


def _root_cause(err: BaseException) -> BaseException:
    """Desembrulha ExceptionGroup/__cause__ do anyio para achar o erro real."""
    seen = 0
    while seen < 10:
        seen += 1
        if isinstance(err, BaseExceptionGroup) and err.exceptions:
            err = err.exceptions[0]
        elif err.__cause__ is not None:
            err = err.__cause__
        else:
            break
    return err


manager = McpManager()


# ---------- transportes ----------
def stdio_transport(command: str, args: list[str], env: dict[str, str], log_file: Path):
    async def open_transport(stack: AsyncExitStack):
        from mcp.client.stdio import StdioServerParameters, stdio_client
        log_file.parent.mkdir(parents=True, exist_ok=True)
        errlog = stack.enter_context(open(log_file, "a", encoding="utf-8"))   # logs do servidor fora do terminal
        params = StdioServerParameters(command=command, args=args, env={**os.environ, **env})
        return await stack.enter_async_context(stdio_client(params, errlog=errlog))
    return open_transport


def http_transport(url: str, token_provider: Callable[[], str]):
    async def open_transport(stack: AsyncExitStack):
        import httpx2
        from mcp.client.streamable_http import streamable_http_client

        class BearerAuth(httpx2.Auth):
            def auth_flow(self, request):
                request.headers["Authorization"] = f"Bearer {token_provider()}"   # renova se preciso
                yield request

        client = await stack.enter_async_context(httpx2.AsyncClient(auth=BearerAuth(), timeout=60))
        streams = await stack.enter_async_context(streamable_http_client(url, http_client=client))
        return streams[0], streams[1]
    return open_transport
