"""Blindaudio: audio em texto com Whisper, no computador do Blind. Um so codigo para o Blind local e para o gateway remoto.

O audio nunca vai para servico de IA. Entra por caminho do arquivo (so no Blind local), por base64 ou por link publico da web
(baixado com IP fixo e sem rede interna, remote_fetch.py). O motor Whisper e o de servers/stt.py (o mesmo do ditado do app).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

URL_MAX_BYTES = 30 * 1024 * 1024
TIMEOUT_S = 900  # a primeira vez baixa o modelo
BACKEND_DIR = Path(__file__).resolve().parents[1]
DESCRICAO = (
    "Blindaudio: transcreve um audio (voz, mensagem de voz, gravacao; WAV, MP3, M4A, OGG, FLAC, WebM) em texto com Whisper, "
    "no computador do Blind: o audio nao vai para servico de IA nenhum. Entra por base64 ou por link publico da web (`url`); "
    "no Blind local tambem por caminho do arquivo. `language`: 'pt' (padrao), 'en', ... ou 'auto' para o Whisper descobrir. "
    "A primeira vez baixa o modelo e demora. Depois, leia o texto para a pessoa e diga a duracao do audio."
)


async def transcrever(
    file_path: Optional[str] = None,
    audio_base64: Optional[str] = None,
    url: Optional[str] = None,
    language: Optional[str] = "pt",
) -> Dict[str, Any]:
    if url and not audio_base64:  # audio de um link publico da web
        from . import remote_fetch

        try:
            audio_base64 = base64.b64encode(await remote_fetch.baixar(url, URL_MAX_BYTES)).decode("ascii")
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        file_path = None
    if not audio_base64 and not file_path:
        raise ValueError("Diga o arquivo, o base64 ou o link do audio.")
    lang = None if str(language or "").strip().lower() in ("", "auto") else str(language).strip()
    return await _rodar({"audio_base64": audio_base64, "file_path": file_path, "language": lang})


async def _rodar(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Uma transcricao num processo proprio (audio_worker.py): o Whisper nao carrega dentro do servidor MCP e some ao terminar."""
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(BACKEND_DIR) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "blind_mcp.audio_worker",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        cwd=str(BACKEND_DIR), env=env, creationflags=0x08000000 if sys.platform == "win32" else 0,  # sem janela de console
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(json.dumps(payload).encode("utf-8")), timeout=TIMEOUT_S)
    except asyncio.TimeoutError as exc:
        proc.kill()
        raise RuntimeError("A transcricao demorou demais e foi cancelada.") from exc
    linhas = [l for l in out.decode("utf-8", errors="replace").splitlines() if l.strip()]
    try:
        res = json.loads(linhas[-1])
    except (IndexError, ValueError) as exc:
        raise RuntimeError("A transcricao falhou sem resposta. Tente de novo.") from exc
    if "error" in res:
        raise ValueError(res["error"])
    return res
