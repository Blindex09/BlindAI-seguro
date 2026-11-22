"""Rotas HTTP do Blind AI que expoem o catalogo MCP e as capacidades implementadas como ferramentas MCP.

A interface Electron usa /api/mcp/* (status, ferramentas, reinicio, chamada direta). As rotas de
canais e escrita mantem o contrato antigo da interface, mas por baixo chamam o servidor MCP dono.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .manager import MCPManager

router = APIRouter()


class McpCallRequest(BaseModel):
    server: str
    tool: str
    arguments: Dict[str, Any] = {}


class PairRequest(BaseModel):
    phone: str


class TelegramConnectRequest(BaseModel):
    bot_token: str


class WriterDraftRequest(BaseModel):
    title: str
    content: str
    filename: Optional[str] = None


class WriterSaveRequest(BaseModel):
    draft: Dict[str, Any]


def manager_of(request: Request) -> MCPManager:
    mgr = getattr(request.app.state, "mcp", None)
    if mgr is None:
        raise HTTPException(status_code=503, detail="Camada MCP ainda nao iniciou.")
    return mgr


def result_data(res: Dict[str, Any]) -> Any:
    """Extrai o dado util de um resultado de ferramenta (structuredContent, JSON no texto ou texto puro)."""
    structured = res.get("structured")
    if isinstance(structured, dict):
        return structured["result"] if set(structured) == {"result"} else structured
    content = res.get("content", "")
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return content


_PREFIX = re.compile(r"^Error executing tool [^:]+:\s*")


def ensure_ok(res: Dict[str, Any], status: int = 400) -> Any:
    if not res.get("ok"):
        raise HTTPException(status_code=status, detail=_PREFIX.sub("", res.get("content") or "Falha na ferramenta."))
    return result_data(res)


async def maybe_speak(request: Request, text: str) -> None:
    speak = getattr(request.app.state, "speak", None)
    if speak and text:
        await speak(text)


# ---------------------------------------------------------------- catalogo MCP
@router.get("/api/mcp/servers")
async def mcp_servers(request: Request) -> List[Dict[str, Any]]:
    return manager_of(request).status()


@router.get("/api/mcp/tools")
async def mcp_tools(request: Request) -> List[Dict[str, Any]]:
    return [
        {
            "server": t.server,
            "name": t.name,
            "description": t.description.splitlines()[0][:200] if t.description else "",
            "hidden_from_model": t.hidden_from_model,
        }
        for t in manager_of(request).list_tools()
    ]


@router.post("/api/mcp/servers/{name}/restart")
async def mcp_restart(name: str, request: Request) -> Dict[str, Any]:
    return await manager_of(request).restart(name)


@router.post("/api/mcp/call")
async def mcp_call(req: McpCallRequest, request: Request) -> Dict[str, Any]:
    res = await manager_of(request).call_tool(req.server, req.tool, req.arguments)
    return {"ok": res["ok"], "content": res["content"], "is_error": res["is_error"], "images": res["images"]}


# ---------------------------------------------------------------- atividades (diario do que o Blind fez)
@router.get("/api/activity")
async def activity(limit: int = 50, only_errors: bool = False, server: str = "") -> Dict[str, Any]:
    """Atividades recentes em frases simples (deu certo / falhou), do diario gravado pelas ferramentas do Blind."""
    from .servers import _audit

    return _audit.activity(limit=limit, only_errors=only_errors, server=server)


# ---------------------------------------------------------------- canais
@router.post("/api/whatsapp/pair")
async def whatsapp_pair(req: PairRequest, request: Request) -> Any:
    data = ensure_ok(await manager_of(request).call_tool("blind-channels", "whatsapp_pair", {"phone": req.phone}))
    if isinstance(data, dict):
        await maybe_speak(request, data.get("spoken_instructions", ""))
    return data


@router.get("/api/whatsapp/status")
async def whatsapp_status(phone: str, request: Request) -> Any:
    return ensure_ok(await manager_of(request).call_tool("blind-channels", "whatsapp_status", {"phone": phone}))


@router.post("/api/telegram/connect")
async def telegram_connect(req: TelegramConnectRequest, request: Request) -> Any:
    data = ensure_ok(
        await manager_of(request).call_tool("blind-channels", "telegram_connect", {"bot_token": req.bot_token})
    )
    if isinstance(data, dict):
        await maybe_speak(request, data.get("spoken_message", ""))
    return data


@router.get("/api/telegram/status")
async def telegram_status(request: Request) -> Dict[str, Any]:
    data = ensure_ok(await manager_of(request).call_tool("blind-channels", "telegram_status", {}))
    return {"bots": data if isinstance(data, list) else []}


# ---------------------------------------------------------------- voz (Whisper local)
class SttRequest(BaseModel):
    audio_base64: str
    language: Optional[str] = "pt"
    prompt: Optional[str] = None


@router.post("/api/stt/transcribe")
async def stt_transcribe(req: SttRequest, request: Request) -> Any:
    res = await manager_of(request).call_tool(
        "blind-stt",
        "transcribe",
        {"audio_base64": req.audio_base64, "language": req.language, "prompt": req.prompt},
        timeout=900,
    )
    return ensure_ok(res, status=502)


@router.post("/api/stt/prepare")
async def stt_prepare(request: Request) -> Any:
    return ensure_ok(await manager_of(request).call_tool("blind-stt", "prepare", {}, timeout=900), status=502)


@router.get("/api/stt/status")
async def stt_status(request: Request) -> Any:
    return ensure_ok(await manager_of(request).call_tool("blind-stt", "stt_status", {}), status=502)


# ---------------------------------------------------------------- escrita assistida
@router.post("/api/writer/draft")
async def writer_draft(req: WriterDraftRequest, request: Request) -> Any:
    data = ensure_ok(
        await manager_of(request).call_tool(
            "blind-docs", "writer_draft", {"title": req.title, "content": req.content, "filename": req.filename}
        )
    )
    if isinstance(data, dict):
        await maybe_speak(request, data.get("spoken_review", ""))
    return data


@router.post("/api/writer/save")
async def writer_save(req: WriterSaveRequest, request: Request) -> Any:
    data = ensure_ok(await manager_of(request).call_tool("blind-docs", "writer_save", {"draft": req.draft}))
    if isinstance(data, dict):
        await maybe_speak(request, data.get("confirmation_speech", ""))
    return data
