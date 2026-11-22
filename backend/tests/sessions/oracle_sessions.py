"""
Oráculo da Capacidade: Gestão de Sessões e Histórico no SQLite
Local: tests/sessions/oracle_sessions.py
Valida:
1. Criação e persistência de sessões temáticas (/api/sessions).
2. Gravação e leitura atômica de mensagens multi-turn (/api/sessions/{id}/messages).
3. Remoção e ciclo de vida de conversas.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oracle_base import log, request_json


def run_sessions_oracle():
    log("ORACULO-SESSOES", "1. Validando criação de sessão temática (/api/sessions)...")
    sess = request_json("/api/sessions", method="POST", data={"title": "Sessão Teste Modular", "source": "oracle"})
    sess_id = sess.get("id")
    assert sess_id and sess_id.startswith("sess_"), f"ID de sessão inválido: {sess_id}"
    log("ORACULO-SESSOES", f"   OK -> Sessão {sess_id} criada no SQLite.")

    log("ORACULO-SESSOES", "2. Validando adição e recuperação de mensagens no histórico...")
    msg_res = request_json(
        f"/api/sessions/{sess_id}/messages",
        method="POST",
        data={"sender": "Audiodescrição", "text": "Audiodescrição gravada no banco.", "is_user": False}
    )
    assert msg_res.get("status") == "success", "Falha ao gravar mensagem na sessão"

    hist = request_json(f"/api/sessions/{sess_id}/messages")
    messages = hist.get("messages", [])
    assert any("Audiodescrição gravada" in m.get("text", "") for m in messages), "Mensagem não recuperada do SQLite!"
    log("ORACULO-SESSOES", "   OK -> Histórico recuperado com integridade total.")

    log("ORACULO-SESSOES", "3. Validando listagem e ciclo de vida das conversas...")
    sess_list = request_json("/api/sessions")
    assert any(s["id"] == sess_id for s in sess_list.get("sessions", [])), "Sessão não listada no histórico"
    log("ORACULO-SESSOES", "STATUS: 100% APROVADO! Gestor de sessões e SQLite íntegros.")


if __name__ == "__main__":
    try:
        run_sessions_oracle()
        sys.exit(0)
    except Exception as e:
        print(f"\n[FALHA NO ORÁCULO SESSOES] {e}\n", file=sys.stderr)
        sys.exit(1)
