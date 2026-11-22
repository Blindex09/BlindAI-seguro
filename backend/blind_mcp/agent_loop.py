"""Loop de agente com tool calling NATIVO sobre MCP.

Substitui o antigo parsing de tags `[TOOL: ...]` no texto do modelo. O modelo recebe o catalogo
real de ferramentas MCP, devolve tool_calls estruturados, o Blind AI executa no servidor MCP
dono da ferramenta e devolve o resultado real para o modelo conferir. Uma acao so conta como
feita se houve tool_call com resultado ok; se o modelo afirma ter agido sem chamar ferramenta,
o Blind AI o corrige uma vez e depois entrega uma resposta honesta.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .context_engine import prune_tool_messages
from .manager import MCPManager

MAX_STEPS = 8

_DESKTOP_HINT = re.compile(
    r"\b(abr\w*|fech\w*|clic\w*|toqu\w*|aperte|pression\w*|digit\w*|escrev\w*|traga|tragam|foco|"
    r"janela\w*|tela|bandeja|[ií]cone\w*|programa\w*|aplicativ\w*|app|apps|youtube|toc\w+|reproduz\w*|"
    r"copi\w*|cola\w*|processo\w*|minimiz\w*|maximiz\w*|rol\w*|menu|bot[aã]o|clipboard|"
    r"[aá]rea de transfer[eê]ncia|volume|mouse|teclado|atalho\w*|captur\w*|screenshot|notifica\w*)\b",
    re.IGNORECASE,
)
_DOCS_WEB_HINT = re.compile(
    r"\b(pdf|documento\w*|formul[aá]rio\w*|preench\w*|fatura\w*|boleto\w*|arquivo\w*|pasta\w*|"
    r"leia|ler|site|p[aá]gina|web|not[ií]cia\w*|pesquis\w*|busc\w*|navegador|resum\w*)\b",
    re.IGNORECASE,
)
_CHANNELS_HINT = re.compile(
    r"\b(whats\w*|winzapp|telezapp|telegram|envi\w*|mand\w*|mensagen\w*|conversa\w*|[aá]udio\w*|fotos?|descrev\w*|"
    r"calend[aá]rio|agenda|drive|gmail|e-?mails?|google|reuni[aã]o|reuni[oõ]es|evento\w*)\b",
    re.IGNORECASE,
)
_MEMORY_HINT = re.compile(
    r"\b(lembr\w*|memor\w*|agend\w*|hist[oó]rico|salve|guarde|esquec\w*)\b",
    re.IGNORECASE,
)


def select_relevant_servers(message: str) -> Optional[List[str]]:
    """Filtra os servidores MCP relevantes para a intencao do usuario (Tool Scoping).
    Evita despejar 71 esquemas de ferramentas de uma vez quando o pedido e especifico,
    aumentando a velocidade e a precisao de modelos menores ou em nuvem."""
    text = message or ""
    selected: List[str] = ["blind-memory", "blind-schedule", "blind-speech"]
    if _DESKTOP_HINT.search(text):
        selected.extend(["agent-desktop", "windows"])
    if _DOCS_WEB_HINT.search(text):
        selected.append("blind-docs")
    if _CHANNELS_HINT.search(text):
        selected.append("blind-channels")
    if _MEMORY_HINT.search(text):
        selected.extend(["blind-memory", "blind-schedule"])
    # Se o pedido for amplo e nao casar especificamente com nenhum subgrupo, libera todos
    if len(selected) <= 3 and not _MEMORY_HINT.search(text):
        return None
    return list(dict.fromkeys(selected))

# Pedidos que provavelmente exigem agir no computador. Conversa comum nao paga o custo
# de enviar dezenas de definicoes de ferramentas a cada mensagem.
_ACTION_HINT = re.compile(
    r"\b(abr\w*|fech\w*|clic\w*|toqu\w*|aperte|pression\w*|digit\w*|escrev\w*|envi\w*|mand\w*|"
    r"traga|tragam|foco|janela\w*|tela|bandeja|[ií]cone\w*|programa\w*|aplicativ\w*|app|apps|"
    r"whats\w*|winzapp|telezapp|telegram|youtube|toc\w+|reproduz\w*|copi\w*|cola\w*|"
    r"arquivo\w*|pasta\w*|leia|ler|fal\w+|diga|descrev\w*|captur\w*|screenshot|notifica\w*|"
    r"processo\w*|minimiz\w*|maximiz\w*|rol\w*|navegador|pesquis\w*|busc\w*|menu|bot[aã]o|"
    r"clipboard|[aá]rea de transfer[eê]ncia|volume|mouse|teclado|atalho\w*|ativ\w+|"
    r"pdf|documento\w*|formul[aá]rio\w*|preench\w*|site|p[aá]gina|web|not[ií]cia\w*|"
    r"lembr\w*|memor\w*|agend\w*|hist[oó]rico|conversa\w*|fatura\w*|boleto\w*|[aá]udio\w*|fotos?)\b",
    re.IGNORECASE,
)

_CLAIMS_ACTION = re.compile(
    r"\b(pronto|feito|abri|abriu|cliquei|clicou|enviei|enviou|executei|executou|digitei|fechei|"
    r"toquei|minimizei|maximizei|traze?ndo|copiei|colei)\b",
    re.IGNORECASE,
)

SYSTEM_PROMPT = (
    "Voce e o Blind AI, assistente pessoal e de acessibilidade para pessoas com deficiencia visual. "
    "Responda em portugues, com clareza e empatia, em texto simples: sem asteriscos, crases, hashtags "
    "ou marcadores, porque leitores de tela soletram esses simbolos.\n"
    "Voce controla o computador e apoia a acessibilidade usando as ferramentas MCP disponiveis. Regras:\n"
    "1. So diga que abriu, clicou, enviou, agendou ou executou algo depois de chamar a ferramenta e ver resultado ok. "
    "Se a ferramenta falhar ou nao existir, diga isso com honestidade.\n"
    "2. Para saber o que esta na tela ou na bandeja, use agent-desktop (snapshot, screen_context, list_windows, list_tray) "
    "ou windows (Snapshot). Nao adivinhe nomes de icones, botoes ou janelas.\n"
    "3. Para interagir com qualquer aplicativo ou janela: inspecione a arvore (snapshot/find), execute a acao no elemento "
    "(@ref_id ou coordenada/atalho) e verifique o resultado.\n"
    "4. Para PDFs (inclusive escaneados com OCR, formularios preenchiveis ou juntar/dividir) e leitura limpa de paginas web "
    "sem anuncios, use blind-docs (read_document, pdf_forms, pdf_fill, pdf_merge_split, web_search, web_read).\n"
    "5. Para lembrar preferencias/dados da pessoa ou buscar em conversas antigas, use blind-memory (memory_save, "
    "memory_recall, session_search). Para tarefas e lembretes falados, use blind-schedule (blindschedule_create, blindschedule_list, blindschedule_snooze, blindschedule_delete).\n"
    "6. Para descrever fotos ou transcrever audios recebidos no Telegram/WhatsApp, use blind-channels.\n"
    "7. Se o pedido nao exigir ferramenta, responda direto."
)

NUDGE = (
    "Voce descreveu uma acao como concluida, mas nao chamou nenhuma ferramenta. Chame a ferramenta "
    "correspondente agora. Se nao existir ferramenta para isso, diga com honestidade o que nao e possivel fazer."
)

NO_TOOL_HONEST = (
    "Nao consegui executar essa acao: o modelo nao chamou nenhuma ferramenta do computador, "
    "entao nada foi feito. Tente de novo ou escolha outro modelo com suporte a ferramentas."
)


def wants_tools(message: str) -> bool:
    return bool(_ACTION_HINT.search(message or ""))


def claims_action(text: str) -> bool:
    return bool(_CLAIMS_ACTION.search(text or ""))


def result_for_model(res: Dict[str, Any]) -> str:
    body = res.get("content") or ""
    if res.get("is_error"):
        return f"ERRO: {body}".strip()
    extra = f"\n[{res['images']} imagem(ns) omitida(s)]" if res.get("images") else ""
    return (body or "ok") + extra


def _action_record(name: str, args: Dict[str, Any], res: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tool": res.get("tool") or name,
        "server": res.get("server"),
        "arguments": args,
        "status": "success" if res.get("ok") else "error",
        "action": res.get("tool") or name,
        "message": (res.get("content") or "")[:300],
    }


def _parse_args(raw: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    if isinstance(raw, dict):
        return raw, None
    try:
        parsed = json.loads(raw or "{}")
        return (parsed if isinstance(parsed, dict) else {}), None
    except json.JSONDecodeError as exc:
        return {}, f"argumentos JSON invalidos: {exc}"


async def run_openai_loop(
    client: httpx.AsyncClient,
    endpoint: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    manager: MCPManager,
    use_tools: bool,
    user_message: str,
    max_steps: int = MAX_STEPS,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Loop para provedores compativeis com OpenAI Chat Completions (Ollama, LM Studio, OpenAI, Gemini, OpenRouter)."""
    messages = list(payload["messages"])
    scoped_servers = select_relevant_servers(user_message) if use_tools else None
    tools = (manager.openai_tools(scoped_servers) or manager.openai_tools()) if use_tools else []
    actions: List[Dict[str, Any]] = []
    nudged = False
    tools_rejected = False

    for _ in range(max_steps):
        messages = prune_tool_messages(messages)
        body = {**payload, "messages": messages}
        if tools and not tools_rejected:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        r = await client.post(endpoint, json=body, headers=headers)
        if r.status_code in (400, 422) and "tools" in body:
            tools_rejected = True
            body.pop("tools", None)
            body.pop("tool_choice", None)
            r = await client.post(endpoint, json=body, headers=headers)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        msg = r.json()["choices"][0]["message"]
        calls = msg.get("tool_calls") or []

        if not calls:
            text = (msg.get("content") or "").strip()
            if use_tools and not actions and claims_action(text):
                if not nudged and not tools_rejected:
                    nudged = True
                    messages.append({"role": "assistant", "content": text})
                    messages.append({"role": "user", "content": NUDGE})
                    continue
                return NO_TOOL_HONEST, actions
            return text, actions

        messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": calls})
        for call in calls:
            fn = call.get("function") or {}
            args, err = _parse_args(fn.get("arguments"))
            if err:
                res = {"ok": False, "is_error": True, "content": err, "images": 0}
            else:
                res = await manager.call_qualified(fn.get("name", ""), args, from_model=True)
            actions.append(_action_record(fn.get("name", ""), args, res))
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result_for_model(res)})

    return "Cheguei ao limite de passos sem concluir. Diga se devo continuar.", actions


async def run_anthropic_loop(
    client: httpx.AsyncClient,
    headers: Dict[str, str],
    model: str,
    system: str,
    messages: List[Dict[str, Any]],
    manager: MCPManager,
    use_tools: bool,
    max_steps: int = MAX_STEPS,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Loop para a Anthropic Messages API com tool_use/tool_result."""
    messages = list(messages)
    tools = manager.anthropic_tools() if use_tools else []
    actions: List[Dict[str, Any]] = []
    nudged = False

    for _ in range(max_steps):
        body: Dict[str, Any] = {"model": model, "max_tokens": 2048, "system": system, "messages": messages}
        if tools:
            body["tools"] = tools
        r = await client.post("https://api.anthropic.com/v1/messages", json=body, headers=headers)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        blocks = r.json().get("content", [])
        text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        uses = [b for b in blocks if b.get("type") == "tool_use"]

        if not uses:
            if use_tools and not actions and claims_action(text):
                if not nudged:
                    nudged = True
                    messages.append({"role": "assistant", "content": text})
                    messages.append({"role": "user", "content": NUDGE})
                    continue
                return NO_TOOL_HONEST, actions
            return text, actions

        messages.append({"role": "assistant", "content": blocks})
        results = []
        for use in uses:
            args = use.get("input") or {}
            res = await manager.call_qualified(use.get("name", ""), args, from_model=True)
            actions.append(_action_record(use.get("name", ""), args, res))
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": use.get("id", ""),
                    "content": result_for_model(res),
                    "is_error": bool(res.get("is_error")),
                }
            )
        messages.append({"role": "user", "content": results})

    return "Cheguei ao limite de passos sem concluir. Diga se devo continuar.", actions


def _extract_json_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """Extrai um pedido estruturado de ferramenta `{"tool_call": {"name": ..., "arguments": ...}}` da resposta."""
    if not text or "tool_call" not in text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = text[start : end + 1]
    try:
        obj = json.loads(snippet)
        tc = obj.get("tool_call") if isinstance(obj, dict) else None
        if isinstance(tc, dict) and isinstance(tc.get("name"), str) and tc["name"].strip():
            args = tc.get("arguments")
            return {"name": tc["name"].strip(), "arguments": args if isinstance(args, dict) else {}}
    except Exception:
        return None
    return None
