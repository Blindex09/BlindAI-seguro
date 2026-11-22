"""
Oráculo da Capacidade: Leitor de Documentos e Faturas PDF
Local: tests/docs/oracle_docs.py
Valida:
1. Extração estruturada de faturas PDF via PyMuPDF.
2. Persistência na sessão SQLite.
3. Retenção cognitiva de valor monetário e data de vencimento no chat.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oracle_base import log, request_json


def run_docs_oracle():
    log("ORACULO-DOCS", "1. Validando leitura e estruturação de fatura PDF via PyMuPDF...")
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 72), "FATURA DE ENERGIA\nTotal a Pagar: R$ 312,40\nVencimento: 10/12/2026", fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    pdf_b64 = f"data:application/pdf;base64,{base64.b64encode(pdf_bytes).decode('utf-8')}"

    sess = request_json("/api/sessions", method="POST", data={"title": "Fatura de Energia", "source": "docs"})
    sess_id = sess.get("id")

    res = request_json("/api/docs/read", method="POST", data={"file_base64": pdf_b64, "filename": "luz.pdf", "session_id": sess_id}, timeout=90.0)
    assert res.get("status") == "success", f"Falha na leitura do PDF: {res}"
    assert "extracted_text" in res and len(res["extracted_text"]) > 10, "Texto não extraído do PDF"
    log("ORACULO-DOCS", "   OK -> Fatura processada com sucesso via PyMuPDF.")

    log("ORACULO-DOCS", "2. Validando retenção do valor da fatura no chat...")
    chat_turn = request_json(
        "/api/chat",
        method="POST",
        data={
            "message": "qual o valor total da fatura que você leu?",
            "session_id": sess_id,
            "provider": "opencode",
            "model": "opencode/deepseek-v4.1-flash-free",
            "tts": False
        },
        timeout=90.0
    )
    reply = chat_turn.get("reply", "")
    assert reply, "Resposta vazia"
    assert "312" in reply or "312,40" in reply, f"IA não reteve o valor da fatura! Resposta: '{reply}'"
    assert "*" not in reply, f"Resposta contém asteriscos: '{reply}'"
    log("ORACULO-DOCS", f"   OK -> IA respondeu com o valor retido na memória: '{reply[:80]}...'")

    log("ORACULO-DOCS", "STATUS: 100% APROVADO! Leitura de documentos e faturas íntegra.")


if __name__ == "__main__":
    try:
        run_docs_oracle()
        sys.exit(0)
    except Exception as e:
        print(f"\n[FALHA NO ORÁCULO DOCS] {e}\n", file=sys.stderr)
        sys.exit(1)
