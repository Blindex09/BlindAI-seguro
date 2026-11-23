"""Gateway MCP remoto do Blind AI (Streamable HTTP) para o Claude no celular e na web.

O app do Claude fora do computador so aceita conectores remotos. Este gateway e SEPARADO do Blind local:
- sobe so os servidores de `mcp.remote.json` (nao o `mcp.json` do computador inteiro);
- oferece e executa so as ferramentas de `remote_allowlist.py`, que sao de leitura (nada apaga, envia, grava,
  comanda o computador, le arquivo por caminho ou abre o cofre);
- respeita as ferramentas escondidas do modelo ao chamar (`call_raw(..., from_model=True)`);
- liga a protecao contra DNS rebinding: so aceita o Host de `BLIND_REMOTE_HOSTS` (padrao: localhost e 127.0.0.1).
Login: OAuth 2.1 com o GitHub, so para a conta de BLIND_REMOTE_GITHUB_USER (remote_oauth.py). O /mcp exige o token
do Claude; sem ele a resposta e 401. O caminho com segredo na URL deixou de existir.

Uso:  python -m blind_mcp.remote_gateway   (variaveis: BLIND_REMOTE_PORT, padrao 8770, e as do login em remote_oauth.py)
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any, List, Optional

import mcp.types as types
import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from .config import config_path, default_data_dir, load_specs
from .manager import MCPManager
from .remote_oauth import IdP, OAuthConfig, OAuthServer
import base64
from . import audio_tool, remote_fetch, remote_image
from .remote_allowlist import AUDIO_MAX_BYTES, BLINDAUDIO, BLINDAUDIO_SCHEMA, URL_TOOLS, allowed, clean_schema, forbidden_args, guia, with_forced
DESCRIBE = "blind-docs__describe_image"

logger = logging.getLogger("blind.remote")
PORT = int(os.environ.get("BLIND_REMOTE_PORT", "8770"))
COMECAR = "comecar"


def remote_config_path() -> Path:
    """O arquivo de servidores do gateway: `mcp.remote.json`, nunca o `mcp.json` do computador inteiro."""
    return Path(os.environ.get("BLIND_REMOTE_CONFIG") or (config_path().parent / "mcp.remote.json"))


def _extra_hosts(public_host: str = "") -> List[str]:
    extra = [h.strip() for h in os.environ.get("BLIND_REMOTE_HOSTS", "").split(",") if h.strip()]
    return [*extra, *([public_host] if public_host and public_host not in extra else [])]


def remote_hosts(public_host: str = "") -> List[str]:
    """Hosts aceitos (protecao contra DNS rebinding): local e o endereco do tunel."""
    return [f"127.0.0.1:{PORT}", f"localhost:{PORT}", *_extra_hosts(public_host)]


def remote_origins(public_host: str = "") -> List[str]:
    return [f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}", *[f"https://{h}" for h in _extra_hosts(public_host)]]


def build_app(oauth_config: Optional[OAuthConfig] = None, idp: Optional[IdP] = None, specs: Optional[list] = None):
    """O app do gateway. Sem as variaveis do login ele nao sobe: nunca ha um /mcp aberto."""
    cfg = oauth_config or OAuthConfig.from_env(default_data_dir())
    oauth = OAuthServer(cfg, idp=idp)
    manager = MCPManager(specs=specs if specs is not None else load_specs(remote_config_path()))
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
        tools.append(types.Tool(name=BLINDAUDIO, description=audio_tool.DESCRICAO, inputSchema=BLINDAUDIO_SCHEMA))
        for ref in manager.list_tools():
            if ref.hidden_from_model or not allowed(ref.qualified):
                continue
            if ref.qualified == DESCRIBE:  # o gateway mesmo entrega a imagem ao Claude, sem chave de IA
                tools.append(types.Tool(name=DESCRIBE, description=remote_image.DESCRICAO, inputSchema=remote_image.SCHEMA))
                continue
            tools.append(types.Tool(name=ref.qualified, description=ref.description[:1000], inputSchema=clean_schema(ref.schema, ref.qualified)))
        return tools

    @server.call_tool()
    async def _call(name: str, arguments: dict) -> Any:
        if name == COMECAR:
            return [types.TextContent(type="text", text=guia())]
        if name == BLINDAUDIO:  # audio em texto: o gateway mesmo transcreve, so por base64 ou link publico
            if forbidden_args(arguments):
                raise RuntimeError(f"Este conector nao aceita estes argumentos: {', '.join(forbidden_args(arguments))}. Audio so por base64 ou link publico.")
            arguments = dict(arguments or {})
            bruto = str(arguments.get("audio_base64") or "").split(",", 1)[-1]
            if len(bruto) * 3 // 4 > AUDIO_MAX_BYTES:
                raise RuntimeError("O audio e grande demais para este conector (mais de 30 MB). Mande um trecho menor ou um link publico.")
            try:
                return [types.TextContent(type="text", text=json.dumps(await audio_tool.transcrever(
                    audio_base64=arguments.get("audio_base64"), url=arguments.get("url"), language=arguments.get("language") or "pt"), ensure_ascii=False))]
            except (ValueError, FileNotFoundError) as exc:
                raise RuntimeError(str(exc)) from exc
        if not allowed(name):  # a lista vale para chamar, nao so para listar
            raise RuntimeError(f"Ferramenta indisponivel pelo gateway remoto: {name}")
        proibidos = forbidden_args(arguments)
        if proibidos:  # um caminho de arquivo leria o computador: so o conteudo em base64 vale aqui
            raise RuntimeError(f"Este conector nao aceita estes argumentos: {', '.join(proibidos)}. Arquivos so por conteudo em base64.")
        arguments = dict(arguments or {})
        link = arguments.pop("url", None) if name in URL_TOOLS else None
        if link:  # link publico da web: o gateway baixa (sem rede interna) e passa o conteudo adiante
            try:
                dados = await remote_fetch.baixar(str(link), remote_image.MAX_BYTES)
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
            arguments["image_base64" if name == DESCRIBE else "file_base64"] = base64.b64encode(dados).decode("ascii")
        if name == DESCRIBE:
            return remote_image.entregar(str(arguments.get("image_base64") or ""), arguments.get("prompt"))
        result = await manager.call_raw(name, with_forced(name, arguments), from_model=True)
        if result.isError:  # o decorador transforma excecao em isError
            raise RuntimeError("\n".join(getattr(b, "text", "") for b in result.content) or "falha na ferramenta")
        return list(result.content)

    session_manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=True,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=remote_hosts(cfg.host), allowed_origins=remote_origins(cfg.host)),
    )

    async def mcp_app(scope: Scope, receive: Receive, send: Send) -> None:
        """O /mcp so com o token do login; sem ele, 401 com o aviso de onde fazer o login."""
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        if not oauth.valid_bearer(headers.get("authorization", "")):
            await PlainTextResponse("login necessario", status_code=401, headers={"WWW-Authenticate": oauth.www_authenticate("invalid_token" if headers.get("authorization") else "")})(scope, receive, send)
            return
        await session_manager.handle_request(dict(scope, path="/mcp", raw_path=b"/mcp"), receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        await manager.start(wait=True)
        async with session_manager.run():
            logger.info("Gateway remoto pronto em %s/mcp (login: GitHub %s)", cfg.base_url, cfg.github_user)
            yield
        await manager.stop()

    web = Starlette(
        lifespan=lifespan,
        routes=[
            Route("/.well-known/oauth-protected-resource", oauth.protected_resource),
            Route("/.well-known/oauth-protected-resource/mcp", oauth.protected_resource),
            Route("/.well-known/oauth-authorization-server", oauth.metadata),
            Route("/oauth/register", oauth.register, methods=["POST"]),
            Route("/oauth/authorize", oauth.authorize),
            Route("/oauth/github/callback", oauth.github_callback),
            Route("/oauth/token", oauth.token, methods=["POST"]),
        ],
    )

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path", "") in ("/mcp", "/mcp/"):
            await mcp_app(scope, receive, send)
        else:
            await web(scope, receive, send)

    app.oauth = oauth  # type: ignore[attr-defined]  # os testes leem o estado do login
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    app = build_app()
    print(f"Gateway Blind AI em http://127.0.0.1:{PORT}  (endereco publico: {app.oauth.cfg.base_url}/mcp)")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
