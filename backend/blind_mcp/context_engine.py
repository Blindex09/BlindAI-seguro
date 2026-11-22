"""Motor de Contexto, Compressao Head+Tail, Poda de Ferramentas MCP e Injecao de Memoria.

Inspirado em `agent/context_compressor.py` e `agent/context_compressor_prune.py` do Hermes Agent:
1. Protecao de Inicio e Fim (Head + Tail): nunca descarta as primeiras mensagens da sessao
   (que definem o objetivo, fatura ou tela analisada) nem as mensagens mais recentes.
2. Compactacao Deterministica do Meio: quando a conversa cresce alem da janela ideal, resume
   os turnos intermediarios preservando valores monetarios, nomes de programas, datas e fatos.
3. Poda Proativa de Resultados de Ferramentas (Proactive Tool-Result Prune):
   - Desduplicacao sem perdas de resultados identicos de ferramentas MCP (ex.: snapshots repetidos).
   - Compactacao de resultados antigos gigantes de ferramentas, mantendo o topo e o final.
4. Injecao Automatica de Memoria de Longo Prazo (`blind-memory`): carrega os fatos salvos no
   SQLite para que nenhum modelo perca o contexto do usuario ao trocar de sessao ou de provedor.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

CHARS_PER_TOKEN = 4
_KEY_FACT_RE = re.compile(
    r"(R\$\s*[\d.,]+|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d+[.,]\d+\b|vencimento|total|fatura|janela|programa|software|erro|conclu[ií]d)",
    re.IGNORECASE,
)


def estimate_tokens(text: str) -> int:
    """Estimativa rapida de tokens (aprox. 4 caracteres por token)."""
    return max(1, len(text or "") // CHARS_PER_TOKEN)


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    total += estimate_tokens(str(part.get("text") or part.get("content") or ""))
        if m.get("tool_calls"):
            total += estimate_tokens(str(m.get("tool_calls")))
    return total


def elide_middle(text: str, max_chars: int = 600) -> str:
    """Compacta um texto grande mantendo o inicio e o fim intactos (estilo Hermes elide_middle)."""
    if not text or len(text) <= max_chars:
        return text
    half = max(120, (max_chars - 60) // 2)
    omitted = len(text) - (half * 2)
    return f"{text[:half].rstrip()}\n[... {omitted} caracteres intermediarios compactados ...]\n{text[-half:].lstrip()}"


def summarize_middle_turns(middle_messages: List[Dict[str, Any]], max_summary_chars: int = 1800) -> str:
    """Gera um resumo deterministico dos turnos intermediarios preservando fatos, valores e decisoes."""
    highlights: List[str] = []
    for m in middle_messages:
        role = "Usuário" if m.get("is_user") or m.get("role") == "user" else (m.get("sender") or "Blind AI")
        text = str(m.get("text") or m.get("content") or "").strip()
        if not text:
            continue
        # Se a mensagem contem fatos chave (valores, datas, nomes de janelas/faturas), preserva mais contexto
        if _KEY_FACT_RE.search(text):
            snippet = elide_middle(text, 280)
        else:
            snippet = elide_middle(text, 140)
        highlights.append(f"- {role}: {snippet}")

    joined = "\n".join(highlights)
    if len(joined) > max_summary_chars:
        joined = elide_middle(joined, max_summary_chars)
    return f"[Resumo compactado de {len(middle_messages)} mensagens anteriores desta conversa:\n{joined}\nFim do resumo]"


def build_compressed_history(
    previous_messages: List[Dict[str, Any]],
    context_window: int = 128000,
    protect_head: int = 2,
    protect_tail: int = 10,
) -> List[Dict[str, str]]:
    """Constroi o historico da sessao sem perder o inicio (Head) nem o fim (Tail).

    Diferente de cortar secamente as ultimas 10 mensagens, mantem:
    - As primeiras `protect_head` mensagens (que contem a audiodescricao inicial, PDF lido ou objetivo)
    - Um bloco de resumo compacto para o meio da conversa (se houver mais que protect_head + protect_tail)
    - As ultimas `protect_tail` mensagens completas.
    """
    valid = [m for m in (previous_messages or []) if str(m.get("text") or m.get("content") or "").strip()]
    if not valid:
        return []

    def _to_chat_msg(m: Dict[str, Any]) -> Dict[str, str]:
        is_user = bool(m.get("is_user")) if "is_user" in m else (m.get("role") == "user")
        text = str(m.get("text") if "text" in m else m.get("content", "")).strip()
        return {"role": "user" if is_user else "assistant", "content": text}

    total_keep = protect_head + protect_tail
    if len(valid) <= total_keep:
        out = [_to_chat_msg(m) for m in valid]
    else:
        head = valid[:protect_head]
        middle = valid[protect_head:-protect_tail]
        tail = valid[-protect_tail:]
        summary_text = summarize_middle_turns(middle)
        out = [_to_chat_msg(m) for m in head]
        out.append({"role": "assistant", "content": summary_text})
        out.extend(_to_chat_msg(m) for m in tail)

    # Garante que nunca ultrapasse 60% da janela de contexto do modelo
    max_history_tokens = max(2000, int(context_window * 0.6))
    if estimate_messages_tokens(out) > max_history_tokens:
        for msg in out[:-2]:
            if len(msg["content"]) > 800:
                msg["content"] = elide_middle(msg["content"], 800)

    return out


def prune_tool_messages(
    messages: List[Dict[str, Any]],
    protect_last_rounds: int = 2,
    max_old_tool_chars: int = 700,
) -> List[Dict[str, Any]]:
    """Poda proativa de resultados de ferramentas MCP durante o loop do agente (Hermes ProactivePruneMixin).

    1. Desduplicacao sem perda: se uma ferramenta devolveu exatamente o mesmo texto de um resultado
       mais recente (ex.: dois snapshots iguais), substitui a copia antiga por uma referencia curta.
    2. Compactacao de resultados antigos grandes: resultados de ferramentas fora das ultimas
       `protect_last_rounds` rodadas sao compactados com `elide_middle`.
    """
    if len(messages) <= 4:
        return messages

    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    if not tool_indices:
        return messages

    # 1. Desduplicacao de tras para frente (mantem sempre a copia mais recente completa)
    seen_hashes: Dict[str, int] = {}
    duplicate_of: Dict[int, int] = {}
    for idx in reversed(tool_indices):
        content = str(messages[idx].get("content") or "")
        if len(content) < 200:
            continue
        digest = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()[:16]
        if digest in seen_hashes:
            duplicate_of[idx] = seen_hashes[digest]
        else:
            seen_hashes[digest] = idx

    protected_Indices = set(tool_indices[-protect_last_rounds:]) if protect_last_rounds > 0 else set()

    pruned: List[Dict[str, Any]] = []
    for idx, msg in enumerate(messages):
        if msg.get("role") != "tool":
            pruned.append(msg)
            continue
        content = str(msg.get("content") or "")
        if idx in duplicate_of:
            new_msg = dict(msg)
            new_msg["content"] = "[Resultado identico a uma leitura mais recente desta conversa; omitido para preservar contexto.]"
            pruned.append(new_msg)
        elif idx not in protected_Indices and len(content) > max_old_tool_chars:
            new_msg = dict(msg)
            new_msg["content"] = elide_middle(content, max_old_tool_chars)
            pruned.append(new_msg)
        else:
            pruned.append(msg)

    return pruned


def load_persistent_memory_context(max_items: int = 8, max_chars: int = 900) -> str:
    """Carrega as memorias de longo prazo salvas no SQLite (`blind-memory`) para injetar no prompt."""
    data_dir = os.environ.get("BLIND_DATA_DIR")
    base = Path(data_dir) if data_dir else Path(__file__).resolve().parent.parent / "data"
    db_path = base / "blind_memory.db"
    if not db_path.exists():
        return ""
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memories'"
        )
        if not cur.fetchone():
            conn.close()
            return ""
        cur.execute(
            "SELECT key, content, category FROM memories ORDER BY updated_at DESC LIMIT ?",
            (max_items,),
        )
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return ""
        lines = [f"- {r['key']} ({r['category']}): {r['content']}" for r in rows if r["content"]]
        block = "\n".join(lines)
        if len(block) > max_chars:
            block = block[:max_chars].rsplit("\n", 1)[0]
        return f"\nMemoria persistente do usuario:\n{block}"
    except Exception:
        return ""
