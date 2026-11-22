"""
Orquestrador Central de Oráculos Modulares - Blind AI

Uso:
  python tests/run_oracles.py --module desktop    # Executa tests/desktop/oracle_desktop.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

ORACLE_REGISTRY = {
    "desktop": TESTS_DIR / "desktop" / "oracle_desktop.py",
    "winzapp": TESTS_DIR / "winzapp" / "oracle_winzapp.py",
    "windows_mcp": TESTS_DIR / "windows_mcp" / "oracle_windows_mcp.py",
    "vision": TESTS_DIR / "vision" / "oracle_vision.py",
    "docs": TESTS_DIR / "docs" / "oracle_docs.py",
    "providers": TESTS_DIR / "providers" / "oracle_providers.py",
    "channels": TESTS_DIR / "channels" / "oracle_channels.py",
    "writer": TESTS_DIR / "writer" / "oracle_writer.py",
    "audio": TESTS_DIR / "audio" / "oracle_audio.py",
    "sessions": TESTS_DIR / "sessions" / "oracle_sessions.py",
    "frontend": TESTS_DIR / "frontend" / "oracle_frontend.py",
}


def discover_oracles() -> dict[str, Path]:
    """Combina o registro padrão com qualquer novo oráculo criado futuramente em tests/*/oracle_*.py."""
    registry = dict(ORACLE_REGISTRY)
    for oracle_path in sorted(TESTS_DIR.glob("*/oracle_*.py")):
        module_name = oracle_path.parent.name.lower()
        if module_name not in registry:
            registry[module_name] = oracle_path
    return registry


def run_single_oracle(name: str, script_path: Path) -> bool:
    """Executa um oráculo modular do Blind AI."""
    rel_script = script_path.relative_to(TESTS_DIR.parent)
    print(f"\n>>> [CAPACIDADE: {name.upper()}] Rodando: {rel_script}", flush=True)
    start = time.time()
    res = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.time() - start

    if res.stdout:
        print(res.stdout, end="" if res.stdout.endswith("\n") else "\n", flush=True)
    if res.stderr:
        print(res.stderr, end="" if res.stderr.endswith("\n") else "\n", file=sys.stderr, flush=True)

    if res.returncode == 0:
        print(f">>> [CAPACIDADE: {name.upper()}] APROVADO em {elapsed:.2f}s.", flush=True)
        return True

    print(
        f">>> [CAPACIDADE: {name.upper()}] REPROVADO (Código {res.returncode}) em {elapsed:.2f}s.",
        file=sys.stderr,
        flush=True,
    )
    return False


def main():
    registry = discover_oracles()
    parser = argparse.ArgumentParser(description="Orquestrador Modular de Oráculos (1 módulo por vez)")
    parser.add_argument(
        "--module",
        "--oracle",
        dest="module",
        required=True,
        choices=list(registry.keys()),
        help="Obrigatório: executa apenas o oráculo da capacidade especificada",
    )
    args = parser.parse_args()

    path = registry[args.module]
    ok = run_single_oracle(args.module, path)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

