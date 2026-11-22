"""Servidor MCP: fala (Windows SAPI offline).

A fala so ocorre quando uma ferramenta pede. O padrao do Blind AI continua sendo nao sobrepor
o leitor de tela do usuario (NVDA, JAWS).
"""

from __future__ import annotations

import re
import threading
from typing import Any, Dict, List

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("blind-speech")

_current: Dict[str, Any] = {"stop": None}


def _clean(text: str) -> str:
    t = re.sub(r"```[a-zA-Z]*\n?", "", text).replace("```", "").replace("`", "")
    t = re.sub(r"\*{1,3}", "", t)
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", t).strip()


def _speak_blocking(text: str, rate: int, stop: threading.Event) -> None:
    """Fala na propria thread do SAPI. O objeto COM nao pode ser usado de outra thread, entao o
    stop_speaking so sinaliza um Event e esta thread interrompe a fala (SVSFPurgeBeforeSpeak)."""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        voice.Rate = rate
        voice.Speak(text, 1)  # SVSFlagsAsync
        while not voice.WaitUntilDone(100):
            pythoncom.PumpWaitingMessages()
            if stop.is_set():
                voice.Speak("", 3)  # Async + PurgeBeforeSpeak
                break
    finally:
        if _current.get("stop") is stop:
            _current["stop"] = None
        pythoncom.CoUninitialize()


@mcp.tool()
async def speak(text: str, rate: int = 0) -> Dict[str, Any]:
    """Fala o texto em voz alta pelo alto-falante. rate vai de -10 (lento) a 10 (rapido)."""
    cleaned = _clean(text)
    if not cleaned:
        raise ValueError("Texto vazio.")
    rate = max(-10, min(10, int(rate)))
    previous = _current.get("stop")
    if previous is not None:
        previous.set()
    stop = threading.Event()
    _current["stop"] = stop
    threading.Thread(target=_speak_blocking, args=(cleaned, rate, stop), daemon=True).start()
    return {"status": "speaking", "chars": len(cleaned)}


@mcp.tool()
async def stop_speaking() -> Dict[str, Any]:
    """Interrompe a fala em andamento."""
    stop = _current.get("stop")
    if stop is None:
        return {"status": "idle"}
    stop.set()
    return {"status": "stopped"}


@mcp.tool()
async def list_voices() -> List[str]:
    """Lista as vozes SAPI instaladas."""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        voices = win32com.client.Dispatch("SAPI.SpVoice").GetVoices()
        return [voices.Item(i).GetDescription() for i in range(voices.Count)]
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    from . import _audit

    _audit.install_audit(mcp, "blind-speech")
    mcp.run()
