"""Teste real do servidor MCP de voz: sintetiza fala em portugues com o SAPI e transcreve com Whisper local.

Opt-in (BLIND_INTEGRATION=1): baixa o modelo na primeira execucao (base, ~150 MB) e usa a voz pt-BR do Windows.
"""

import asyncio
import base64
import os
import sys
import unicodedata
from pathlib import Path

import pytest

from blind_mcp import MCPManager, ServerSpec

BACKEND = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    os.environ.get("BLIND_INTEGRATION") != "1", reason="defina BLIND_INTEGRATION=1 (baixa o modelo Whisper)"
)

PHRASE = "Olá, abra o bloco de notas e escreva uma mensagem para a minha família."


def payload(res: dict) -> dict:
    """Dado estruturado da ferramenta (structuredContent ou JSON no texto)."""
    import json

    structured = res.get("structured")
    if isinstance(structured, dict):
        return structured["result"] if set(structured) == {"result"} else structured
    return json.loads(res["content"])


def norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def synthesize_wav(path: str, text: str) -> None:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        for i in range(voice.GetVoices().Count):
            v = voice.GetVoices().Item(i)
            if "Portuguese" in v.GetDescription():
                voice.Voice = v
                break
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        fmt = win32com.client.Dispatch("SAPI.SpAudioFormat")
        fmt.Type = 22  # 16 kHz, 16 bits, mono
        stream.Format = fmt
        stream.Open(path, 3)
        voice.AudioOutputStream = stream
        voice.Speak(text)
        stream.Close()
    finally:
        pythoncom.CoUninitialize()


def manager(tmp_path) -> MCPManager:
    spec = ServerSpec(
        name="blind-stt",
        command=sys.executable,
        args=["-m", "blind_mcp.servers.stt"],
        cwd=str(BACKEND),
        env={"PYTHONUTF8": "1"},
        startup_timeout=60,
        call_timeout=900,
        model_hidden_tools=["transcribe", "prepare", "stt_status"],  # igual ao mcp.json
    )
    return MCPManager([spec], log_dir=tmp_path)


def test_whisper_transcribes_portuguese_speech(tmp_path):
    wav = str(tmp_path / "fala.wav")
    synthesize_wav(wav, PHRASE)
    assert Path(wav).stat().st_size > 20000

    async def go():
        mgr = manager(tmp_path)
        await mgr.start(wait=True, timeout=60)
        try:
            b64 = "data:audio/wav;base64," + base64.b64encode(Path(wav).read_bytes()).decode()
            by_b64 = await mgr.call_tool("blind-stt", "transcribe", {"audio_base64": b64, "language": "pt"}, timeout=900)
            by_path = await mgr.call_tool("blind-stt", "transcribe", {"file_path": wav}, timeout=300)
            silence = await mgr.call_tool(
                "blind-stt",
                "transcribe",
                {"audio_base64": base64.b64encode(_silent_wav()).decode(), "language": "pt"},
                timeout=300,
            )
            status = await mgr.call_tool("blind-stt", "stt_status", {})
            bad = await mgr.call_tool("blind-stt", "transcribe", {}, timeout=30)
            garbage = await mgr.call_tool(
                "blind-stt",
                "transcribe",
                {"audio_base64": base64.b64encode(b"isto nao e audio" * 50).decode()},
                timeout=60,
            )
            after_garbage = await mgr.call_tool("blind-stt", "stt_status", {}, timeout=30)
            offered = {t["function"]["name"] for t in mgr.openai_tools()}
            return by_b64, by_path, silence, status, bad, offered, garbage, after_garbage
        finally:
            await mgr.stop()

    by_b64, by_path, silence, status, bad, offered, garbage, after_garbage = asyncio.run(go())
    assert by_b64["ok"], by_b64
    assert payload(by_b64)["decoder"] == "wav"  # WAV nao depende do PyAV
    assert not garbage["ok"]  # audio invalido volta como erro, sem travar o servidor
    assert after_garbage["ok"]  # e o servidor continua vivo depois do erro
    for res in (by_b64, by_path):
        assert res["ok"], res
        text = norm(payload(res)["text"])
        # Whisper pode variar pontuacao e acentos; exige as palavras de conteudo.
        for word in ("bloco", "notas", "mensagem", "familia"):
            assert word in text, f"'{word}' ausente na transcricao: {text}"
    assert payload(by_b64)["language"] == "pt"
    assert silence["ok"] and payload(silence)["text"].strip() == ""  # silencio nao vira texto inventado
    assert payload(status)["loaded"] is True
    assert not bad["ok"]
    assert not any("blind-stt" in n or n.startswith("blind_stt") for n in offered)  # escondidas do modelo


def _silent_wav(seconds: float = 2.0) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()
