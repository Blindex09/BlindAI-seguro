"""Diario de acoes do Blind AI.

Cada ferramenta propria grava uma linha ANTES de rodar ("inicio") e outra DEPOIS ("fim"). Se o computador travar no meio,
a ultima linha sem "fim" mostra o que estava em andamento. O texto digitado e o conteudo de mensagens nao sao gravados:
so o tamanho. Arquivo: <BLIND_DATA_DIR>/audit/acoes.jsonl (gira em 2 MB).
"""

from __future__ import annotations

import functools
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

from ._common import BACKEND_DIR

DATA_DIR = Path(os.environ.get("BLIND_DATA_DIR") or (BACKEND_DIR / "data"))
AUDIT_DIR = DATA_DIR / "audit"
AUDIT_FILE = AUDIT_DIR / "acoes.jsonl"
MAX_BYTES = 2 * 1024 * 1024
_LOCK = threading.Lock()

# Argumentos cujo conteudo e privado: grava so o tamanho.
_PRIVATE_ARGS = {"text", "content", "message", "bot_token", "api_key", "draft", "file_base64", "image_base64", "fields", "value",
                 "texto", "para", "cc", "assunto", "consulta", "segredo", "senha"}


def _clean_args(args: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in (args or {}).items():
        if k in _PRIVATE_ARGS:
            out[k] = f"<{len(v) if hasattr(v, '__len__') else 1} itens/caracteres>" if v else ""
        elif isinstance(v, str):
            from blind_mcp import cofre

            v = cofre.mascarar(v)  # dado sensivel nunca vai para o diario, nem em argumento "comum"
            out[k] = v if len(v) <= 80 else v[:77] + "..."
        else:
            out[k] = v if isinstance(v, (int, float, bool, type(None))) else str(type(v).__name__)
    return out


def write_entry(entry: Dict[str, Any]) -> None:
    """Grava uma linha no diario. Nunca levanta erro: o diario jamais pode derrubar uma ferramenta."""
    try:
        with _LOCK:
            AUDIT_DIR.mkdir(parents=True, exist_ok=True)
            if AUDIT_FILE.exists() and AUDIT_FILE.stat().st_size > MAX_BYTES:
                old = AUDIT_DIR / "acoes.1.jsonl"
                if old.exists():
                    old.unlink()
                AUDIT_FILE.replace(old)
            with AUDIT_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def install_audit(mcp: Any, server: str) -> None:
    """Envolve todas as ferramentas ja registradas no FastMCP com o registro de inicio/fim."""
    try:
        tools = mcp._tool_manager._tools  # noqa: SLF001 - nao ha API publica para trocar a funcao
    except Exception:  # noqa: BLE001
        return
    for tool in tools.values():
        original = tool.fn
        if getattr(original, "_blind_audited", False):
            continue
        name = tool.name

        @functools.wraps(original)
        async def wrapper(*args: Any, __orig=original, __name=name, **kwargs: Any) -> Any:
            call_id = f"{os.getpid()}-{time.time_ns() // 1000}"
            started = time.time()
            base = {"id": call_id, "server": server, "tool": __name, "pid": os.getpid(), "args": _clean_args(kwargs)}
            write_entry({**base, "evento": "inicio", "quando": time.strftime("%Y-%m-%dT%H:%M:%S")})
            try:
                result = await __orig(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                write_entry({**base, "evento": "fim", "ok": False, "erro": str(exc)[:200],
                             "ms": int((time.time() - started) * 1000), "quando": time.strftime("%Y-%m-%dT%H:%M:%S")})
                raise
            write_entry({**base, "evento": "fim", "ok": True, "ms": int((time.time() - started) * 1000),
                         "quando": time.strftime("%Y-%m-%dT%H:%M:%S")})
            return result

        wrapper._blind_audited = True  # type: ignore[attr-defined]
        tool.fn = wrapper


def read_recent(limit: int = 20, server: str = "") -> List[Dict[str, Any]]:
    """Ultimas acoes (mais recente primeiro), juntando inicio e fim. Marca 'sem_fim' quando nao houve fim."""
    limit = max(1, min(int(limit or 20), 200))
    lines: List[str] = []
    for f in (AUDIT_DIR / "acoes.1.jsonl", AUDIT_FILE):
        try:
            if f.exists():
                lines.extend(f.read_text(encoding="utf-8", errors="replace").splitlines()[-4000:])
        except Exception:  # noqa: BLE001
            continue
    calls: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for raw in lines:
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        cid = e.get("id")
        if not cid:
            continue
        if cid not in calls:
            calls[cid] = {"server": e.get("server"), "tool": e.get("tool"), "args": e.get("args"), "quando": e.get("quando"),
                          "terminou": False}
            order.append(cid)
        if e.get("evento") == "fim":
            calls[cid].update({"terminou": True, "ok": e.get("ok"), "ms": e.get("ms"), "erro": e.get("erro")})
    rows = [calls[c] for c in reversed(order) if not server or calls[c]["server"] == server]
    for r in rows:
        if not r["terminou"]:
            r["sem_fim"] = True
    return rows[:limit]


# ------------------------------ atividades em linguagem simples (tela do Electron) ------------------------------

_SERVER_LABELS = {
    "agent-desktop": "Controle de janelas", "blind-speech": "Voz", "blind-docs": "Documentos", "blind-channels": "WhatsApp e Telegram",
    "blind-memory": "Memoria", "blind-schedule": "Tarefas e lembretes", "blind-system": "Diagnostico", "blind-stt": "Ditado", "blind": "Guia do Blind",
    "blind-mail": "Gmail", "blind-drive": "Drive", "vigia": "Vigia do teclado e mouse",
}

_TOOL_PHRASES = {
    "snapshot": "Li a tela de um aplicativo", "click": "Cliquei em um botao", "type_text": "Escrevi em um campo",
    "element_action": "Fiz uma acao em um elemento", "launch_app": "Abri um aplicativo", "close_app": "Fechei um aplicativo",
    "list_windows": "Listei as janelas abertas", "screen_context": "Li o estado da tela", "descrever_janela": "Descrevi uma janela",
    "read_document": "Li um documento", "document_outline": "Li o sumario de um documento", "describe_image": "Descrevi uma imagem",
    "web_search": "Pesquisei na web", "web_read": "Li uma pagina da web", "writer_draft": "Preparei um texto",
    "writer_save": "Salvei um documento", "pdf_forms": "Li os campos de um formulario PDF", "pdf_fill": "Preenchi um formulario PDF",
    "memory_save": "Guardei uma informacao na memoria", "memory_recall": "Busquei na memoria", "blindschedule_create": "Criei um lembrete",
    "blindschedule_list": "Listei os lembretes", "blindschedule_delete": "Apaguei um lembrete", "blindschedule_snooze": "Adiei um lembrete",
    "speak": "Falei em voz alta", "telegram_send": "Mensagem do Telegram", "whatsapp_send": "Mensagem do WhatsApp", "whatsapp_contatos": "Procurei um contato do WhatsApp", "documento_acessibilidade": "Conferi a acessibilidade de um documento", "cofre_guardar": "Guardei um item no cofre", "cofre_listar": "Listei os nomes do cofre", "cofre_falar": "Falei um item do cofre", "cofre_copiar": "Copiei um item do cofre", "cofre_apagar": "Apaguei um item do cofre", "falar_em_segredo": "Falei um dado sensível em voz alta", "telegram_messages": "Li mensagens do Telegram",
    "whatsapp_pair": "Gerei o codigo do WhatsApp", "whatsapp_messages": "Li mensagens do WhatsApp", "whatsapp_status": "Conferi o WhatsApp", "saude_teclado": "Conferi teclado e mouse",
    "trabalho_nao_salvo": "Procurei trabalho nao salvo", "acoes_recentes": "Consultei o diario de atividades",
    "tecla_presa_liberada": "Soltei uma tecla ou botao preso", "tecla_presa_aviso": "Detectei uma tecla ou botao apertado por muito tempo",
    "recurso_ligado": "Um recurso de acessibilidade esta ligado", "tecla_presa_falha": "Nao consegui soltar uma tecla ou botao preso",
    "recurso_falha": "Nao consegui desligar um recurso de acessibilidade",
    "windows_mcp_inseguro_aviso": "Ha uma copia insegura do controle do Windows",
    "windows_mcp_inseguro_falha": "Nao consegui encerrar uma copia insegura",
    "recurso_desligado": "Desliguei um recurso de acessibilidade que ligou sozinho",
    "windows_mcp_inseguro_encerrado": "Encerrei uma copia insegura do controle do Windows",
}

_ERROR_HINTS = (
    ("STALE_REF", "A tela mudou. Tente de novo."),
    ("POLICY_DENIED", "A acao foi bloqueada por seguranca."),
    ("nao encontrado", "O arquivo ou item nao foi encontrado."),
    ("Tempo esgotado", "Demorou demais. Tente de novo."),
    ("timeout", "Demorou demais. Tente de novo."),
    ("Codigo de confirmacao", "Falta a confirmacao da pessoa antes de enviar."),
)


def humanize(row: Dict[str, Any]) -> Dict[str, Any]:
    """Uma frase curta e o estado (deu_certo / falhou / em_andamento) para a tela de Atividades."""
    tool = str(row.get("tool") or "")
    server = str(row.get("server") or "")
    phrase = _TOOL_PHRASES.get(tool) or tool.replace("_", " ").capitalize()
    if server == "vigia":
        detalhe = str((row.get("args") or {}).get("detalhe") or "")
        if tool.endswith("_falha"):
            state = "falhou"
        elif tool.endswith("_aviso") or tool == "recurso_ligado":
            state = "aviso"
        else:
            state = "corrigido"
        text = f"{phrase}. {detalhe}".strip()
    elif row.get("terminou") is False:
        state, text = "em_andamento", f"{phrase}: ainda em andamento ou nao terminou."
    elif row.get("ok") is False:
        erro = str(row.get("erro") or "")
        hint = next((h for k, h in _ERROR_HINTS if k.lower() in erro.lower()), "")
        state = "falhou"
        text = f"{phrase}: nao deu certo. {hint} {('Detalhe: ' + erro[:160]) if erro and not hint else ''}".strip()
    else:
        state, text = "deu_certo", f"{phrase}: deu certo."
    return {
        "quando": row.get("quando"),
        "origem": _SERVER_LABELS.get(server, server),
        "estado": state,
        "frase": text,
        "ms": row.get("ms"),
        "ferramenta": tool,
        "servidor": server,
    }


def activity(limit: int = 50, only_errors: bool = False, server: str = "") -> Dict[str, Any]:
    rows = [humanize(r) for r in read_recent(max(limit * 3, limit) if only_errors else limit, server)]
    if only_errors:
        rows = [r for r in rows if r["estado"] == "falhou"]
    rows = rows[: max(1, min(int(limit or 50), 200))]
    total = len(rows)
    falhas = sum(1 for r in rows if r["estado"] == "falhou")
    return {
        "ok": True,
        "total": total,
        "falhas": falhas,
        "resumo": (f"{total} atividades recentes, {falhas} com falha." if total else "Nenhuma atividade registrada ainda."),
        "atividades": rows,
    }
