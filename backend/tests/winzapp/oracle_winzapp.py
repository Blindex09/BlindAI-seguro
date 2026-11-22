"""
Oráculo da Capacidade: Automação de Comunicador WinZapp / WhatsApp Desktop
Local: tests/winzapp/oracle_winzapp.py
Valida exclusivamente o fluxo de envio de mensagens e confirmação no WinZapp:
1. Envio de mensagem por linguagem natural ('manda uma mensagem pro mozão. fala. eu te amo').
2. Pergunta de confirmação ('mandou?').
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oracle_base import log, request_json


def run_winzapp_oracle():
    log("ORACULO-WINZAPP", "Iniciando validação isolada do comunicador WinZapp...")

    sess_res = request_json("/api/sessions", method="POST", data={"title": "Teste Oráculo WinZapp", "source": "chat"})
    sess_id = sess_res.get("id")

    # 1. Envio de mensagem no comunicador ('manda uma mensagem pro mozão. fala. eu te amo')
    log("ORACULO-WINZAPP", "1. Testando envio de mensagem no WinZapp ('manda uma mensagem pro mozão. fala. eu te amo')...")
    msg_res = request_json(
        "/api/chat",
        method="POST",
        data={"message": "manda uma mensagem pro mozão. fala. eu te amo", "session_id": sess_id, "tts": False},
    )
    msg_reply = msg_res.get("reply", "")
    assert msg_reply, "Resposta vazia para envio de mensagem"
    assert "Janelas abertas atualmente" not in msg_reply, f"Resposta de fallback indevida: {msg_reply}"
    assert "*" not in msg_reply, f"Resposta contém asteriscos: {msg_reply}"
    log("ORACULO-WINZAPP", f"   OK -> Mensagem processada e enviada: '{msg_reply[:80]}...'")

    # 2. Pergunta de confirmação ('mandou?')
    log("ORACULO-WINZAPP", "2. Testando pergunta de confirmação ('mandou?')...")
    confirm_res = request_json(
        "/api/chat",
        method="POST",
        data={"message": "mandou?", "session_id": sess_id, "tts": False},
    )
    confirm_reply = confirm_res.get("reply", "")
    assert confirm_reply, "Resposta vazia para confirmação 'mandou?'"
    assert "sim" in confirm_reply.lower() or "enviad" in confirm_reply.lower(), f"Resposta não confirmou o envio: {confirm_reply}"
    assert "Janelas abertas atualmente" not in confirm_reply, f"Resposta de fallback indevida: {confirm_reply}"
    assert "*" not in confirm_reply, f"Resposta contém asteriscos: {confirm_reply}"
    log("ORACULO-WINZAPP", f"   OK -> Confirmação de envio respondida com precisão: '{confirm_reply[:80]}...'")

    log("ORACULO-WINZAPP", "STATUS: 100% APROVADO! Fluxo WinZapp validado isoladamente.")


if __name__ == "__main__":
    try:
        run_winzapp_oracle()
        sys.exit(0)
    except Exception as e:
        print(f"\n[FALHA NO ORÁCULO WINZAPP] {e}\n", file=sys.stderr)
        sys.exit(1)
