"""Proxy preguicoso: carrega cada servidor do Blind SOB DEMANDA, conforme a pessoa trabalha.

O Claude abre todos os servidores de uma vez quando inicia (lento e pesado). Aqui, no lugar do servidor real, o Claude abre
este proxy minusculo. Ele:
- responde `tools/list` na hora, a partir de um cache (tools_cache/<servidor>.json), sem iniciar o servidor real;
- inicia o servidor real so na PRIMEIRA chamada de ferramenta e repassa tudo (texto, imagens, erros) sem mudar nada;
- descarrega o servidor real depois de um tempo sem uso (BLIND_LAZY_IDLE_S, padrao 15 min) e o reinicia na proxima chamada;
- "uma chama a outra": depois de ferramentas que mexem com teclado/mouse, solta na hora qualquer tecla ou botao preso
  (a protecao do vigia, sem esperar os 25 s).
Se o cache faltar, o proxy gera sozinho (sobe o servidor uma vez, le as ferramentas e guarda).

Uso: python -m blind_mcp.lazy_proxy --server <nome> [--config mcp.json] [--cache-dir pasta]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from blind_mcp.config import ServerSpec, load_specs

CACHE_DIR = Path(__file__).with_name("tools_cache")
IDLE_SECONDS = float(os.environ.get("BLIND_LAZY_IDLE_S", "900"))

# Ferramentas que apertam teclas ou mexem o mouse (de qualquer servidor): depois delas, o guarda solta o que ficar preso.
INPUT_TOOLS = {"Click", "Type", "Shortcut", "Move", "Scroll", "MultiEdit", "MultiSelect", "press_keys", "hover", "double_click"}


def cache_path(name: str, cache_dir: Optional[Path] = None) -> Path:
    return (cache_dir or CACHE_DIR) / f"{name}.json"


def _describe(exc: BaseException) -> str:
    inner = getattr(exc, "exceptions", None)
    if inner:
        return "; ".join(_describe(e) for e in inner)
    return f"{type(exc).__name__}: {exc}"


class Child:
    """O servidor real, iniciado e parado sob demanda. O contexto stdio vive numa tarefa propria (exigencia do anyio)."""

    def __init__(self, spec: ServerSpec, log_dir: Path) -> None:
        self.spec = spec
        self.log_dir = log_dir
        self.session: Optional[ClientSession] = None
        self.init_result: Any = None
        self.error: Optional[str] = None
        self.in_flight = 0
        self.last_used = time.monotonic()
        self._task: Optional[asyncio.Task] = None
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()

    async def ensure(self) -> ClientSession:
        if self.session is not None and self._task is not None and not self._task.done():
            return self.session
        if self._task is None or self._task.done():
            self._ready = asyncio.Event()
            self._stop = asyncio.Event()
            self.error = None
            self.session = None
            self._task = asyncio.create_task(self._run())
        await asyncio.wait_for(self._ready.wait(), self.spec.startup_timeout + 10)
        if self.session is None:
            raise RuntimeError(f"Nao consegui iniciar o servidor '{self.spec.name}': {self.error or 'sem detalhe'}")
        return self.session

    async def _run(self) -> None:
        log = None
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log = open(self.log_dir / f"lazy-{self.spec.name}.log", "a", encoding="utf-8", errors="replace")
            params = StdioServerParameters(command=self.spec.command, args=self.spec.args, env=self.spec.env or None,
                                           cwd=self.spec.cwd)
            async with stdio_client(params, errlog=log) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    self.init_result = await asyncio.wait_for(session.initialize(), self.spec.startup_timeout)
                    self.session = session
                    self._ready.set()
                    await self._stop.wait()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - inclui ExceptionGroup
            self.error = _describe(exc)
        finally:
            self.session = None
            self._ready.set()
            if log:
                log.close()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done() and self.session is not None

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task is not None:
            try:
                await asyncio.wait_for(task, 10)
            except BaseException:  # noqa: BLE001
                task.cancel()
        self.session = None


async def list_all_tools(session: ClientSession) -> List[types.Tool]:
    tools: List[types.Tool] = []
    cursor: Optional[str] = None
    while True:
        page = await session.list_tools(cursor=cursor) if cursor else await session.list_tools()
        tools.extend(page.tools)
        cursor = getattr(page, "nextCursor", None)
        if not cursor:
            return tools


async def build_cache(spec: ServerSpec, path: Path, log_dir: Path) -> Dict[str, Any]:
    """Sobe o servidor real uma vez, le instrucoes e ferramentas, grava o cache e desliga."""
    child = Child(spec, log_dir)
    try:
        session = await child.ensure()
        tools = await list_all_tools(session)
        init = child.init_result
        data = {
            "server": spec.name,
            "instructions": getattr(init, "instructions", None),
            "tools": [t.model_dump(mode="json", exclude_none=True, by_alias=True) for t in tools],
        }
    finally:
        await child.stop()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def load_cache(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data.get("tools"), list) and data["tools"] else None
    except Exception:  # noqa: BLE001
        return None


async def post_input_guard(api: Any = None, settle: float = 0.25, log: Any = None) -> List[str]:
    """Depois de uma ferramenta de teclado/mouse: solta na hora qualquer tecla modificadora ou botao do mouse que ficou presa."""
    try:
        if api is None:
            from blind_mcp.servers._vigia import WinApi

            api = WinApi()
        await asyncio.sleep(settle)
        released: List[str] = []
        for name in sorted(api.pressed()):
            api.release(name)
            released.append(name)
        if released and log is not None:
            log({"id": f"guarda-{time.time_ns() // 1000}", "server": "vigia", "tool": "tecla_presa_liberada",
                 "args": {"detalhe": "Solta logo apos ferramenta de teclado/mouse: " + ", ".join(released)}, "evento": "fim",
                 "ok": True, "quando": time.strftime("%Y-%m-%dT%H:%M:%S")})
        return released
    except Exception:  # noqa: BLE001 - o guarda nunca pode quebrar a chamada
        return []


def _text_of(content: List[Any]) -> str:
    return "\n".join(getattr(c, "text", "") for c in content if getattr(c, "type", "") == "text").strip()


async def serve(spec: ServerSpec, cache_dir: Optional[Path], guard_api: Any = None) -> None:
    from blind_mcp.servers._audit import write_entry

    log_dir = Path(os.environ.get("BLIND_DATA_DIR") or (Path(__file__).resolve().parent.parent / "data")) / "logs"
    child = Child(spec, log_dir)
    path = cache_path(spec.name, cache_dir)
    cache = load_cache(path)
    if cache is None:  # primeira vez (ou cache apagado): gera sozinho
        cache = await build_cache(spec, path, log_dir)

    server: Server = Server(f"blind-lazy-{spec.name}", instructions=cache.get("instructions"))
    bloqueadas = set(spec.disabled_tools)  # `disabledTools` do mcp.json: some da lista e a chamada e recusada
    tools = [types.Tool.model_validate(t) for t in cache["tools"] if t.get("name") not in bloqueadas]

    @server.list_tools()
    async def _list() -> List[types.Tool]:
        return tools

    @server.call_tool(validate_input=False)  # o servidor real valida; o proxy nao muda nada
    async def _call(name: str, arguments: Dict[str, Any]) -> Any:
        if name in bloqueadas:
            raise RuntimeError(f"A ferramenta '{name}' esta desligada neste Blind (mcp.json, disabledTools).")
        from blind_mcp import seguranca

        try:
            seguranca.verificar_chamada(spec.name, name, arguments)
        except seguranca.BloqueioDeSeguranca as exc:
            write_entry({"server": spec.name, "tool": name, "evento": "bloqueado", "erro": str(exc)[:200],
                         "quando": time.strftime("%Y-%m-%dT%H:%M:%S")})
            raise RuntimeError(str(exc)) from None
        child.in_flight += 1
        started = time.time()
        try:
            for attempt in (1, 2):
                session = await child.ensure()
                try:
                    result = await session.call_tool(name, arguments or {},
                                                     read_timeout_seconds=timedelta(seconds=spec.call_timeout))
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == 2 or "closed" not in f"{type(exc).__name__} {exc}".lower():
                        raise
                    await child.stop()  # o servidor real caiu: sobe de novo e tenta uma vez
        finally:
            child.in_flight -= 1
            child.last_used = time.monotonic()
        if name in INPUT_TOOLS:
            await post_input_guard(guard_api, log=write_entry)
        if result.isError:
            raise RuntimeError(_text_of(result.content) or "A ferramenta devolveu erro.")
        if getattr(result, "structuredContent", None) is not None:
            return result.content, result.structuredContent
        return result.content

    idle_limit = IDLE_SECONDS if spec.lazy_idle_seconds is None else spec.lazy_idle_seconds

    async def idle_watcher() -> None:
        if idle_limit <= 0:
            return  # nunca descarrega (ex.: o conector do WhatsApp precisa ficar ligado)
        interval = max(0.5, min(15.0, idle_limit / 4))
        while True:
            await asyncio.sleep(interval)
            if child.running and child.in_flight == 0 and time.monotonic() - child.last_used > idle_limit:
                await child.stop()  # libera memoria; volta sozinho na proxima chamada

    watcher = asyncio.create_task(idle_watcher())
    try:
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())
    finally:
        watcher.cancel()
        await child.stop()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True)
    ap.add_argument("--config", default=None)
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--build-cache", action="store_true", help="so gera o cache e sai")
    args = ap.parse_args(argv)
    specs = {s.name: s for s in load_specs(Path(args.config) if args.config else None)}
    spec = specs.get(args.server)
    if spec is None:
        print(f"servidor '{args.server}' nao existe no mcp.json", file=sys.stderr)
        return 2
    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    if args.build_cache:
        log_dir = Path(os.environ.get("BLIND_DATA_DIR") or (Path(__file__).resolve().parent.parent / "data")) / "logs"
        data = asyncio.run(build_cache(spec, cache_path(spec.name, cache_dir), log_dir))
        print(f"{spec.name}: {len(data['tools'])} ferramentas")
        return 0
    asyncio.run(serve(spec, cache_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
