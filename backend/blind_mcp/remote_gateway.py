"""Gateway MCP remoto do Blind AI (Streamable HTTP) para o Claude no celular e na web.

O app do Claude fora do computador so aceita conectores remotos. Este gateway e SEPARADO do Blind local:
- sobe so os servidores de `mcp.remote.json` (nao o `mcp.json` do computador inteiro);
- oferece e executa so as ferramentas de `remote_allowlist.py`, que sao de leitura (nada apaga, envia, grava,
  comanda o computador, le arquivo por caminho ou abre o cofre);
- respeita as ferramentas escondidas do modelo ao chamar (`call_raw(..., from_model=True)`);
- liga a protecao contra DNS rebinding: so aceita o Host de `BLIND_REMOTE_HOSTS` (padrao: localhost e 127.0.0.1).
O gateway ouve em http://127.0.0.1:PORTA/<segredo>/mcp. O <segredo> e um token aleatorio guardado em
data/remote_token.txt: quem nao o tem recebe 404. ATENCAO: o segredo na URL ainda NAO e um login de verdade.
Antes de abrir um tunel, ponha um login com identidade na frente (OAuth ou tunel com identidade), como pediu a revisao.

Uso:  python -m blind_mcp.remote_gateway   (variaveis: BLIND_REMOTE_PORT, padrao 8770)
"""

from __future__ import annotations

import contextlib
import logging
import os
import secrets
from pathlib import Path
from typing import Any, List

import mcp.types as types
import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from .config import config_path, default_data_dir, load_specs
from .manager import MCPManager
from .remote_allowlist import allowed, clean_schema, forbidden_args, guia

logger = logging.getLogger("blind.remote")
PORT = int(os.environ.get("BLIND_REMOTE_PORT", "8770"))
COMECAR = "comecar"


def remote_config_path() -> Path:
    """O arquivo de servidores do gateway: `mcp.remote.json`, nunca o `mcp.json` do computador inteiro."""
    return Path(os.environ.get("BLIND_REMOTE_CONFIG") or (config_path().parent / "mcp.remote.json"))


def remote_hosts() -> List[str]:
    """Hosts aceitos (protecao contra DNS rebinding). Com tunel, ponha o nome dele em BLIND_REMOTE_HOSTS."""
    extra = [h.strip() for h in os.environ.get("BLIND_REMOTE_HOSTS", "").split(",") if h.strip()]
    return [f"127.0.0.1:{PORT}", f"localhost:{PORT}", *extra]


def remote_origins() -> List[str]:
    return [f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}", *[f"https://{h}" for h in os.environ.get("BLIND_REMOTE_HOSTS", "").split(",") if h.strip()]]


def load_token() -> str:
    path = default_data_dir() / "remote_token.txt"
    if path.is_file() and path.read_text(encoding="utf-8").strip():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    path.write_text(token, encoding="utf-8")
    return token


def build_app() -> Starlette:
    manager = MCPManager(specs=load_specs(remote_config_path()))
    server: Server = Server("blind")

    @server.list_tools()
    async def _list() -> List[types.Tool]:
        tools = [
            types.Tool(
                name=COMECAR,
                description="Chame primeiro quando o usuario disser 'blind' ou pedir algo do Blind AI. Devolve o guia de ferramentas e regras.",
                inputSchema={"type": "object", "properties": {"pedido": {"type": "string"}}},
            )
        ]
        for ref in manager.list_tools():
            if ref.hidden_from_model or not allowed(ref.qualified):
                continue
            tools.append(types.Tool(name=ref.qualified, description=ref.description[:1000], inputSchema=clean_schema(ref.schema)))
        return tools

    @server.call_tool()
    async def _call(name: str, arguments: dict) -> Any:
        if name == COMECAR:
            return [types.TextContent(type="text", text=guia())]
        if not allowed(name):  # a lista vale para chamar, nao so para listar
            raise RuntimeError(f"Ferramenta indisponivel pelo gateway remoto: {name}")
        proibidos = forbidden_args(arguments)
        if proibidos:  # um caminho de arquivo leria o computador: so o conteudo em base64 vale aqui
            raise RuntimeError(f"Este conector nao aceita estes argumentos: {', '.join(proibidos)}. Arquivos so por conteudo em base64.")
        result = await manager.call_raw(name, arguments, from_model=True)
        if result.isError:  # o decorador transforma excecao em isError
            raise RuntimeError("\n".join(getattr(b, "text", "") for b in result.content) or "falha na ferramenta")
        return list(result.content)

    session_manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=True,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=remote_hosts(), allowed_origins=remote_origins()),
    )
    token = load_token()

    async def handle(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    async def not_found(scope: Scope, receive: Receive, send: Send) -> None:
        await PlainTextResponse("not found", status_code=404)(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        await manager.start(wait=True)
        async with session_manager.run():
            logger.info("Gateway remoto pronto em /%s/mcp", "<segredo>")
            yield
        await manager.stop()

    class Router:
        """Aceita so /<segredo>/mcp; qualquer outro caminho (ou segredo errado) vira 404 sem pista."""

        def __init__(self) -> None:
            self.prefix = f"/{token}"

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "lifespan":
                await app(scope, receive, send)
                return
            path = scope.get("path", "")
            if scope["type"] == "http" and (path == f"{self.prefix}/mcp" or path == f"{self.prefix}/mcp/"):
                inner = dict(scope, path="/mcp", raw_path=b"/mcp")
                await handle(inner, receive, send)
            else:
                await not_found(scope, receive, send)

    app = Starlette(lifespan=lifespan, routes=[Mount("/__none__", app=not_found)])
    return Router()  # type: ignore[return-value]


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    token = load_token()
    print(f"Gateway Blind AI em http://127.0.0.1:{PORT}/{token}/mcp  (token em {default_data_dir() / 'remote_token.txt'})")
    uvicorn.run(build_app(), host="127.0.0.1", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
