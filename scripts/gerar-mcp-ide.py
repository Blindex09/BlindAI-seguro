"""Conecta os servidores do Blind (backend/mcp.json -> .mcp.json) as IDEs: VS Code, Cursor, Codex e Antigravity.

Uso:  python scripts/gerar-mcp-ide.py              # mostra o que faria (nao grava nada)
      python scripts/gerar-mcp-ide.py --aplicar    # grava nas quatro IDEs, com copia .bak-blind ao lado
      python scripts/gerar-mcp-ide.py --aplicar --so vscode,cursor
      python scripts/gerar-mcp-ide.py --remover    # tira so o que o Blind pos (nomes do mcp.json)

Regras: mescla sem apagar servidores que a pessoa ja tem; so troca os do proprio Blind. Roda gerar-mcp-claude.py
antes para garantir o .mcp.json atual. blind-stt (audio, tudo escondido) fica de fora. As IDEs nao tem `deny` por
ferramenta: telegram_connect (token do bot) aparece para o modelo delas; por isso o Blind guarda o token so pelo
app (Alt+Shift+W) e nunca pede token no chat.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()
APPDATA = Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming"))
FORA = {"blind-stt"}
MARCA_I, MARCA_F = "# >>> blind-ai (gerado por scripts/gerar-mcp-ide.py) >>>", "# <<< blind-ai <<<"


def servidores() -> dict:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "gerar-mcp-claude.py")], check=True, capture_output=True)
    data = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    return {n: e for n, e in data.items() if n not in FORA}


def _backup(path: Path) -> None:
    if path.is_file() and path.stat().st_size:
        path.with_name(path.name + ".bak-blind").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def _json_merge(path: Path, chave: str, novos: dict, remover: set, extra=None) -> str:
    cfg = json.loads(path.read_text(encoding="utf-8")) if path.is_file() and path.stat().st_size else {}
    alvo = cfg.setdefault(chave, {})
    for n in remover:
        alvo.pop(n, None)
    for n, e in novos.items():
        alvo[n] = {**(extra or {}), **e}
    return json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"


def _toml_str(v: str) -> str:
    return json.dumps(v, ensure_ascii=False)  # JSON string e string TOML valida (aspas duplas, escapes)


def _toml_bloco(novos: dict) -> str:
    out = [MARCA_I]
    for n, e in novos.items():
        out += [f'[mcp_servers.{_toml_str(n)}]', f"command = {_toml_str(e['command'])}",
                "args = [" + ", ".join(_toml_str(a) for a in e.get("args", [])) + "]"]
        if e.get("env"):
            out.append(f'[mcp_servers.{_toml_str(n)}.env]')
            out += [f"{_toml_str(k)} = {_toml_str(v)}" for k, v in e["env"].items()]
        out.append("")
    out.append(MARCA_F)
    return "\n".join(out) + "\n"


def _toml_merge(path: Path, novos: dict) -> str:
    atual = path.read_text(encoding="utf-8") if path.is_file() else ""
    atual = re.sub(re.escape(MARCA_I) + r".*?" + re.escape(MARCA_F) + r"\n?", "", atual, flags=re.S)
    # o Codex nao aceita a mesma tabela duas vezes: tira tabelas antigas com o mesmo nome fora do bloco
    for n in novos:
        atual = re.sub(rf'(?ms)^\[mcp_servers\.(?:"{re.escape(n)}"|{re.escape(n)})(?:\.env)?\]\n.*?(?=^\[|\Z)', "", atual)
    return atual.rstrip() + "\n\n" + _toml_bloco(novos) if novos else atual.rstrip() + "\n"


def alvos() -> dict:
    return {
        "vscode": APPDATA / "Code" / "User" / "mcp.json",
        "cursor": HOME / ".cursor" / "mcp.json",
        "antigravity": HOME / ".gemini" / "antigravity" / "mcp_config.json",
        "codex": HOME / ".codex" / "config.toml",
    }


def texto_para(ide: str, path: Path, novos: dict, remover: set) -> str:
    if ide == "vscode":
        return _json_merge(path, "servers", novos, remover, {"type": "stdio"})
    if ide in ("cursor", "antigravity"):
        return _json_merge(path, "mcpServers", novos, remover)
    return _toml_merge(path, novos)


def main() -> int:
    args = sys.argv[1:]
    aplicar, remover = "--aplicar" in args, "--remover" in args
    so = set(args[args.index("--so") + 1].split(",")) if "--so" in args else None
    novos = servidores()
    nomes = set(novos)
    for ide, path in alvos().items():
        if so and ide not in so:
            continue
        try:
            texto = texto_para(ide, path, {} if remover else novos, nomes if remover else set())
        except Exception as exc:  # noqa: BLE001
            print(f"{ide}: ERRO ao preparar ({exc}); nada gravado")
            continue
        if not aplicar and not remover:
            print(f"{ide}: gravaria {len(novos)} servidores em {path}")
            continue
        _backup(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(texto, encoding="utf-8")
        print(f"{ide}: {'removido' if remover else 'gravado'} em {path} (reabra a IDE)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
