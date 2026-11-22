"""
Oráculo da Capacidade: Interface Electron (src/renderer) e contratos de acessibilidade
Local: tests/frontend/oracle_frontend.py
Valida a fonte do renderer (sem abrir o Electron):
1. Os 7 botões primários na tela inicial e nenhuma seção obsoleta.
2. Botão de chat sem falso 'aria-expanded'.
3. Formatador de listas semânticas <ol>, <ul> e <li> para leitores de tela.
4. Todas as telas com h1 focável e região identificada.
5. Segurança do renderer: CSP restritiva, sem fetch/innerHTML/script inline.
6. Ditado por voz gravando no app e transcrevendo com o Whisper do backend.
7. Ausência de emojis.
Os testes com o Electron real ficam em scripts/e2e-renderer.js.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from oracle_base import log
from renderer_contracts import check_renderer_contracts


def run_frontend_oracle():
    log("ORACULO-FRONTEND", "Validando contratos do renderer Electron (src/renderer)...")
    result = check_renderer_contracts()
    log("ORACULO-FRONTEND", f"   OK -> {result['files']} arquivos e {result['screens']} telas verificados.")
    log("ORACULO-FRONTEND", "STATUS: 100% APROVADO! Todos os contratos de acessibilidade do front-end íntegros.")


if __name__ == "__main__":
    try:
        run_frontend_oracle()
        sys.exit(0)
    except Exception as e:
        print(f"\n[FALHA NO ORÁCULO FRONTEND] {e}\n", file=sys.stderr)
        sys.exit(1)
