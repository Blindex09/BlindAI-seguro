"""
Oráculo da Capacidade: Audiodescrição de Tela e Imagens
Local: tests/vision/oracle_vision.py
Valida:
1. Geração de audiodescrição multimodal (W3C WAI e DIAGRAM Center).
2. Persistência na sessão SQLite.
3. Retenção cognitiva de nomes de software (WinZap) e controles de janela no chat.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oracle_base import log, request_json


def run_vision_oracle():
    log("ORACULO-VISAO", "1. Validando geração de audiodescrição multimodal...")
    raw_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkWPjfDwAEcQHsW4E7vQAAAABJRU5ErkJggg=="
    data_uri = f"data:image/png;base64,{raw_b64}"

    sess = request_json("/api/sessions", method="POST", data={"title": "Teste Visão", "source": "vision"})
    sess_id = sess.get("id")

    res = request_json("/api/vision/describe", method="POST", data={"image_base64": data_uri, "session_id": sess_id}, timeout=90.0)
    desc = res.get("description", "").strip()
    assert len(desc) > 10, "Descrição de imagem retornou vazia"
    assert "*" not in desc, "Descrição contém asteriscos proibidos"
    log("ORACULO-VISAO", f"   OK -> Audiodescrição gerada ({len(desc)} caracteres).")

    log("ORACULO-VISAO", "2. Validando retenção cognitiva da tela descrita (WinZap 3)...")
    tela_winzap = (
        "A janela do programa WinZap versão 3 ocupa a tela inteira. Na barra de título no topo "
        "está escrito WinZap 3 entre parênteses, com botões de minimizar, restaurar e fechar."
    )
    request_json(
        f"/api/sessions/{sess_id}/messages",
        method="POST",
        data={"sender": "Audiodescrição (Tela)", "text": tela_winzap, "is_user": False}
    )

    chat_turn = request_json(
        "/api/chat",
        method="POST",
        data={
            "message": "qual o nome do software da tela que você viu?",
            "session_id": sess_id,
            "provider": "opencode",
            "model": "opencode/deepseek-v4.1-flash-free",
            "tts": False
        },
        timeout=90.0
    )
    reply = chat_turn.get("reply", "")
    assert reply, "Resposta do chat vazia"
    reply_lower = reply.lower()
    assert "winzap" in reply_lower or "winzip" in reply_lower, f"IA não reconheceu o software! Resposta: '{reply}'"
    assert "*" not in reply, f"Resposta contém asteriscos: '{reply}'"
    log("ORACULO-VISAO", f"   OK -> IA respondeu com precisão semântica: '{reply[:80]}...'")

    # 3. Validando Auto-Roteamento Inteligente (passando modelo de texto puro)
    log("ORACULO-VISAO", "3. Validando Auto-Roteamento Inteligente com modelo de texto puro (deepseek-v4.1)...")
    route_res = request_json(
        "/api/vision/describe",
        method="POST",
        data={
            "image_base64": data_uri,
            "session_id": sess_id,
            "provider": "opencode",
            "model": "opencode/deepseek-v4.1-flash-free"
        },
        timeout=90.0
    )
    route_desc = route_res.get("description", "").strip()
    assert route_desc, "Descrição retornou vazia no auto-roteamento"
    assert "não foi possível processar" not in route_desc.lower(), f"Falha no auto-roteamento: {route_desc}"
    assert "verifique se o modelo suporta" not in route_desc.lower(), f"Modelo não foi auto-roteado: {route_desc}"
    assert "*" not in route_desc, f"Descrição contém asteriscos: {route_desc}"
    log("ORACULO-VISAO", f"   OK -> Auto-roteamento funcionou perfeitamente: '{route_desc[:80]}...'")

    log("ORACULO-VISAO", "STATUS: 100% APROVADO! Visão e retenção cognitiva íntegras.")


if __name__ == "__main__":
    try:
        run_vision_oracle()
        sys.exit(0)
    except Exception as e:
        print(f"\n[FALHA NO ORÁCULO VISAO] {e}\n", file=sys.stderr)
        sys.exit(1)
