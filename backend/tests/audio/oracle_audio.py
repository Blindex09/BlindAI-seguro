"""
Oráculo da Capacidade: Áudio, Voz Nativa e Sanitização Textual
Local: tests/audio/oracle_audio.py
Valida:
1. Disparo de voz nativa SAPI (/api/speak).
2. Sanitização estrita de saídas (zero asteriscos e zero markdown decorativo).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oracle_base import log, request_json


def run_audio_oracle():
    log("ORACULO-AUDIO", "1. Validando endpoint de voz nativa SAPI (/api/speak)...")
    res = request_json("/api/speak", method="POST", data={"text": "Blind AI áudio operacional."})
    assert res.get("status") == "speaking", f"Status de voz inesperado: {res}"
    log("ORACULO-AUDIO", "   OK -> Sintetizador SAPI respondeu normalmente.")

    log("ORACULO-AUDIO", "2. Validando higienização para leitores de tela no chat (/api/chat)...")
    chat_res = request_json("/api/chat", method="POST", data={"message": "Diga 'olá' de forma simples.", "tts": False})
    reply = chat_res.get("reply", "")
    assert reply, "Resposta vazia"
    assert "*" not in reply, f"Resposta contém asteriscos proibidos: {reply}"
    assert "###" not in reply, f"Resposta contém cabeçalhos markdown crus: {reply}"
    log("ORACULO-AUDIO", "   OK -> Saída textual 100% higienizada para sintetizadores de voz.")

    log("ORACULO-AUDIO", "STATUS: 100% APROVADO! Módulo de áudio e fala acessível íntegro.")


if __name__ == "__main__":
    try:
        run_audio_oracle()
        sys.exit(0)
    except Exception as e:
        print(f"\n[FALHA NO ORÁCULO AUDIO] {e}\n", file=sys.stderr)
        sys.exit(1)
