"""Servidor MCP `blind-mail`: Gmail para uma pessoa cega (so Claude; o app Electron nao o inicia).

Ler/buscar e-mails, baixar anexos e enviar (com anexos do PC) em DUAS etapas: rascunho com codigo e, so apos o "sim" da pessoa,
o envio. Nunca apaga nem altera a caixa. Configuracao: GOOGLE.md. Compartilha a autorizacao com `blind-drive`.
"""

from __future__ import annotations

import base64
import mimetypes
import re
import secrets
import time
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from ._common import run_blocking
from ._google_common import (  # noqa: F401
    CLIENT_FILE, DOWNLOAD_DIR, GOOGLE_DIR, MAX_ATTACH_BYTES, TOKEN_FILE, GoogleNaoConfigurado, _PENDING, _connect_sync,
    _credentials, _prune, _safe_name, _service, _status_sync, _unique_path,
)

mcp = FastMCP("blind-mail")


@mcp.tool()
async def google_status() -> Dict[str, Any]:
    """Diz se o Gmail/Drive estao conectados, em qual conta e o que falta para conectar."""
    return await run_blocking(_status_sync)


@mcp.tool()
async def google_conectar() -> Dict[str, Any]:
    """Abre o navegador para a PESSOA autorizar o Blind no Gmail e no Drive (ela mesma entra na conta e clica em Permitir;
    senha nunca passa pelo Blind). So chame se a pessoa pedir. Espera ate 5 minutos."""
    return await run_blocking(_connect_sync)


# ------------------------------ gmail ------------------------------

def _header(headers: List[Dict[str, str]], name: str) -> str:
    return next((h.get("value", "") for h in headers if h.get("name", "").lower() == name.lower()), "")


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", html)
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def _walk(payload: Dict[str, Any], plain: List[str], html: List[str], anexos: List[Dict[str, Any]]) -> None:
    mime = payload.get("mimeType", "")
    body = payload.get("body", {}) or {}
    filename = payload.get("filename") or ""
    if filename and body.get("attachmentId"):
        anexos.append({"nome": filename, "tipo": mime, "tamanho_bytes": body.get("size", 0), "attachment_id": body["attachmentId"]})
    elif mime == "text/plain" and body.get("data"):
        plain.append(_decode(body["data"]))
    elif mime == "text/html" and body.get("data"):
        html.append(_decode(body["data"]))
    for part in payload.get("parts", []) or []:
        _walk(part, plain, html, anexos)


def _parse_message(msg: Dict[str, Any], max_chars: int) -> Dict[str, Any]:
    payload = msg.get("payload", {}) or {}
    headers = payload.get("headers", [])
    plain: List[str] = []
    html: List[str] = []
    anexos: List[Dict[str, Any]] = []
    _walk(payload, plain, html, anexos)
    texto = "\n".join(plain).strip() or _html_to_text("\n".join(html))
    return {
        "id": msg.get("id"),
        "de": _header(headers, "From"),
        "para": _header(headers, "To"),
        "assunto": _header(headers, "Subject"),
        "data": _header(headers, "Date"),
        "nao_lido": "UNREAD" in (msg.get("labelIds") or []),
        "texto": texto[:max_chars],
        "cortado": len(texto) > max_chars,
        "anexos": anexos,
    }


def _gmail_search_sync(query: str, limit: int) -> Dict[str, Any]:
    svc = _service("gmail", "v1")
    cap = max(1, min(int(limit or 10), 30))
    res = svc.users().messages().list(userId="me", q=query or "", maxResults=cap).execute()
    itens = []
    for m in res.get("messages", []) or []:
        full = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                          metadataHeaders=["From", "Subject", "Date"]).execute()
        h = full.get("payload", {}).get("headers", [])
        itens.append({"id": m["id"], "de": _header(h, "From"), "assunto": _header(h, "Subject"), "data": _header(h, "Date"),
                      "nao_lido": "UNREAD" in (full.get("labelIds") or []), "resumo": (full.get("snippet") or "")[:200]})
    return {"ok": True, "total": len(itens), "mensagens": itens, "consulta": query or "(caixa de entrada inteira)"}


@mcp.tool()
async def gmail_buscar(consulta: str = "in:inbox", limite: int = 10) -> Dict[str, Any]:
    """Busca e-mails com a sintaxe do Gmail (ex: 'is:unread', 'from:banco', 'subject:fatura has:attachment', 'newer_than:2d').
    Devolve remetente, assunto, data e um resumo curto de cada. Nao marca nada como lido."""
    return await run_blocking(_gmail_search_sync, consulta, limite)


def _gmail_read_sync(message_id: str, max_chars: int) -> Dict[str, Any]:
    svc = _service("gmail", "v1")
    msg = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
    return {"ok": True, **_parse_message(msg, max(500, min(int(max_chars or 6000), 30000)))}


@mcp.tool()
async def gmail_ler(message_id: str, max_chars: int = 6000) -> Dict[str, Any]:
    """Le um e-mail pelo id (de gmail_buscar): remetente, assunto, texto limpo e lista de anexos. Nao marca como lido."""
    return await run_blocking(_gmail_read_sync, message_id, max_chars)


def _gmail_attachment_sync(message_id: str, attachment_id: str, pasta: str, nome: str) -> Dict[str, Any]:
    svc = _service("gmail", "v1")
    att = svc.users().messages().attachments().get(userId="me", messageId=message_id, id=attachment_id).execute()
    data = base64.urlsafe_b64decode(att["data"] + "=" * (-len(att["data"]) % 4))
    folder = Path(pasta) if pasta else DOWNLOAD_DIR
    dest = _unique_path(folder, nome or "anexo")
    dest.write_bytes(data)
    return {"ok": True, "arquivo": str(dest), "tamanho_bytes": len(data)}


@mcp.tool()
async def gmail_anexo_baixar(message_id: str, attachment_id: str, nome: str, pasta: str = "") -> Dict[str, Any]:
    """Baixa um anexo de e-mail para uma pasta (padrao: Downloads\\Blind). Nunca sobrescreve: se o nome existir, acrescenta (1).
    Depois pode ler com blind-docs read_document (PDF) ou describe_image (imagem)."""
    return await run_blocking(_gmail_attachment_sync, message_id, attachment_id, pasta, nome)


def _check_files(anexos: List[str]) -> List[Dict[str, Any]]:
    out = []
    total = 0
    for a in anexos or []:
        p = Path(a)
        if not p.is_file():
            raise FileNotFoundError(f"Anexo nao encontrado: {a}")
        size = p.stat().st_size
        total += size
        out.append({"caminho": str(p), "nome": p.name, "tamanho_bytes": size})
    if total > MAX_ATTACH_BYTES:
        raise ValueError("Os anexos passam de 20 MB. Envie menos arquivos ou use o Drive.")
    return out


def _build_raw(para: str, assunto: str, texto: str, anexos: List[Dict[str, Any]], cc: str) -> str:
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["To"] = para
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = assunto
    msg.set_content(texto)
    for a in anexos:
        ctype, _ = mimetypes.guess_type(a["nome"])
        main, sub = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(Path(a["caminho"]).read_bytes(), maintype=main, subtype=sub, filename=a["nome"])
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


@mcp.tool()
async def gmail_enviar(
    para: str,
    assunto: str,
    texto: str,
    anexos: Optional[List[str]] = None,
    cc: str = "",
    codigo_confirmacao: Optional[str] = None,
) -> Dict[str, Any]:
    """Envia e-mail em DUAS etapas. `anexos` e uma lista de caminhos de arquivos do computador.
    1) Chame sem `codigo_confirmacao`: NADA e enviado; volta o rascunho (para, assunto, texto, anexos com tamanho) e um codigo.
       Leia tudo em voz alta e pergunte 'Posso enviar?'.
    2) So depois do 'sim', chame de novo com os MESMOS argumentos e o codigo (vale 10 min, uso unico). Se mudar algo, recomece."""
    _prune()
    if not (para or "").strip() or "@" not in para:
        raise ValueError("Informe um endereco de e-mail valido em `para`.")
    if not (assunto or "").strip() and not (texto or "").strip():
        raise ValueError("Assunto e texto estao vazios.")
    arquivos = await run_blocking(_check_files, list(anexos or []))
    assinatura = {"para": para.strip(), "cc": cc.strip(), "assunto": assunto, "texto": texto,
                  "anexos": [a["caminho"] for a in arquivos]}

    if not codigo_confirmacao:
        code = secrets.token_hex(2)
        _PENDING[code] = {"tipo": "gmail", "sig": assinatura, "criado": time.time()}
        return {"ok": True, "enviado": False, "codigo_confirmacao": code, "para": assinatura["para"], "cc": assinatura["cc"],
                "assunto": assunto, "texto": texto, "anexos": arquivos,
                "instrucao": "Leia para a pessoa o destinatario, o assunto, o texto e os anexos e pergunte 'Posso enviar?'. "
                             "So reenvie com o codigo apos o sim."}

    pend = _PENDING.get(codigo_confirmacao.strip())
    if not pend or pend["tipo"] != "gmail" or pend["sig"] != assinatura:
        raise ValueError("Codigo invalido, vencido ou o conteudo mudou. Prepare o rascunho de novo (sem codigo) e peca o sim outra vez.")
    del _PENDING[codigo_confirmacao.strip()]

    def _send() -> Dict[str, Any]:
        svc = _service("gmail", "v1")
        raw = _build_raw(assinatura["para"], assunto, texto, arquivos, assinatura["cc"])
        sent = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"ok": True, "enviado": True, "id": sent.get("id"), "para": assinatura["para"], "anexos": [a["nome"] for a in arquivos]}

    return await run_blocking(_send)


if __name__ == "__main__":
    from . import _audit

    _audit.install_audit(mcp, "blind-mail")
    mcp.run()
