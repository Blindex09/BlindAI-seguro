"""Gera um WAV 16 kHz mono com fala em portugues (voz pt-BR do Windows) para os testes de ditado.

Uso: python scripts/make-speech-wav.py SAIDA.wav "frase a falar"
O arquivo tem 1,2 s de silencio antes (o usuario leva um instante para falar depois do bip) e 2 s depois
(a gravacao termina sozinha apos uma pausa).
"""

import sys
import tempfile
import wave
from pathlib import Path


def synthesize(path: str, text: str) -> None:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        for i in range(voice.GetVoices().Count):
            item = voice.GetVoices().Item(i)
            if "Portuguese" in item.GetDescription():
                voice.Voice = item
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


def main() -> None:
    out, text = sys.argv[1], sys.argv[2]
    with tempfile.TemporaryDirectory() as tmp:
        raw = str(Path(tmp) / "speech.wav")
        synthesize(raw, text)
        with wave.open(raw) as w:
            frames = w.readframes(w.getnframes())
            rate = w.getframerate()
        silence = lambda seconds: b"\x00\x00" * int(rate * seconds)  # noqa: E731
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(silence(1.2) + frames + silence(2.0))
    print(out)


if __name__ == "__main__":
    main()
