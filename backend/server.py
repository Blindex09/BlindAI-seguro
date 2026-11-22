"""
Servidor Backend Real do Blind AI.
Baseado na arquitetura do api_server.py do Hermes Agent e no backend do OpenBot.
Conecta a interface gráfica diretamente ao motor real:
- Chamadas de IA via httpx (OpenAI, Gemini, Anthropic, OpenRouter, Ollama Cloud)
- Síntese de fala offline nativa no Windows (SAPI.SpVoice)
- Leitura real de documentos e PDFs (PyMuPDF / fitz)
"""

import os
import re
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Configurações do Blind AI
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "core"))
sys.path.insert(0, str(BASE_DIR / "core" / "utils"))

from config.settings import config
from core.providers.smart_router import get_model_metadata, infer_required_capability, smart_router
from core.channels.session_manager import session_manager

import asyncio
from contextlib import asynccontextmanager

from blind_mcp import MCPManager
from blind_mcp.agent_loop import (
    SYSTEM_PROMPT as AGENT_SYSTEM_PROMPT,
    run_anthropic_loop,
    run_openai_loop,
    wants_tools,
)
from blind_mcp.context_engine import build_compressed_history, load_persistent_memory_context
from blind_mcp.api import result_data, router as mcp_router


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Sobe a camada MCP em segundo plano (o health check responde na hora) e a encerra no desligamento."""
    application.state.mcp = MCPManager()
    application.state.speak = _speak
    mcp_start = asyncio.create_task(application.state.mcp.start(wait=False))
    from core.channels.blind_bridge import Ponte

    application.state.canais = Ponte(_chat_canal)
    application.state.canais.iniciar()
    try:
        yield
    finally:
        application.state.canais.parar()
        await mcp_start
        await application.state.mcp.stop()


app = FastAPI(title="Blind AI Server", version="2.0.0", lifespan=lifespan)
app.include_router(mcp_router)

# Habilita CORS irrestrito para conexões locais
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- SÍNTESE DE FALA NATIVA DO WINDOWS (OFFLINE) ---
# Desativada por padrão para não sobrepor nem conflitar com leitores de tela (NVDA, JAWS, etc.)
TTS_ENABLED = False

def sanitize_screen_reader_text(text: str) -> str:
    """Higieniza o texto removendo asteriscos, crases, hashtags e markdown que poluem leitores de tela."""
    if not text:
        return ""
    # Remove blocos de código com crases (``` e `)
    t = re.sub(r"```[a-zA-Z]*\n?", "", text)
    t = t.replace("```", "").replace("`", "")
    # Remove qualquer sequência de asteriscos (***, **, *)
    t = re.sub(r"\*{1,3}", "", t)
    # Remove hashtags de cabeçalho no início da linha (#, ##, ###)
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.MULTILINE)
    # Remove marcadores de lista (* ou -) no início da linha
    t = re.sub(r"^[\*\-]\s+", "", t, flags=re.MULTILINE)
    # Remove sublinhados markdown (__ ou _)
    t = re.sub(r"_{1,2}", "", t)
    # Substitui quebras de linha múltiplas por no máximo duas
    t = re.sub(r"\n{3,}", "\n\n", t)
    # Remove espaços duplos
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


async def _speak(text: str, force: bool = False):
    """Fala pelo servidor MCP blind-speech, apenas se habilitado (ou se a chamada for explícita)."""
    if not (TTS_ENABLED or force) or not text:
        return
    mgr = getattr(app.state, "mcp", None)
    if mgr is None:
        return
    res = await mgr.call_tool("blind-speech", "speak", {"text": sanitize_screen_reader_text(text)})
    if not res.get("ok"):
        print(f"[Aviso TTS]: {res.get('content')}")


# --- MODELOS DE REQUISIÇÃO ---
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    provider: str = "auto"
    model: Optional[str] = None
    api_key: Optional[str] = None
    speak: bool = False
    response_style: Optional[str] = None
    custom_instructions: Optional[str] = None


class CanaisConfigRequest(BaseModel):
    ativo: Optional[bool] = None
    cerebro: Optional[str] = None
    voz_espelho: Optional[bool] = None

class SessionCreateRequest(BaseModel):
    title: str
    source: Optional[str] = "chat"

class SpeakRequest(BaseModel):
    text: str

class PairRequest(BaseModel):
    phone: str

class DocReadRequest(BaseModel):
    file_path: Optional[str] = None
    file_base64: Optional[str] = None
    filename: Optional[str] = "documento.pdf"
    question: Optional[str] = None
    provider: Optional[str] = "auto"
    model: Optional[str] = None
    api_key: Optional[str] = None
    session_id: Optional[str] = None
    speak: bool = False


class VisionDescribeRequest(BaseModel):
    image_base64: Optional[str] = None
    file_path: Optional[str] = None
    provider: Optional[str] = "auto"
    model: Optional[str] = None
    api_key: Optional[str] = None
    prompt: Optional[str] = "Descreva com clareza todos os elementos visuais, textos e detalhes desta imagem para uma pessoa com deficiência visual."
    session_id: Optional[str] = None
    source_label: Optional[str] = "Captura da Tela Atual"
    speak: bool = False


class SessionMessageAddRequest(BaseModel):
    sender: str
    text: str
    is_user: bool = False


class WriterDraftRequest(BaseModel):
    title: str
    content: str
    filename: Optional[str] = None


class WriterSaveRequest(BaseModel):
    draft: Dict[str, Any]


class TelegramConnectRequest(BaseModel):
    bot_token: str


class DesktopInspectRequest(BaseModel):
    window_title: Optional[str] = None


class DesktopActionRequest(BaseModel):
    action: str = "click"
    target: str
    text: Optional[str] = None
    window_title: Optional[str] = None
    session_id: Optional[str] = None


# Catálogo oficial clonado do OpenBot (provider-model-options.ts) e Hermes (model-catalog.json)
OFFICIAL_MODELS_CATALOG: Dict[str, List[Dict[str, str]]] = {
    "auto": [
        {"id": "auto", "name": "Piloto Automático (escolhe o melhor modelo por tarefa e MCP)"},
    ],
    "openai": [
        {"id": "gpt-4o", "name": "GPT-4o (Multimodal - Rápido e Preciso)"},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini (Econômico e Ágil)"},
        {"id": "o1", "name": "o1 (Raciocínio Profundo)"},
        {"id": "o3-mini", "name": "o3-mini (Raciocínio Ágil)"},
        {"id": "gpt-4-turbo", "name": "GPT-4 Turbo"},
    ],
    "gemini": [
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash (Próxima Geração - Muito Rápido)"},
        {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro (Alta Capacidade Multimodal)"},
        {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash (Ágil)"},
        {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro (Janela de 2 Milhões de Tokens)"},
        {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash (Leve e Eficiente)"},
    ],
    "anthropic": [
        {"id": "claude-3-5-sonnet-latest", "name": "Claude 3.5 Sonnet (Altíssima Precisão e Código)"},
        {"id": "claude-3-5-haiku-latest", "name": "Claude 3.5 Haiku (Ultra Rápido)"},
        {"id": "claude-3-opus-latest", "name": "Claude 3 Opus (Raciocínio Complexo)"},
    ],
    "openrouter": [
        {"id": "anthropic/claude-3.5-sonnet", "name": "Claude 3.5 Sonnet (via OpenRouter)"},
        {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1 (via OpenRouter)"},
        {"id": "meta-llama/llama-3.3-70b-instruct", "name": "Llama 3.3 70B (via OpenRouter)"},
        {"id": "google/gemini-2.5-flash", "name": "Gemini 2.5 Flash (via OpenRouter)"},
        {"id": "mistralai/mistral-large-2411", "name": "Mistral Large (via OpenRouter)"},
        {"id": "qwen/qwen-2.5-72b-instruct", "name": "Qwen 2.5 72B (via OpenRouter)"},
    ],
}


# --- ROTAS DA API ---

@app.get("/api/models/{provider}")
async def get_models_for_provider(provider: str):
    """Retorna os modelos reais disponíveis para o provedor solicitado."""
    prov = provider.lower()
    models = OFFICIAL_MODELS_CATALOG.get(prov, [])
    return {"provider": prov, "models": models, "source": "official_catalog"}


@app.get("/api/router/capabilities")
async def get_router_capabilities():
    """Retorna a matriz de capacidades dos modelos (text, vision, tools) usada pelo roteador automático."""
    return {
        "status": "ok",
        "capabilities": smart_router.list_capability_matrix(config_obj=config),
    }


@app.get("/api/status")
async def get_status():
    """Verifica os serviços e modelos disponíveis."""
    return {
        "status": "ready",
        "configured_provider": config.llm_provider,
        "configured_model": config.llm_model,
        "mcp": [
            {"name": s["name"], "status": s["status"], "tool_count": s["tool_count"]}
            for s in (app.state.mcp.status() if getattr(app.state, "mcp", None) else [])
        ],
    }


@app.post("/api/speak")
async def speak_text(req: SpeakRequest):
    """Dispara a voz nativa do Windows diretamente no alto-falante."""
    await _speak(req.text, force=True)
    return {"status": "speaking", "text": req.text}


def _mcp() -> MCPManager:
    mgr = getattr(app.state, "mcp", None)
    if mgr is None:
        raise HTTPException(status_code=503, detail="Camada MCP ainda nao iniciou.")
    return mgr


def _history_messages(previous_messages: List[Dict[str, Any]], context_window: int = 128000) -> List[Dict[str, str]]:
    return build_compressed_history(previous_messages, context_window=context_window)


async def _chat_canal(chave: str, texto: str) -> str:
    """Conversa vinda do Telegram/WhatsApp: uma sessao fixa por canal, no provedor guardado em canais_blind.json."""
    from core.channels import blind_bridge as bb

    cfg = bb.config()
    sessoes = cfg.setdefault("sessoes", {})
    if chave not in sessoes:
        sessoes[chave] = session_manager.create_session(f"Canal {chave}", "canal")["id"]
        bb.salvar_config(cfg)
    res = await chat_inference(ChatRequest(message=texto, session_id=sessoes[chave],
                                           provider=cfg["provider"], model=cfg["model"]))
    return str(res.get("reply") or "Pronto.")


@app.get("/api/canais")
async def canais_estado():
    from core.channels import blind_bridge as bb

    return bb.estado()


@app.post("/api/canais/config")
async def canais_configurar_http(req: CanaisConfigRequest):
    from core.channels import blind_bridge as bb

    cfg = bb.config()
    if req.ativo is not None:
        cfg["ativo"] = bool(req.ativo)
    if req.cerebro in ("claude", "local"):
        cfg["cerebro"] = req.cerebro
    if req.voz_espelho is not None:
        cfg["voz_espelho"] = bool(req.voz_espelho)
    bb.salvar_config(cfg)
    return bb.estado()


@app.post("/api/canais/telegram/codigo")
async def canais_codigo_telegram():
    from core.channels import blind_bridge as bb

    return bb.gerar_codigo_vinculo()


def _build_user_preferences_block(response_style: Optional[str], custom_instructions: Optional[str]) -> str:
    parts: List[str] = []
    style = (response_style or "").strip().lower()
    if style == "curto":
        parts.append("PREFERÊNCIA DO USUÁRIO: Responda de forma curta, objetiva e direta (ideal para leitura em voz alta).")
    elif style == "detalhado":
        parts.append("PREFERÊNCIA DO USUÁRIO: Explique com mais detalhes e passo a passo claro, ainda sem formatação markdown visual.")
    clean_custom = sanitize_screen_reader_text((custom_instructions or "").strip())[:1500]
    if clean_custom:
        parts.append(f"INSTRUÇÕES PERSONALIZADAS DO USUÁRIO:\n{clean_custom}")
    return ("\n\n" + "\n\n".join(parts)) if parts else ""


@app.post("/api/chat")
async def chat_inference(req: ChatRequest):
    """Envia a mensagem para o modelo (local ou nuvem). Ações no computador usam tool calling nativo sobre MCP."""
    provider = req.provider.lower()
    model = (req.model or "").strip()
    user_msg = req.message.strip()
    session_id = req.session_id

    if not user_msg:
        raise HTTPException(status_code=400, detail="Mensagem vazia.")

    previous_messages = session_manager.get_messages(session_id) if session_id else []
    if session_id:
        session_manager.add_message(session_id, "Você", user_msg, is_user=True)

    mcp = _mcp()

    needs_tools = wants_tools(user_msg)
    if needs_tools:
        await mcp.wait_ready(timeout=30)
        needs_tools = bool(mcp.openai_tools())

    memory_block = load_persistent_memory_context()
    from blind_mcp import habilidades as _habilidades

    prefs_block = _build_user_preferences_block(req.response_style, req.custom_instructions)
    effective_system_prompt = AGENT_SYSTEM_PROMPT + _habilidades.bloco_para(user_msg) + memory_block + prefs_block
    custom_key = req.api_key.strip() if req.api_key else ""

    async def _execute_provider_candidate(cand_provider: str, cand_model: str, _prompt: str) -> Dict[str, Any]:
        cand_window = get_model_metadata(cand_provider, cand_model).get("context_window", 128000)
        history = _history_messages(previous_messages, context_window=cand_window)
        # 1. Anthropic Messages API (tool_use nativo)
        if cand_provider == "anthropic":
            key = custom_key or getattr(config, "anthropic_api_key", "") or os.getenv("ANTHROPIC_API_KEY", "")
            if not key:
                raise RuntimeError("Chave da Anthropic não configurada.")
            ant_headers = {"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"}
            async with httpx.AsyncClient(timeout=60.0) as ant_client:
                text, actions = await run_anthropic_loop(
                    ant_client,
                    ant_headers,
                    cand_model or "claude-3-5-sonnet-latest",
                    effective_system_prompt,
                    history + [{"role": "user", "content": user_msg}],
                    mcp,
                    needs_tools,
                )
            return _finish_candidate("anthropic", text, actions)

        # 3. Rotas compatíveis com OpenAI Chat Completions
        endpoint = ""
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        effective_model = cand_model
        key_override = custom_key if cand_provider == provider else ""

        if cand_provider == "ollama_cloud":
            endpoint = "https://ollama.com/v1/chat/completions"
            key = key_override or getattr(config, "ollama_api_key", "") or os.getenv("OLLAMA_API_KEY", "").strip()
            if not key:
                raise RuntimeError("Chave OLLAMA_API_KEY não configurada.")
            headers["Authorization"] = f"Bearer {key}"
            effective_model = effective_model or "kimi-k2.7-code"
        elif cand_provider == "free_cloud":
            endpoint = "https://text.pollinations.ai/openai"
            effective_model = effective_model or "openai"
        elif cand_provider in ("openai", "gemini", "openrouter"):
            cfg = {
                "openai": ("https://api.openai.com/v1/chat/completions", config.openai_api_key, "OPENAI_API_KEY", "OpenAI"),
                "gemini": (
                    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                    config.gemini_api_key,
                    "GEMINI_API_KEY",
                    "Google Gemini",
                ),
                "openrouter": (
                    "https://openrouter.ai/api/v1/chat/completions",
                    config.openrouter_api_key,
                    "OPENROUTER_API_KEY",
                    "OpenRouter",
                ),
            }[cand_provider]
            endpoint = cfg[0]
            key = key_override or cfg[1] or os.getenv(cfg[2], "")
            if not key:
                raise RuntimeError(f"Chave do {cfg[3]} não configurada.")
            headers["Authorization"] = f"Bearer {key}"
        else:
            raise RuntimeError(f"Provedor desconhecido: {cand_provider}")

        payload = {
            "model": effective_model,
            "messages": [{"role": "system", "content": effective_system_prompt}]
            + history
            + [{"role": "user", "content": user_msg}],
            "temperature": 0.4,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            text, actions = await run_openai_loop(client, endpoint, headers, payload, mcp, needs_tools, user_msg)
        return _finish_candidate(cand_provider, text, actions)

    def _finish_candidate(name: str, text: str, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        reply_txt = sanitize_screen_reader_text(text)
        if not reply_txt and not actions:
            raise RuntimeError(f"{name} retornou resposta vazia.")
        if not reply_txt and actions:
            reply_txt = actions[-1]["message"] or "Ação executada."
        return {"reply": reply_txt, "actions": actions}

    try:
        routed_res = await smart_router.execute_with_failover(
            prompt=user_msg,
            preferred_provider=provider,
            preferred_model=model,
            executor_fn=_execute_provider_candidate,
            needs_tools=needs_tools,
            required_capability=infer_required_capability(user_msg, needs_tools=needs_tools),
            config_obj=config,
        )
        res_data = routed_res["result"]
        reply = res_data["reply"]
        actions = res_data.get("actions", [])

        if session_id and reply:
            session_manager.add_message(session_id, "Blind AI", reply, is_user=False)
        if req.speak and reply:
            await _speak(reply)

        return {
            "status": "success",
            "reply": reply,
            "provider": routed_res["provider"],
            "model": routed_res["model"],
            "routed_from": routed_res.get("routed_from"),
            "fallback_used": routed_res.get("fallback_used", False),
            "action_performed": actions[-1] if actions else None,
            "actions": actions,
            "steps_executed": len(actions),
        }
    except Exception as e:
        if req.speak:
            await _speak("Ocorreu uma falha na comunicação com a inteligência artificial.")
        return {"status": "error", "reply": f"Falha na comunicação com os provedores de IA: {str(e)}"}


@app.post("/api/docs/read")
async def read_document(req: DocReadRequest):
    """Lê um PDF (servidor MCP blind-docs), e gera uma síntese acessível com a IA."""
    if not req.file_base64 and not (req.file_path and os.path.exists(req.file_path)):
        raise HTTPException(status_code=400, detail="Nenhum arquivo ou conteúdo fornecido.")
    res = await _mcp().call_tool(
        "blind-docs", "read_document", {"file_path": req.file_path, "file_base64": req.file_base64}
    )
    if not res.get("ok"):
        raise HTTPException(status_code=500, detail=f"Erro ao extrair PDF: {res.get('content')}")
    data = result_data(res)
    filename = data.get("filename") or req.filename or "documento.pdf"
    text = (data.get("text") or "").strip()

    if not text:
        summary = f"O arquivo {filename} foi aberto, mas não contém texto digital legível (pode ser um documento digitalizado como imagem pura)."
        if req.speak:
            await _speak(summary)
        return {"status": "warning", "filename": filename, "summary": summary, "total_words": 0}

    summary = sanitize_screen_reader_text(f"Documento {filename} lido com sucesso. Total a pagar e detalhes: {text}")

    if req.session_id and summary:
        session_manager.add_message(req.session_id, f"Smart Audio Desk ({filename})", summary, is_user=False)
    if req.speak:
        await _speak(summary)
    return {
        "status": "success",
        "filename": filename,
        "total_words": data.get("total_words", len(text.split())),
        "summary": summary,
        "preview": text[:500],
        "extracted_text": text,
    }


@app.post("/api/vision/describe")
async def describe_vision(req: VisionDescribeRequest):
    """Audiodescrição acessível de imagem (servidor MCP blind-docs) e fala opcional."""
    mcp = _mcp()
    effective_prompt = req.prompt
    file_path = req.file_path
    is_screen = bool(req.source_label and "tela" in req.source_label.lower())
    if is_screen and not req.image_base64 and not file_path:
        # Sem imagem do cliente: a captura vem do MCP agent-desktop (comando oficial `screenshot`).
        import tempfile
        import uuid
        shot_path = os.path.join(tempfile.gettempdir(), f"blind_tela_{uuid.uuid4().hex[:8]}.png")
        shot = await mcp.call_tool("agent-desktop", "screenshot", {"path": shot_path}, timeout=30)
        if not shot.get("ok") or not os.path.exists(shot_path):
            raise HTTPException(
                status_code=503,
                detail=f"O agent-desktop não conseguiu capturar a tela: {shot.get('content') or 'sem detalhes'}",
            )
        file_path = shot_path
    if is_screen:
        ctx = await mcp.call_tool("agent-desktop", "screen_context", {})
        gt_ctx = result_data(ctx) if ctx.get("ok") else ""
        if gt_ctx:
            base_p = effective_prompt or "Descreva esta tela de forma clara, estruturada e acessível para uma pessoa com deficiência visual."
            effective_prompt = (
                f"{base_p}\n\n"
                "REGRA ESTRITA: Descreva EXCLUSIVAMENTE o que aparece visualmente na imagem capturada. "
                "NÃO descreva janelas de segundo plano que não estejam visíveis na imagem. "
                "Use os dados de acessibilidade abaixo apenas como apoio caso correspondam à mesma janela exibida na imagem:\n"
                f"{gt_ctx}"
            )
    args = {
        "file_path": file_path,
        "image_base64": req.image_base64,
        "prompt": effective_prompt,
        "provider": req.provider or "auto",
        "model": req.model,
        "api_key": req.api_key,
    }
    res = await mcp.call_tool("blind-docs", "describe_image", args, timeout=120)
    if not res.get("ok"):
        raise HTTPException(status_code=502, detail=f"Falha na audiodescrição: {res.get('content')}")
    description = sanitize_screen_reader_text(str(result_data(res)))

    if req.session_id and description:
        lbl = req.source_label or "Captura da Tela Atual"
        session_manager.add_message(req.session_id, f"Audiodescrição ({lbl})", description, is_user=False)
    if req.speak:
        await _speak(description)
    return {"status": "success", "description": description}


# --- ROTAS DE GESTÃO DE SESSÕES E HISTÓRICO DE CHAT ---
@app.post("/api/sessions")
async def create_new_session(req: SessionCreateRequest):
    """Cria uma nova sessão de conversa para organizar tópicos de chat ou saídas de ferramentas."""
    return session_manager.create_session(req.title, req.source or "chat")


@app.get("/api/sessions")
async def list_all_sessions(limit: int = 30):
    """Lista as conversas salvas no SQLite ordenadas pelas mais recentes."""
    return {"sessions": session_manager.list_sessions(limit=limit)}


@app.get("/api/sessions/{session_id}/messages")
async def get_session_history(session_id: str):
    """Recupera o histórico completo de mensagens de uma conversa específica."""
    return {"session_id": session_id, "messages": session_manager.get_messages(session_id)}


@app.post("/api/sessions/{session_id}/messages")
async def add_message_to_session(session_id: str, req: SessionMessageAddRequest):
    """Insere manualmente uma mensagem no histórico da conversa especificada."""
    session_manager.add_message(session_id, req.sender, req.text, req.is_user)
    return {"status": "success", "session_id": session_id}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Remove uma conversa do histórico SQLite."""
    session_manager.delete_session(session_id)
    return {"status": "success", "session_id": session_id}


# A interface vive no aplicativo Electron (src/renderer) e fala com este servidor por IPC.
# Esta rota existe só para diagnóstico: abrir o endereço no navegador mostra como usar o app.
@app.get("/")
async def root_info():
    return {
        "app": "Blind AI",
        "role": "backend",
        "ui": "A interface é o aplicativo Electron (pasta src/renderer). Abra o Blind AI pelo aplicativo.",
        "status": "/api/status",
        "mcp": "/api/mcp/servers",
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("BLIND_PORT", "8765"))
    print("\n" + "=" * 65)
    print(" [BLIND AI SERVER] - MOTOR REAL DE ACESSIBILIDADE")
    print(f" Interface Acessivel: http://127.0.0.1:{port}")
    print("=" * 65 + "\n")
    # Somente loopback: este servidor controla o computador e nao pode ficar exposto na rede local.
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
