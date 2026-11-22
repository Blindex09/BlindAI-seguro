"""Gera backend/blind_mcp/tools_manifest.json (nomes exatos das ferramentas do Blind). Rode depois de criar/renomear ferramenta."""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from blind_mcp.manifest import build_manifest, write_manifest  # noqa: E402

if __name__ == "__main__":
    if "--cache" in sys.argv:
        # Tambem refaz o cache de ferramentas dos servidores carregados sob demanda (sobe cada um uma vez, le e desliga).
        import subprocess

        from blind_mcp.config import load_specs

        for spec in load_specs():
            if spec.lazy and spec.enabled:
                subprocess.run([sys.executable, "-m", "blind_mcp.lazy_proxy", "--server", spec.name, "--build-cache"],
                               cwd=str(BACKEND), env={**__import__("os").environ, "PYTHONPATH": str(BACKEND)}, check=False)
    path = write_manifest()
    total = sum(len(v) for v in build_manifest()["proprios"].values())
    print(f"gravado {path} com {total} ferramentas proprias")
