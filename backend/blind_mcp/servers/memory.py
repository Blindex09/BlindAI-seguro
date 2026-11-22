"""Servidor MCP: memoria pessoal persistente, busca em conversas passadas e cofre (lembretes agendados: servidor blind-schedule).

Adaptado do Hermes Agent (memory_tool.py, session_search_tool.py, cronjob_tools.py) e
do Abacus AI Bot (cron-store.ts / routine-guards.ts), voltado para acessibilidade:
- Evita que a pessoa cega precise rolar historicos longos para achar protocolos, valores ou conversas antigas.
- Guarda fatos pessoais e preferencias para preenchimento automatico de documentos e formularios.
- Dispara lembretes falados no horario programado via sintetizador SAPI do Windows.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List

from mcp.server.fastmcp import FastMCP

from ._common import BACKEND_DIR, run_blocking

mcp = FastMCP("blind-memory")

DATA_DIR = Path(os.environ.get("BLIND_DATA_DIR") or (BACKEND_DIR / "data"))
MEMORY_DB = DATA_DIR / "blind_memory.db"
SESSIONS_DB = BACKEND_DIR / "blind_sessions.db"


def _init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(MEMORY_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                key TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.commit()


_init_db()



def _memory_save_sync(key: str, content: str, category: str = "pessoal") -> Dict[str, Any]:
    k = (key or "").strip().lower()
    c = (content or "").strip()
    cat = (category or "pessoal").strip().lower()
    if not k or not c:
        raise ValueError("Informe key e content nao vazios.")
    from blind_mcp import cofre

    sens = cofre.detectar(c) or cofre.detectar(k)
    if sens:
        raise ValueError(f"Isso parece {sens[0]}: dado sensível não vai para a memória comum (ela fica em texto no computador). "
                         "Guarde no cofre com cofre_guardar (criptografado, e a voz fala sem expor).")
    now = time.time()
    with sqlite3.connect(MEMORY_DB) as conn:
        conn.execute(
            """
            INSERT INTO memories (key, category, content, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                category = excluded.category,
                content = excluded.content,
                updated_at = excluded.updated_at
            """,
            (k, cat, c, now),
        )
        conn.commit()
    return {"ok": True, "key": k, "category": cat, "content": c}


@mcp.tool()
async def memory_save(key: str, content: str, category: str = "pessoal") -> Dict[str, Any]:
    """Salva na memoria persistente um fato importante sobre a pessoa (ex: nome, endereco, preferencias de leitura, contatos
    frequentes). Sobrescreve se a mesma key ja existir. NAO aceita dado sensivel (senha, chave, cartao, CPF, CNPJ, boleto):
    para esses use cofre_guardar."""
    return await run_blocking(_memory_save_sync, key, content, category)


def _memory_recall_sync(query: str = "", category: str = "", limit: int = 20) -> Dict[str, Any]:
    q = (query or "").strip().lower()
    cat = (category or "").strip().lower()
    cap = max(1, min(int(limit or 20), 100))
    sql = "SELECT key, category, content, updated_at FROM memories WHERE 1=1"
    params: List[Any] = []
    if cat:
        sql += " AND lower(category) = ?"
        params.append(cat)
    if q:
        sql += " AND (lower(key) LIKE ? OR lower(content) LIKE ? OR lower(category) LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like])
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(cap)

    with sqlite3.connect(MEMORY_DB) as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        items = [
            {
                "key": row[0],
                "category": row[1],
                "content": row[2],
                "updated_at": dt.datetime.fromtimestamp(row[3]).isoformat(timespec="seconds"),
            }
            for row in cur.fetchall()
        ]
    return {"ok": True, "count": len(items), "memories": items}


@mcp.tool()
async def memory_recall(query: str = "", category: str = "", limit: int = 20) -> Dict[str, Any]:
    """Busca ou lista fatos salvos na memoria persistente da pessoa (por palavra-chave ou categoria)."""
    return await run_blocking(_memory_recall_sync, query, category, limit)


def _memory_forget_sync(key: str) -> Dict[str, Any]:
    k = (key or "").strip().lower()
    with sqlite3.connect(MEMORY_DB) as conn:
        cur = conn.execute("DELETE FROM memories WHERE lower(key) = ?", (k,))
        conn.commit()
        deleted = cur.rowcount > 0
    return {"ok": True, "key": k, "deleted": deleted}


@mcp.tool()
async def memory_forget(key: str) -> Dict[str, Any]:
    """Remove uma informacao especifica da memoria persistente pela key."""
    return await run_blocking(_memory_forget_sync, key)


def _snippet(text: str, terms: List[str], width: int = 240) -> str:
    """Trecho curto em volta da primeira palavra achada, em vez da mensagem inteira (melhor para ouvir)."""
    flat = " ".join((text or "").split())
    if len(flat) <= width:
        return flat
    low = flat.lower()
    pos = min((i for i in (low.find(t) for t in terms) if i >= 0), default=0)
    start = max(0, pos - width // 3)
    end = min(len(flat), start + width)
    start = max(0, end - width)
    # nao corta palavra no meio
    if start > 0:
        sp = flat.find(" ", start)
        start = sp + 1 if 0 <= sp < pos else start
    if end < len(flat):
        sp = flat.rfind(" ", start, end)
        end = sp if sp > start else end
    return ("... " if start > 0 else "") + flat[start:end] + (" ..." if end < len(flat) else "")


def _session_search_sync(query: str, limit: int = 10) -> Dict[str, Any]:
    """Busca em todas as conversas passadas no banco SQLite de sessoes (adaptado de session_search_tool.py do Hermes)."""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "Informe o termo de busca em query."}
    if not SESSIONS_DB.exists():
        return {"ok": True, "query": q, "count": 0, "matches": []}

    cap = max(1, min(int(limit or 10), 50))
    terms = [t.strip().lower() for t in q.split() if t.strip()]
    with sqlite3.connect(SESSIONS_DB) as conn:
        cur = conn.cursor()
        where_clauses = " AND ".join(["(lower(h.text) LIKE ? OR lower(s.title) LIKE ?)"] * len(terms))
        params: List[Any] = []
        for t in terms:
            like = f"%{t}%"
            params.extend([like, like])
        params.append(cap)

        cur.execute(
            f"""
            SELECT h.id, h.session_id, s.title, s.source, h.sender, h.text, h.created_at
            FROM chat_history h
            JOIN chat_sessions s ON s.id = h.session_id
            WHERE {where_clauses}
            ORDER BY h.created_at DESC
            LIMIT ?
            """,
            params,
        )
        matches = [
            {
                "message_id": row[0],
                "session_id": row[1],
                "session_title": row[2],
                "source": row[3],
                "sender": row[4],
                "text": _snippet(row[5], terms),
                "full_length": len(row[5] or ""),
                "when": dt.datetime.fromtimestamp(row[6]).strftime("%d/%m/%Y %H:%M"),
            }
            for row in cur.fetchall()
        ]
    return {"ok": True, "query": q, "count": len(matches), "matches": matches}


@mcp.tool()
async def session_search(query: str, limit: int = 10) -> Dict[str, Any]:
    """Pesquisa em todo o historico de conversas passadas (faturas lidas, protocolos, descricoes de tela, chats)
    sem que a pessoa cega precise rolar listas de mensagens."""
    return await run_blocking(_session_search_sync, query, limit)


# ---------------------------------------------------------------- cofre: guarda segredos, fala sem expor
@mcp.tool()
async def cofre_guardar(nome: str, segredo: str = "", da_area_de_transferencia: bool = False) -> Dict[str, Any]:
    """Guarda um segredo (senha, chave, numero de cartao, CPF, dado de remedio...) no COFRE: criptografado, so esta conta do
    Windows abre. Nunca devolve o segredo. Para o segredo NAO passar pelo modelo de IA, peca para a pessoa copiar o valor e
    chame com da_area_de_transferencia=true (o valor e lido da area de transferencia, que e limpa em seguida). `nome` e um
    rotulo falavel (ex: 'senha do wifi', 'cartao do banco'), nunca o proprio segredo."""
    from blind_mcp import cofre

    valor = segredo
    if da_area_de_transferencia:
        valor = await run_blocking(cofre.ler_e_limpar_area)
        if not valor:
            raise ValueError("A área de transferência está vazia. Peça para a pessoa copiar o valor e tente de novo.")
    elif not valor:
        raise ValueError("Informe o segredo ou use da_area_de_transferencia=true.")
    r = await run_blocking(cofre.guardar, nome, valor)
    return {"ok": True, "guardado": r["nome"], "tipo": r["tipo"] or "texto", "tamanho": r["tamanho"],
            "origem": "área de transferência (limpa)" if da_area_de_transferencia else "informado na conversa",
            "aviso": None if da_area_de_transferencia else "O segredo passou pela conversa. Para os próximos, use a área de transferência."}


@mcp.tool()
async def cofre_listar() -> Dict[str, Any]:
    """Lista os NOMES dos itens do cofre e o tipo (senha, cartão...). Nunca mostra os valores."""
    from blind_mcp import cofre

    itens = await run_blocking(cofre.listar)
    return {"ok": True, "total": len(itens), "itens": itens}


@mcp.tool()
async def cofre_falar(nome: str, soletrar: str = "auto", codigo_confirmacao: str = "") -> Dict[str, Any]:
    """Fala em voz alta um item do cofre SEM devolver o valor (ele nao aparece no texto, no diario nem na memoria). Duas etapas:
    1) chame so com `nome`: volta um codigo. Pergunte se ha alguem por perto (ofereca fone) e se pode falar.
    2) so depois do 'sim', chame de novo com o mesmo nome e o `codigo_confirmacao`. `soletrar`: 'auto' (numeros em grupos, senha
    letra por letra), 'letras' ou 'grupos'. Diga a pessoa que pode pedir para repetir."""
    from blind_mcp import cofre

    if not codigo_confirmacao:
        await run_blocking(cofre.ler, nome)  # confere que existe, sem guardar o valor
        return {"ok": True, "falado": False, "codigo_confirmacao": cofre.novo_codigo("falar", nome),
                "instrucao": "Pergunte se há alguém por perto e se prefere fone. Só com o sim, chame de novo com o código."}
    if not cofre.confirmar(codigo_confirmacao, "falar", nome):
        raise ValueError("Código inválido, vencido ou o item mudou. Comece de novo sem o código.")
    valor = await run_blocking(cofre.ler, nome)
    await cofre.falar(f"{nome}. " + cofre.para_voz(valor, soletrar), devagar=True)
    return {"ok": True, "falado": True, "item": nome, "tamanho": len(valor), "obs": "O valor foi dito só em voz alta."}


@mcp.tool()
async def cofre_copiar(nome: str, segundos: int = 20, codigo_confirmacao: str = "") -> Dict[str, Any]:
    """Poe um item do cofre na area de transferencia para a pessoa COLAR (ex: senha em um site), sem devolver o valor. Limpa
    sozinha depois de `segundos` (5 a 120) se nada mais for copiado. Duas etapas, como cofre_falar (codigo e o sim da pessoa)."""
    from blind_mcp import cofre

    if not codigo_confirmacao:
        await run_blocking(cofre.ler, nome)
        return {"ok": True, "copiado": False, "codigo_confirmacao": cofre.novo_codigo("copiar", nome),
                "instrucao": "Diga que vai copiar o item para a área de transferência e pergunte se pode."}
    if not cofre.confirmar(codigo_confirmacao, "copiar", nome):
        raise ValueError("Código inválido, vencido ou o item mudou. Comece de novo sem o código.")
    valor = await run_blocking(cofre.ler, nome)
    await run_blocking(cofre.copiar_e_limpar_depois, valor, segundos)
    return {"ok": True, "copiado": True, "item": nome, "limpa_em_segundos": max(5, min(int(segundos), 120))}


@mcp.tool()
async def cofre_apagar(nome: str, codigo_confirmacao: str = "") -> Dict[str, Any]:
    """Apaga um item do cofre para sempre. Duas etapas: sem codigo volta um codigo; so com o sim da pessoa, chame com ele."""
    from blind_mcp import cofre

    if not codigo_confirmacao:
        return {"ok": True, "apagado": False, "codigo_confirmacao": cofre.novo_codigo("apagar", nome),
                "instrucao": "Diga qual item será apagado, que não dá para desfazer, e peça o sim."}
    if not cofre.confirmar(codigo_confirmacao, "apagar", nome):
        raise ValueError("Código inválido, vencido ou o item mudou. Comece de novo sem o código.")
    return {"ok": True, "apagado": await run_blocking(cofre.apagar, nome), "item": nome}


@mcp.tool()
async def falar_em_segredo(texto: str, devagar: bool = True) -> Dict[str, Any]:
    """Fala um texto sensivel (dose de remedio, numero de conta, o que estava num documento) SO em voz alta e devolve apenas
    que falou, sem repetir o conteudo. Use para ler em segredo o que voce acabou de ler de uma foto ou documento. O texto nao
    entra no diario de acoes. Antes, se puder haver gente por perto, pergunte se prefere fone."""
    from blind_mcp import cofre

    await cofre.falar(texto, devagar=devagar)
    return {"ok": True, "falado": True, "caracteres": len(texto or ""), "tipos_detectados": cofre.detectar(texto),
            "obs": "O conteúdo foi dito só em voz alta; não o repita por escrito."}


if __name__ == "__main__":
    from . import _audit

    _audit.install_audit(mcp, "blind-memory")
    mcp.run()
