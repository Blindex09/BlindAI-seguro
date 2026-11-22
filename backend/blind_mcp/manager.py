"""Gerenciador de servidores MCP do Blind AI (cliente stdio sobre o SDK oficial `mcp`).

Cada servidor roda em uma task asyncio propria, dona do contexto stdio_client/ClientSession.
Isso mantem a entrada e a saida dos escopos anyio na mesma task e permite chamar as
ferramentas a partir de qualquer rota do FastAPI.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import ServerSpec, default_data_dir, load_specs

logger = logging.getLogger("blind.mcp")

PING_INTERVAL = 5.0
PING_TIMEOUT = 10.0
PING_FAILURES_BEFORE_RESTART = 3
MAX_RECONNECTS = 3
MAX_DESC_CHARS = 400
_NAME_OK = re.compile(r"[^a-zA-Z0-9_-]")


def _describe(exc: BaseException) -> str:
    """Achata ExceptionGroup do anyio em uma mensagem curta e legivel."""
    subs = getattr(exc, "exceptions", None)
    if subs:
        return "; ".join(_describe(e) for e in subs)
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _is_closed(exc: BaseException) -> bool:
    """True quando o erro indica que o processo do servidor morreu ou o pipe fechou."""
    subs = getattr(exc, "exceptions", None)
    if subs:
        return any(_is_closed(e) for e in subs)
    names = {c.__name__ for c in type(exc).__mro__}
    if names & {"ClosedResourceError", "BrokenResourceError", "EndOfStream", "EOFError", "BrokenPipeError"}:
        return True
    return "connection closed" in str(exc).lower()


def qualified_name(server: str, tool: str) -> str:
    """Nome de funcao aceito por OpenAI/Anthropic: [a-zA-Z0-9_-]{1,64}."""
    name = _NAME_OK.sub("_", f"{server}__{tool}")
    if len(name) <= 64:
        return name
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return f"{name[:55]}_{digest}"


@dataclass
class ToolRef:
    server: str
    name: str
    qualified: str
    description: str
    schema: Dict[str, Any]
    hidden_from_model: bool = False


@dataclass
class _Runtime:
    spec: ServerSpec
    status: str = "disabled"  # disabled | starting | connected | error
    error: Optional[str] = None
    tools: List[Any] = field(default_factory=list)
    session: Optional[ClientSession] = None
    task: Optional["asyncio.Task[None]"] = None
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    dead: asyncio.Event = field(default_factory=asyncio.Event)  # conexao caiu (detectada em chamada ou ping)
    inflight: int = 0
    reconnects: int = 0
    started_at: Optional[float] = None
    log_path: Optional[str] = None


class MCPManager:
    def __init__(
        self,
        specs: Optional[List[ServerSpec]] = None,
        log_dir: Optional[Path] = None,
        max_result_chars: int = 8000,
    ) -> None:
        self._specs = [sp for sp in (specs if specs is not None else load_specs()) if not sp.client_only]
        self._log_dir = Path(log_dir) if log_dir else default_data_dir() / "logs"
        self._max_chars = max_result_chars
        self._servers: Dict[str, _Runtime] = {s.name: _Runtime(spec=s) for s in self._specs}
        self._by_qualified: Dict[str, ToolRef] = {}

    # ------------------------------------------------------------------ ciclo de vida
    async def start(self, wait: bool = True, timeout: float = 90.0) -> None:
        """Inicia todos os servidores habilitados em paralelo."""
        for rt in self._servers.values():
            if rt.spec.enabled:
                self._launch(rt)
        if wait:
            await self.wait_ready(timeout)

    def _launch(self, rt: _Runtime) -> None:
        rt.stop = asyncio.Event()
        rt.ready = asyncio.Event()
        rt.status = "starting"
        rt.error = None
        rt.reconnects = 0
        rt.task = asyncio.create_task(self._run(rt), name=f"mcp-{rt.spec.name}")

    async def wait_ready(self, timeout: float = 90.0) -> None:
        waiters = [rt.ready.wait() for rt in self._servers.values() if rt.task is not None]
        if not waiters:
            return
        try:
            await asyncio.wait_for(asyncio.gather(*waiters), timeout)
        except asyncio.TimeoutError:
            logger.warning("Tempo esgotado esperando servidores MCP; seguindo com os que subiram.")

    async def stop(self, timeout: float = 10.0) -> None:
        for rt in self._servers.values():
            rt.stop.set()
        tasks = [rt.task for rt in self._servers.values() if rt.task]
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=timeout)
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        for rt in self._servers.values():
            rt.session = None
            if rt.spec.enabled:
                rt.status = "disabled"
        self._rebuild_index()

    async def restart(self, name: str, timeout: float = 90.0) -> Dict[str, Any]:
        rt = self._servers.get(name)
        if rt is None:
            return {"ok": False, "error": f"Servidor desconhecido: {name}"}
        rt.stop.set()
        if rt.task:
            try:
                await asyncio.wait_for(asyncio.shield(rt.task), 10.0)
            except asyncio.TimeoutError:
                rt.task.cancel()
                await asyncio.gather(rt.task, return_exceptions=True)
            except Exception:
                pass
        rt.session = None
        if not rt.spec.enabled:
            rt.status = "disabled"
            return {"ok": False, "error": "Servidor desabilitado no mcp.json."}
        self._launch(rt)
        try:
            await asyncio.wait_for(rt.ready.wait(), timeout)
        except asyncio.TimeoutError:
            pass
        return {"ok": rt.status == "connected", "error": rt.error}

    # ------------------------------------------------------------------ tarefa por servidor
    async def _run(self, rt: _Runtime) -> None:
        spec = rt.spec
        attempts = 0
        while not rt.stop.is_set():
            rt.status = "starting"
            rt.dead = asyncio.Event()
            self._log_dir.mkdir(parents=True, exist_ok=True)
            log_file = open(self._log_dir / f"mcp-{spec.name}.log", "a", encoding="utf-8", errors="replace")
            rt.log_path = log_file.name
            try:
                params = StdioServerParameters(
                    command=spec.command, args=spec.args, env=spec.env or None, cwd=spec.cwd
                )
                async with stdio_client(params, errlog=log_file) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await asyncio.wait_for(session.initialize(), spec.startup_timeout)
                        rt.tools = await self._list_all(session)
                        rt.session = session
                        rt.status = "connected"
                        rt.error = None
                        rt.started_at = time.time()
                        attempts = 0
                        self._rebuild_index()
                        rt.ready.set()
                        await self._watch(rt, session)
            except asyncio.CancelledError:
                rt.status = "disabled"
                raise
            except BaseException as exc:  # noqa: BLE001 - inclui ExceptionGroup do anyio
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                rt.error = _describe(exc)
                rt.status = "error"
                logger.warning("MCP '%s' falhou: %s", spec.name, rt.error)
            finally:
                rt.session = None
                rt.tools = [] if rt.status == "error" else rt.tools
                self._rebuild_index()
                log_file.close()
                rt.ready.set()
            if rt.stop.is_set():
                break
            attempts += 1
            rt.reconnects = attempts
            if attempts > MAX_RECONNECTS:
                break
            try:
                await asyncio.wait_for(rt.stop.wait(), min(2.0 * attempts, 8.0))
            except asyncio.TimeoutError:
                pass
        if rt.status != "error":
            rt.status = "disabled"

    async def _list_all(self, session: ClientSession) -> List[Any]:
        tools: List[Any] = []
        cursor: Optional[str] = None
        while True:
            page = await session.list_tools(cursor=cursor) if cursor else await session.list_tools()
            tools.extend(page.tools)
            cursor = getattr(page, "nextCursor", None)
            if not cursor:
                return tools

    async def _watch(self, rt: _Runtime, session: ClientSession) -> None:
        failures = 0
        while True:
            waiters = [asyncio.ensure_future(rt.stop.wait()), asyncio.ensure_future(rt.dead.wait())]
            await asyncio.wait(waiters, timeout=PING_INTERVAL, return_when=asyncio.FIRST_COMPLETED)
            for w in waiters:
                w.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
            if rt.stop.is_set():
                return
            if rt.dead.is_set():
                raise RuntimeError("a conexao com o servidor MCP foi encerrada")
            if rt.inflight:
                continue  # chamada longa em andamento: nao sondar
            try:
                await asyncio.wait_for(session.send_ping(), PING_TIMEOUT)
                failures = 0
            except Exception as exc:  # noqa: BLE001
                if _is_closed(exc):
                    raise RuntimeError(f"servidor MCP encerrou ({_describe(exc)})") from exc
                failures += 1
                if failures >= PING_FAILURES_BEFORE_RESTART:
                    raise RuntimeError(f"servidor nao responde ao ping ({_describe(exc)})") from exc

    # ------------------------------------------------------------------ catalogo de ferramentas
    def _rebuild_index(self) -> None:
        index: Dict[str, ToolRef] = {}
        for rt in self._servers.values():
            if rt.status != "connected":
                continue
            blocked = set(rt.spec.disabled_tools)
            hidden = set(rt.spec.model_hidden_tools)
            for tool in rt.tools:
                if tool.name in blocked:
                    continue
                q = qualified_name(rt.spec.name, tool.name)
                schema = dict(tool.inputSchema or {})
                schema.setdefault("type", "object")
                schema.setdefault("properties", {})
                index[q] = ToolRef(
                    server=rt.spec.name,
                    name=tool.name,
                    qualified=q,
                    description=(tool.description or "").strip(),
                    schema=schema,
                    hidden_from_model=tool.name in hidden,
                )
        self._by_qualified = index

    def list_tools(self, server: Optional[str] = None) -> List[ToolRef]:
        refs = list(self._by_qualified.values())
        return [r for r in refs if server is None or r.server == server]

    def openai_tools(self, servers: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        out = []
        for ref in self.list_tools():
            if ref.hidden_from_model or (servers and ref.server not in servers):
                continue
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": ref.qualified,
                        "description": ref.description[:MAX_DESC_CHARS],
                        "parameters": ref.schema,
                    },
                }
            )
        return out

    def anthropic_tools(self, servers: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        return [
            {
                "name": t["function"]["name"],
                "description": t["function"]["description"],
                "input_schema": t["function"]["parameters"],
            }
            for t in self.openai_tools(servers)
        ]

    def status(self) -> List[Dict[str, Any]]:
        rows = []
        for rt in self._servers.values():
            if not rt.spec.enabled:
                state = "disabled"
            else:
                state = rt.status
            rows.append(
                {
                    "name": rt.spec.name,
                    "status": state,
                    "tool_count": len([r for r in self._by_qualified.values() if r.server == rt.spec.name]),
                    "error": rt.error,
                    "description": rt.spec.description,
                    "log": rt.log_path,
                }
            )
        return rows

    # ------------------------------------------------------------------ chamadas
    async def call_tool(
        self, server: str, tool: str, arguments: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        rt = self._servers.get(server)
        if rt is None:
            return self._error(f"Servidor MCP desconhecido: {server}")
        if tool in rt.spec.disabled_tools:
            return self._error(f"A ferramenta {server}/{tool} esta desabilitada no mcp.json.")
        from blind_mcp import seguranca

        try:
            seguranca.verificar_chamada(server, tool, arguments)
        except seguranca.BloqueioDeSeguranca as exc:
            return self._error(str(exc))
        if rt.status != "connected" or rt.session is None:
            return self._error(f"Servidor MCP '{server}' indisponivel ({rt.status}). {rt.error or ''}".strip())
        rt.inflight += 1
        try:
            result = await asyncio.wait_for(rt.session.call_tool(tool, arguments or {}), timeout or rt.spec.call_timeout)
        except asyncio.TimeoutError:
            return self._error(f"Tempo esgotado em {server}/{tool}.")
        except Exception as exc:  # noqa: BLE001
            if _is_closed(exc):
                rt.dead.set()  # acorda o watcher para reconectar na hora
            return self._error(f"Falha em {server}/{tool}: {_describe(exc)}")
        finally:
            rt.inflight -= 1
        return self._format(result)

    async def call_qualified(
        self, qualified: str, arguments: Optional[Dict[str, Any]] = None, from_model: bool = False
    ) -> Dict[str, Any]:
        ref = self._by_qualified.get(qualified)
        if ref is None or (from_model and ref.hidden_from_model):
            return self._error(f"Ferramenta desconhecida ou indisponivel: {qualified}")
        out = await self.call_tool(ref.server, ref.name, arguments)
        out["server"], out["tool"] = ref.server, ref.name
        return out

    async def call_raw(self, qualified: str, arguments: Optional[Dict[str, Any]] = None, from_model: bool = False) -> Any:
        """Chama a ferramenta e devolve o CallToolResult original (com imagens), para o gateway remoto.

        `from_model=True` e o caso do gateway remoto: a ferramenta escondida do modelo (`modelHiddenTools`) nao roda,
        como em `call_qualified`. Antes o gateway ignorava a lista de escondidas ao chamar."""
        ref = self._by_qualified.get(qualified)
        if ref is None or (from_model and ref.hidden_from_model):
            raise ValueError(f"Ferramenta desconhecida ou indisponivel: {qualified}")
        rt = self._servers[ref.server]
        from blind_mcp import seguranca

        seguranca.verificar_chamada(ref.server, ref.name, arguments)  # levanta BloqueioDeSeguranca (RuntimeError)
        if rt.status != "connected" or rt.session is None:
            raise RuntimeError(f"Servidor MCP '{ref.server}' indisponivel ({rt.status}).")
        rt.inflight += 1
        try:
            return await asyncio.wait_for(rt.session.call_tool(ref.name, arguments or {}), rt.spec.call_timeout)
        except Exception as exc:  # noqa: BLE001
            if _is_closed(exc):
                rt.dead.set()
            raise
        finally:
            rt.inflight -= 1

    def _format(self, result: Any) -> Dict[str, Any]:
        texts: List[str] = []
        images = 0
        for block in result.content or []:
            if getattr(block, "type", "") == "text":
                texts.append(block.text)
            elif getattr(block, "type", "") == "image":
                images += 1
        content = "\n".join(texts).strip()
        truncated = len(content) > self._max_chars
        if truncated:
            content = content[: self._max_chars] + "\n[... resultado truncado]"
        is_error = bool(getattr(result, "isError", False))
        return {
            "ok": not is_error,
            "is_error": is_error,
            "content": content,
            "images": images,
            "truncated": truncated,
            "structured": getattr(result, "structuredContent", None),
        }

    @staticmethod
    def _error(message: str) -> Dict[str, Any]:
        return {"ok": False, "is_error": True, "content": message, "images": 0, "truncated": False, "structured": None}
