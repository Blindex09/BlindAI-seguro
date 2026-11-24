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
import weakref
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


def tipo_do_audio(inicio: bytes) -> Optional[str]:
    """O formato de audio pelos primeiros bytes do arquivo (a assinatura), ou None se nao for um dos aceitos.

    Confere o conteudo, nunca o nome nem o tipo que o site informa: um link pode dizer 'audio/mpeg' e entregar outra coisa.
    """
    if inicio[:4] == b"RIFF" and inicio[8:12] == b"WAVE":
        return "wav"
    if inicio[:3] == b"ID3" or (len(inicio) >= 2 and inicio[0] == 0xFF and inicio[1] & 0xE0 == 0xE0):
        return "mp3"
    if inicio[4:8] == b"ftyp":
        return "m4a"
    if inicio[:4] == b"OggS":
        return "ogg"
    if inicio[:4] == b"fLaC":
        return "flac"
    if inicio[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    return None


def conferir_audio(inicio: bytes) -> str:
    tipo = tipo_do_audio(inicio)
    if tipo is None:
        raise ValueError("O arquivo nao parece um audio aceito (WAV, MP3, M4A, OGG, FLAC ou WebM): o conteudo nao bate com nenhum desses formatos.")
    return tipo


_TRAVAS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = weakref.WeakKeyDictionary()


def _uma_por_vez() -> asyncio.Lock:
    """A trava das transcricoes: uma de cada vez. O Whisper pesa; varias ao mesmo tempo travariam o computador."""
    loop = asyncio.get_running_loop()
    trava = _TRAVAS.get(loop)
    if trava is None:
        trava = _TRAVAS[loop] = asyncio.Lock()
    return trava


async def transcrever(
    file_path: Optional[str] = None,
    audio_base64: Optional[str] = None,
    url: Optional[str] = None,
    language: Optional[str] = "pt",
) -> Dict[str, Any]:
    if url and not audio_base64:  # audio de um link publico da web
        from . import remote_fetch

        try:
            dados = await remote_fetch.baixar(url, URL_MAX_BYTES)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        conferir_audio(dados[:16])  # a assinatura do arquivo, antes de qualquer decodificacao
        audio_base64 = base64.b64encode(dados).decode("ascii")
        file_path = None
    elif audio_base64:  # base64 do remoto (ou data URL): confere a assinatura nos primeiros bytes decodificados
        audio_base64 = audio_base64.split(",", 1)[-1].strip()
        try:
            inicio = base64.b64decode(audio_base64[:24] + "=" * (-len(audio_base64[:24]) % 4))
        except ValueError as exc:
            raise ValueError("O audio em base64 esta invalido.") from exc
        conferir_audio(inicio)
    if not audio_base64 and not file_path:
        raise ValueError("Diga o arquivo, o base64 ou o link do audio.")
    lang = None if str(language or "").strip().lower() in ("", "auto") else str(language).strip()
    async with _uma_por_vez():
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
