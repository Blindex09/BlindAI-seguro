"""Servidor MCP `blind-drive`: Google Drive para uma pessoa cega (so Claude; o app Electron nao o inicia).

Listar, buscar e baixar arquivos; subir arquivo do PC em DUAS etapas (rascunho com codigo, depois o "sim"). Nunca apaga nem
substitui. Configuracao: GOOGLE.md. Compartilha a autorizacao com `blind-mail`.
"""

from __future__ import annotations

import mimetypes
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

from ._common import run_blocking
from ._google_common import (  # noqa: F401
    CLIENT_FILE, DOWNLOAD_DIR, GOOGLE_DIR, TOKEN_FILE, GoogleNaoConfigurado, _PENDING, _credentials, _prune, _safe_name,
    _service, _status_sync, _unique_path,
)

mcp = FastMCP("blind-drive")


@mcp.tool()
async def drive_status() -> Dict[str, Any]:
    """Diz se o Drive/Gmail estao conectados, em qual conta e o que falta. Para conectar, use google_conectar (blind-mail)."""
    return await run_blocking(_status_sync)


# ------------------------------ drive ------------------------------

_FOLDER = "application/vnd.google-apps.folder"
_EXPORT = {  # arquivos nativos do Google nao baixam direto: exporta
    "application/vnd.google-apps.document": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}


def _drive_list_sync(consulta: str, pasta_id: str, limite: int) -> Dict[str, Any]:
    svc = _service("drive", "v3")
    partes = ["trashed = false"]
    if pasta_id:
        partes.append(f"'{pasta_id}' in parents")
    if consulta:
        q = consulta.replace("\\", "\\\\").replace("'", "\\'")
        partes.append(f"(name contains '{q}' or fullText contains '{q}')")
    res = svc.files().list(q=" and ".join(partes), pageSize=max(1, min(int(limite or 15), 50)),
                           orderBy="modifiedTime desc",
                           fields="files(id,name,mimeType,size,modifiedTime,owners(displayName))").execute()
    itens = [{"id": f["id"], "nome": f["name"], "tipo": "pasta" if f["mimeType"] == _FOLDER else f["mimeType"],
              "tamanho_bytes": int(f["size"]) if f.get("size") else None, "modificado": f.get("modifiedTime"),
              "dono": ((f.get("owners") or [{}])[0]).get("displayName", "")} for f in res.get("files", [])]
    return {"ok": True, "total": len(itens), "arquivos": itens}


@mcp.tool()
async def drive_listar(consulta: str = "", pasta_id: str = "", limite: int = 15) -> Dict[str, Any]:
    """Lista ou busca arquivos do Drive (mais recentes primeiro) por nome ou conteudo. `pasta_id` limita a uma pasta.
    Sem argumentos, mostra os mais recentes."""
    return await run_blocking(_drive_list_sync, consulta, pasta_id, limite)


def _drive_download_sync(file_id: str, pasta: str) -> Dict[str, Any]:
    import io

    from googleapiclient.http import MediaIoBaseDownload

    svc = _service("drive", "v3")
    meta = svc.files().get(fileId=file_id, fields="id,name,mimeType,size").execute()
    if meta["mimeType"] == _FOLDER:
        raise ValueError("Isso e uma pasta. Use drive_listar com pasta_id para ver o que tem dentro.")
    if meta["mimeType"] in _EXPORT:
        mime, ext = _EXPORT[meta["mimeType"]]
        request = svc.files().export_media(fileId=file_id, mimeType=mime)
        nome = meta["name"] + ext
    elif meta["mimeType"].startswith("application/vnd.google-apps."):
        mime, ext = "application/pdf", ".pdf"
        request = svc.files().export_media(fileId=file_id, mimeType=mime)
        nome = meta["name"] + ext
    else:
        if int(meta.get("size") or 0) > 200 * 1024 * 1024:
            raise ValueError("Arquivo maior que 200 MB: baixe pelo navegador.")
        request = svc.files().get_media(fileId=file_id)
        nome = meta["name"]
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = dl.next_chunk()
    dest = _unique_path(Path(pasta) if pasta else DOWNLOAD_DIR, nome)
    dest.write_bytes(buf.getvalue())
    return {"ok": True, "arquivo": str(dest), "tamanho_bytes": dest.stat().st_size, "origem": meta["name"]}


@mcp.tool()
async def drive_baixar(file_id: str, pasta: str = "") -> Dict[str, Any]:
    """Baixa um arquivo do Drive para uma pasta (padrao: Downloads\\Blind). Documentos, planilhas e apresentacoes do Google
    saem como .docx/.xlsx/.pptx; outros nativos, como PDF. Nunca sobrescreve arquivo existente."""
    return await run_blocking(_drive_download_sync, file_id, pasta)


@mcp.tool()
async def drive_enviar(
    caminho: str, pasta_id: str = "", nome: str = "", codigo_confirmacao: Optional[str] = None
) -> Dict[str, Any]:
    """Sobe um arquivo do computador para o Drive, em DUAS etapas.
    1) Sem `codigo_confirmacao`: NADA e enviado; volta nome, tamanho, destino e um codigo. Leia e pergunte 'Posso enviar?'.
    2) So depois do 'sim', chame de novo com os mesmos argumentos e o codigo (10 min, uso unico).
    `pasta_id` vazio = raiz do Meu Drive. Cria arquivo novo; nunca substitui nem apaga."""
    _prune()
    p = Path(caminho)
    if not p.is_file():
        raise FileNotFoundError(f"Arquivo nao encontrado: {caminho}")
    final = (nome or p.name).strip()
    sig = {"caminho": str(p), "pasta_id": pasta_id, "nome": final}
    if not codigo_confirmacao:
        code = secrets.token_hex(2)
        _PENDING[code] = {"tipo": "drive", "sig": sig, "criado": time.time()}
        return {"ok": True, "enviado": False, "codigo_confirmacao": code, "arquivo": final, "tamanho_bytes": p.stat().st_size,
                "destino": pasta_id or "raiz do Meu Drive",
                "instrucao": "Leia o nome, o tamanho e o destino e pergunte 'Posso enviar?'. So reenvie com o codigo apos o sim."}
    pend = _PENDING.get(codigo_confirmacao.strip())
    if not pend or pend["tipo"] != "drive" or pend["sig"] != sig:
        raise ValueError("Codigo invalido, vencido ou os dados mudaram. Prepare de novo (sem codigo) e peca o sim outra vez.")
    del _PENDING[codigo_confirmacao.strip()]

    def _upload() -> Dict[str, Any]:
        from googleapiclient.http import MediaFileUpload

        svc = _service("drive", "v3")
        body: Dict[str, Any] = {"name": final}
        if pasta_id:
            body["parents"] = [pasta_id]
        media = MediaFileUpload(str(p), mimetype=mimetypes.guess_type(final)[0] or "application/octet-stream", resumable=True)
        f = svc.files().create(body=body, media_body=media, fields="id,name,webViewLink").execute()
        return {"ok": True, "enviado": True, "id": f.get("id"), "nome": f.get("name"), "link": f.get("webViewLink")}

    return await run_blocking(_upload)


if __name__ == "__main__":
    from . import _audit

    _audit.install_audit(mcp, "blind-drive")
    mcp.run()
