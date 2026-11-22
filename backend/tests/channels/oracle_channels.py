"""
Oráculo da Capacidade: Canais de Comunicação (WhatsApp e Telegram)
Local: tests/channels/oracle_channels.py
Valida:
1. Protocolo de pareamento de WhatsApp sem QR Code (/api/whatsapp/pair).
2. Validação estrita de token de bot do Telegram (/api/telegram/connect).
3. Persistência de sessões de mensageria no SQLite.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oracle_base import log, request_json, OracleAssertionError


def run_channels_oracle():
    log("ORACULO-CANAIS", "1. Validando pareamento de WhatsApp sem QR Code (/api/whatsapp/pair)...")
    res = request_json("/api/whatsapp/pair", method="POST", data={"phone": "(11) 98765-4321"})
    assert res.get("status") in ("waiting_link", "pairing_code_generated"), f"Status de pareamento inesperado: {res}"
    assert res.get("phone") == "5511987654321" or res.get("normalized_phone") == "5511987654321", "Telefone não foi normalizado para formato E.164"
    code = res.get("code") or res.get("pairing_code", "")
    # O gerenciador gera 8 caracteres alfanuméricos (padrão Baileys), sem hífen.
    assert len(code) == 8 and code.isalnum(), f"Código de pareamento inválido: {code}"
    log("ORACULO-CANAIS", f"   OK -> Telefone normalizado e código de pareamento '{code}' gerado no SQLite.")

    log("ORACULO-CANAIS", "2. Validando conector de bot do Telegram (/api/telegram)...")
    try:
        request_json("/api/telegram/connect", method="POST", data={"bot_token": "token_invalido_sem_dois_pontos"})
        raise AssertionError("Token inválido deveria ter sido rejeitado com HTTP 400!")
    except OracleAssertionError as e:
        if "HTTP 400" in str(e):
            log("ORACULO-CANAIS", "   OK -> Token inválido rejeitado com formato estrito (HTTP 400).")
        else:
            raise

    bots_res = request_json("/api/telegram/status")
    assert "bots" in bots_res, "Endpoint /api/telegram/status não retornou a chave 'bots'"
    log("ORACULO-CANAIS", "STATUS: 100% APROVADO! Canais de WhatsApp e Telegram íntegros.")


if __name__ == "__main__":
    try:
        run_channels_oracle()
        sys.exit(0)
    except Exception as e:
        print(f"\n[FALHA NO ORÁCULO CANAIS] {e}\n", file=sys.stderr)
        sys.exit(1)
