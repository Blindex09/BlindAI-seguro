"""Servidor MCP: transcricao de voz local com Whisper (faster-whisper / CTranslate2).

O audio nunca sai do computador. O modelo e baixado uma vez para data/models/whisper e fica carregado
neste processo, fora do backend principal. Variaveis: BLIND_STT_MODEL (padrao 'base', ~150 MB; 'small' e mais preciso),
BLIND_STT_DEVICE (padrao 'auto'), BLIND_STT_COMPUTE (padrao 'int8').

As ferramentas recebem audio inteiro e por isso ficam em modelHiddenTools no mcp.json: so a interface as usa.
"""

from __future__ import annotations

import base64
import io
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

from ._common import BACKEND_DIR, run_blocking

if os.environ.get("BLIND_STT_DEBUG_DUMP"):  # diagnostico: despeja as pilhas de todas as threads apos N segundos
    import faulthandler
    import sys

    faulthandler.dump_traceback_later(float(os.environ["BLIND_STT_DEBUG_DUMP"]), exit=False, file=sys.stderr)

mcp = FastMCP("blind-stt")


def _warm_imports() -> None:
    """Carrega numpy e faster-whisper em segundo plano na partida. No Windows o primeiro LoadLibrary dessas
    DLLs grandes pode levar dezenas de segundos; assim a primeira fala do usuario nao paga esse custo."""
    import sys

    started = time.time()
    try:
        import numpy  # noqa: F401
        import faster_whisper  # noqa: F401

        print(f"[stt] bibliotecas de voz carregadas em {time.time() - started:.1f}s", file=sys.stderr, flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[stt] falha ao pre-carregar bibliotecas: {exc}", file=sys.stderr, flush=True)


threading.Thread(target=_warm_imports, name="stt-warm", daemon=True).start()

MODEL_NAME = os.environ.get("BLIND_STT_MODEL", "base")
DEVICE = os.environ.get("BLIND_STT_DEVICE", "auto")
COMPUTE = os.environ.get("BLIND_STT_COMPUTE", "int8")
MODEL_DIR = Path(os.environ.get("BLIND_DATA_DIR") or (BACKEND_DIR / "data")) / "models" / "whisper"
MAX_AUDIO_BYTES = 60 * 1024 * 1024

_lock = threading.Lock()
_state: Dict[str, Any] = {"model": None, "loading": False, "error": None, "load_seconds": None}


def _load_model() -> Any:
    with _lock:
        if _state["model"] is not None:
            return _state["model"]
        _state["loading"] = True
        _state["error"] = None
        started = time.time()
        try:
            from faster_whisper import WhisperModel

            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            _state["model"] = WhisperModel(
                MODEL_NAME, device=DEVICE, compute_type=COMPUTE, download_root=str(MODEL_DIR)
            )
            _state["load_seconds"] = round(time.time() - started, 1)
            return _state["model"]
        except Exception as exc:  # noqa: BLE001
            _state["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            _state["loading"] = False


def _wav_to_array(data: bytes) -> Any:
    """WAV PCM 16 bits -> float32 mono 16 kHz, sem depender do PyAV. Levanta ValueError se nao for esse formato."""
    import wave

    import numpy as np

    try:
        with wave.open(io.BytesIO(data)) as w:
            if w.getcomptype() != "NONE" or w.getsampwidth() != 2:
                raise ValueError("somente WAV PCM de 16 bits")
            rate, channels = w.getframerate(), w.getnchannels()
            frames = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as exc:
        raise ValueError(f"WAV invalido: {exc}") from exc
    pcm = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        pcm = pcm[: len(pcm) - len(pcm) % channels].reshape(-1, channels).mean(axis=1)
    if rate != 16000 and len(pcm):
        target = int(len(pcm) * 16000 / rate)
        pcm = np.interp(np.linspace(0, len(pcm) - 1, target), np.arange(len(pcm)), pcm).astype(np.float32)
    return pcm


def _decode(audio_base64: Optional[str], file_path: Optional[str]) -> Any:
    """Devolve um array de audio (WAV) ou, para outros formatos, um arquivo/stream que o PyAV decodifica."""
    if audio_base64:
        data = base64.b64decode(audio_base64.split(",", 1)[-1])
        if len(data) > MAX_AUDIO_BYTES:
            raise ValueError("Audio grande demais (limite 60 MB).")
    elif file_path and os.path.isfile(file_path):
        if os.path.getsize(file_path) > MAX_AUDIO_BYTES:
            raise ValueError("Audio grande demais (limite 60 MB).")
        data = Path(file_path).read_bytes()
    else:
        raise FileNotFoundError("Informe audio_base64 ou um file_path existente.")
    try:
        return _wav_to_array(data)
    except ValueError:
        return io.BytesIO(data)  # WebM, MP3, M4A...: faster-whisper decodifica com PyAV


def _transcribe(source: Any, language: Optional[str], prompt: Optional[str]) -> Dict[str, Any]:
    model = _load_model()
    started = time.time()
    segments, info = model.transcribe(
        source,
        language=language or None,
        beam_size=5,
        vad_filter=True,
        initial_prompt=prompt or None,
        condition_on_previous_text=False,
    )
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return {
        "text": text,
        "language": info.language,
        "language_probability": round(float(info.language_probability), 3),
        "audio_seconds": round(float(info.duration), 2),
        "decoder": "wav" if hasattr(source, "dtype") else "pyav",
        "took_seconds": round(time.time() - started, 2),
        "model": MODEL_NAME,
    }


@mcp.tool()
async def transcribe(
    audio_base64: Optional[str] = None,
    file_path: Optional[str] = None,
    language: Optional[str] = "pt",
    prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcreve fala em texto com Whisper local. Aceita WAV/WebM/MP3 em base64 (ou data URL) ou um caminho de arquivo.
    A primeira chamada baixa e carrega o modelo, o que pode demorar."""
    # Decodificacao e transcricao rodam fora do loop: importar DLLs grandes na thread do loop trava o Windows.
    return await run_blocking(lambda: _transcribe(_decode(audio_base64, file_path), language, prompt))


@mcp.tool()
async def prepare() -> Dict[str, Any]:
    """Baixa (se preciso) e carrega o modelo Whisper para que a primeira transcricao seja rapida."""
    await run_blocking(_load_model)
    return await stt_status()


@mcp.tool()
async def stt_status() -> Dict[str, Any]:
    """Estado do reconhecimento de voz: modelo, se esta carregado, carregando ou com erro."""
    return {
        "model": MODEL_NAME,
        "device": DEVICE,
        "compute_type": COMPUTE,
        "loaded": _state["model"] is not None,
        "loading": _state["loading"],
        "error": _state["error"],
        "load_seconds": _state["load_seconds"],
        "model_dir": str(MODEL_DIR),
    }


if __name__ == "__main__":
    from . import _audit

    _audit.install_audit(mcp, "blind-stt")
    mcp.run()
