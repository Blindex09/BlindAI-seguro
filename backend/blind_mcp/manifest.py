"""Manifesto das ferramentas do Blind: nomes EXATOS de cada ferramenta de cada servidor.

O `comecar` devolve esses nomes para o modelo chamar a ferramenta pelo nome, em vez de dizer "nao tenho" quando ela existe.
O arquivo `tools_manifest.json` e gerado por `python scripts/gerar-manifesto-ferramentas.py` e um teste falha se ficar
desatualizado. Servidores de terceiros (windows, blind-commander) entram como lista de referencia.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Dict, List

MANIFEST_FILE = Path(__file__).with_name("tools_manifest.json")

# servidor do mcp.json -> modulo que o implementa
OWN_SERVERS: Dict[str, str] = {
    "blind": "blind",
    "agent-desktop": "agent_desktop",
    "blind-speech": "speech",
    "blind-docs": "docs",
    "blind-channels": "channels",
    "blind-memory": "memory",
    "blind-schedule": "schedule",
    "blind-system": "system",
    "blind-stt": "stt",
    "blind-mail": "mail",
    "blind-drive": "drive",
}

# Terceiros: referencia (nomes vistos nas conversas). O windows tem as de teclado/mouse removidas via mcp.json.
EXTERNAL_REFERENCE: Dict[str, List[str]] = {
    "windows": ["App", "Clipboard", "ControlStatus", "DisplayInventory", "FileSystem", "Notification", "PowerShell", "Process",
                "Registry", "Scrape", "Screenshot", "Snapshot", "Wait", "WaitFor", "Zoom"],
    "blind-commander": ["create_directory", "edit_block", "force_terminate", "get_config", "get_file_info",
                        "get_more_search_results", "get_recent_tool_calls", "get_usage_stats", "interact_with_process",
                        "kill_process", "list_directory", "list_processes", "list_searches", "list_sessions", "move_file",
                        "read_file", "read_multiple_files", "read_process_output", "set_config_value", "start_process",
                        "start_search", "stop_search", "write_file", "write_pdf"],
}


def _cached_names(server: str) -> List[str]:
    try:
        data = json.loads((Path(__file__).with_name("tools_cache") / f"{server}.json").read_text(encoding="utf-8"))
        return [t["name"] for t in data["tools"]]
    except Exception:  # noqa: BLE001
        return []


def build_manifest() -> Dict[str, Dict[str, List[str]]]:
    """Importa cada servidor proprio e le as ferramentas registradas (fonte da verdade: o codigo)."""
    own: Dict[str, List[str]] = {}
    for server, module in OWN_SERVERS.items():
        mod = importlib.import_module(f"blind_mcp.servers.{module}")
        own[server] = sorted(t.name for t in mod.mcp._tool_manager.list_tools())
    external: Dict[str, List[str]] = {}
    for server, fallback in EXTERNAL_REFERENCE.items():
        cached = _cached_names(server)  # lista real, lida do cache gerado a partir do servidor de verdade
        external[server] = sorted(cached or fallback)
    return {"proprios": own, "terceiros_referencia": external}


def load_manifest() -> Dict[str, Dict[str, List[str]]]:
    try:
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"proprios": {}, "terceiros_referencia": {}}


def write_manifest() -> Path:
    MANIFEST_FILE.write_text(json.dumps(build_manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return MANIFEST_FILE
