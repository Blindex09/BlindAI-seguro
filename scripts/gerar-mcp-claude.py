"""Gera o .mcp.json (Claude Code) a partir de backend/mcp.json, a unica fonte da verdade.

Uso:  python scripts/gerar-mcp-claude.py            # grava .mcp.json na raiz do projeto
      python scripts/gerar-mcp-claude.py --desktop  # tambem grava no app Claude Desktop (reinicie o app depois)
      python scripts/gerar-mcp-claude.py --stdout   # so mostra

Troca ${PYTHON}, ${BACKEND_DIR}, ${REPOS_DIR} e ${DATA_DIR} por caminhos reais (o Claude Code nao conhece esses
marcadores) e gera as regras `deny` das ferramentas em `modelHiddenTools`, para o Claude tambem nao oferecer
ao modelo as que recebem segredos ou audio (ex.: telegram_connect).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from blind_mcp.config import load_specs  # noqa: E402


def desktop_config_path() -> Path:
    """O app Claude (Microsoft Store) le a configuracao em Local\\Claude-Data\\claude_*\\claude_desktop_config.json.
    O arquivo em %APPDATA%\\Claude NAO e o que ele usa (descoberto em 17/11/2026)."""
    import os

    local = Path(os.environ.get("LOCALAPPDATA", ""))
    for found in sorted((local / "Claude-Data").glob("claude_*/claude_desktop_config.json")):
        return found
    return Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"


def write_desktop(servers: dict, remove: list | None = None) -> None:
    """Mescla no claude_desktop_config.json sem apagar nada que ja exista. Sem ferramentas escondidas: o
    Desktop nao tem `deny` por arquivo, e blind-stt (todas as ferramentas escondidas) fica de fora."""
    path = desktop_config_path()
    cfg = json.loads(path.read_text(encoding="utf-8")) if path.is_file() and path.stat().st_size else {}
    if path.is_file() and path.stat().st_size:
        path.with_suffix(".json.bak").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    cfg.setdefault("mcpServers", {}).update({n: e for n, e in servers.items() if n != "blind-stt"})
    for name in remove or []:  # servidores desligados no mcp.json saem do app tambem
        cfg["mcpServers"].pop(name, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Claude Desktop: {path} (reinicie o app para carregar)")


def main() -> int:
    servers, deny, disabled = {}, [], []
    lazy_on = "--no-lazy" not in sys.argv
    for spec in load_specs():
        if not spec.enabled:
            disabled.append(spec.name)
            continue
        if spec.lazy and lazy_on:
            # Carrega sob demanda: o Claude abre so o proxy; o servidor real sobe na primeira chamada (cache de ferramentas).
            entry = {"command": sys.executable, "args": ["-m", "blind_mcp.lazy_proxy", "--server", spec.name]}
            env = {"PYTHONPATH": str(ROOT / "backend"), "PYTHONUTF8": "1"}
        else:
            entry = {"command": spec.command, "args": spec.args}
            env = {k: v for k, v in spec.env.items()}
            if spec.cwd:
                # O .mcp.json nao tem "cwd": o PYTHONPATH faz `python -m blind_mcp.servers.x` achar o pacote.
                env.setdefault("PYTHONPATH", spec.cwd)
        if env:
            entry["env"] = env
        servers[spec.name] = entry
        deny += [f"mcp__{spec.name}__{t}" for t in spec.model_hidden_tools]
        deny += [f"mcp__{spec.name}__{t}" for t in spec.disabled_tools]
    out = {"mcpServers": servers}
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    if "--desktop" in sys.argv:
        write_desktop(servers, disabled)
    if "--stdout" in sys.argv:
        print(text)
        print("deny:", json.dumps(deny))
        return 0
    (ROOT / ".mcp.json").write_text(text, encoding="utf-8")
    canal = ROOT / "canal-claude"  # a sessao trancada dos canais usa os mesmos servidores (ver canal-claude/CLAUDE.md)
    if canal.is_dir():
        (canal / ".mcp.json").write_text(text, encoding="utf-8")
    print(f"gravado {ROOT / '.mcp.json'} com {len(servers)} servidores")
    print("ferramentas escondidas do modelo (deny):", ", ".join(deny) or "nenhuma")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
