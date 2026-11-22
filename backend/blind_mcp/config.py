"""Carrega o mcp.json do Blind AI (formato mcpServers, no estilo Claude Desktop/Cursor).

Cada servidor MCP e um processo separado, com seu proprio ambiente. O Blind AI so conversa
com ele pelo protocolo; nao importa nem modifica o codigo interno do servidor.

Variaveis aceitas em command/args/cwd/env: ${BACKEND_DIR}, ${REPOS_DIR}, ${PYTHON},
${DATA_DIR} e qualquer variavel de ambiente (${NOME} ou ${NOME:-padrao}).
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


@dataclass
class ServerSpec:
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    enabled: bool = True
    disabled_tools: List[str] = field(default_factory=list)
    # Ferramentas que a interface/API pode chamar, mas que nao sao oferecidas ao modelo de IA
    # (por exemplo, as que recebem segredos como tokens).
    model_hidden_tools: List[str] = field(default_factory=list)
    startup_timeout: float = 60.0
    call_timeout: float = 60.0
    description: str = ""
    # "claude": servidor so para o Claude (Code/Desktop). O app Electron nao o inicia nem o oferece ao modelo.
    client_only: Optional[str] = None
    # True: no Claude, o servidor so e iniciado na primeira chamada (via blind_mcp.lazy_proxy); a lista de ferramentas vem de cache.
    lazy: bool = False
    # Segundos parado ate descarregar o servidor real (so com lazy). 0 = nunca descarrega (ex.: WhatsApp precisa ficar conectado).
    lazy_idle_seconds: Optional[float] = None


def default_data_dir() -> Path:
    return Path(os.environ.get("BLIND_DATA_DIR") or (BACKEND_DIR / "data"))


def _variables() -> Dict[str, str]:
    return {
        "BACKEND_DIR": str(BACKEND_DIR),
        "REPOS_DIR": os.environ.get("BLIND_REPOS_DIR", r"C:\repos ia"),
        "PYTHON": sys.executable,
        "DATA_DIR": str(default_data_dir()),
    }


def interpolate(value: str, variables: Optional[Dict[str, str]] = None) -> str:
    table = variables or _variables()

    def repl(m: "re.Match[str]") -> str:
        key, default = m.group(1), m.group(2)
        if key in table:
            return table[key]
        return os.environ.get(key, default if default is not None else "")

    return _VAR.sub(repl, value)


def config_path() -> Path:
    return Path(os.environ.get("BLIND_MCP_CONFIG") or (BACKEND_DIR / "mcp.json"))


def load_specs(path: Optional[Path] = None) -> List[ServerSpec]:
    """Le o arquivo e devolve os servidores. Arquivo ausente ou invalido gera lista vazia."""
    cfg = Path(path) if path else config_path()
    if not cfg.is_file():
        return []
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    servers = raw.get("mcpServers") or {}
    table = _variables()
    specs: List[ServerSpec] = []
    for name, entry in servers.items():
        if not isinstance(entry, dict) or not entry.get("command"):
            continue
        specs.append(
            ServerSpec(
                name=name,
                command=interpolate(str(entry["command"]), table),
                args=[interpolate(str(a), table) for a in entry.get("args", [])],
                env={str(k): interpolate(str(v), table) for k, v in (entry.get("env") or {}).items()},
                cwd=interpolate(str(entry["cwd"]), table) if entry.get("cwd") else None,
                enabled=bool(entry.get("enabled", True)),
                disabled_tools=[str(t) for t in entry.get("disabledTools", [])],
                model_hidden_tools=[str(t) for t in entry.get("modelHiddenTools", [])],
                startup_timeout=float(entry.get("startupTimeout", 60)),
                call_timeout=float(entry.get("callTimeout", 60)),
                description=str(entry.get("description", "")),
                client_only=str(entry["clientOnly"]) if entry.get("clientOnly") else None,
                lazy=bool(entry.get("lazy", False)),
                lazy_idle_seconds=float(entry["lazyIdleSeconds"]) if entry.get("lazyIdleSeconds") is not None else None,
            )
        )
    return specs
