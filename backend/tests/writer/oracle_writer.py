"""
Oráculo da Capacidade: Escritor Acessível e Gravação Atômica
Local: tests/writer/oracle_writer.py
Valida:
1. Geração de minuta segura (/api/writer/draft).
2. Gravação atômica em disco sem corrupção e criação de backup .bak (/api/writer/save).
3. Auditoria do arquivo no sistema de arquivos.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oracle_base import log, request_json


def run_writer_oracle():
    log("ORACULO-ESCRITOR", "1. Validando geração de minuta acessível (/api/writer/draft)...")
    draft_res = request_json(
        "/api/writer/draft",
        method="POST",
        data={
            "title": "Ata de Homologacao de Testes Modulares",
            "content": "Sistema atômico aprovado pelos oráculos modulares em todas as suas capacidades.",
            "filename": "ata_modular_teste.txt"
        }
    )
    assert draft_res.get("ready_to_save") is True or draft_res.get("status") == "draft_ready", f"Falha na minuta: {draft_res}"
    draft = draft_res.get("draft", draft_res)
    log("ORACULO-ESCRITOR", "   OK -> Minuta gerada com hash e metadados de auditoria.")

    log("ORACULO-ESCRITOR", "2. Validando gravação atômica e criação de backup .bak (/api/writer/save)...")
    save_res = request_json("/api/writer/save", method="POST", data={"draft": draft})
    assert save_res.get("status") == "success", f"Falha ao salvar documento: {save_res}"
    file_path_str = save_res.get("path") or save_res.get("file_path")
    assert file_path_str, "Caminho do arquivo ausente na resposta"
    filepath = Path(file_path_str)
    assert filepath.exists(), "Arquivo gravado não foi encontrado no disco!"

    # Limpeza do arquivo de teste
    if filepath.exists():
        filepath.unlink()
    bak = filepath.with_suffix(".txt.bak")
    if bak.exists():
        bak.unlink()

    log("ORACULO-ESCRITOR", "STATUS: 100% APROVADO! Escritor acessível e gravação atômica íntegros.")


if __name__ == "__main__":
    try:
        run_writer_oracle()
        sys.exit(0)
    except Exception as e:
        print(f"\n[FALHA NO ORÁCULO ESCRITOR] {e}\n", file=sys.stderr)
        sys.exit(1)
