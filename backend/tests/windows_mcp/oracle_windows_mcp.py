"""
Oráculo Modular 10: Windows-MCP (CursorTouch/Windows-MCP) rodando como servidor MCP, sem modificação.
Local: tests/windows_mcp/oracle_windows_mcp.py

Valida, pelas rotas /api/mcp/*, que o servidor original está conectado e que o Blind AI o usa de forma segura.
Todas as chamadas são somente leitura (não movem o mouse nem clicam).
  1. Servidor 'windows' conectado e com as ferramentas oficiais no catálogo
  2. DisplayInventory real
  3. Process (listar)
  4. ControlStatus (política de controle do desktop)
  5. PowerShell e Registry habilitados por padrão no mcp.json
"""

import json
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from oracle_base import log, request_json


def mcp_call(server: str, tool: str, arguments: dict | None = None) -> dict:
    return request_json(
        "/api/mcp/call", method="POST", data={"server": server, "tool": tool, "arguments": arguments or {}}
    )


def run_windows_mcp_oracle():
    log("ORACULO-WINDOWS-MCP", "Iniciando validação do Windows-MCP como servidor MCP...")
    status_res = request_json("/api/status", method="GET")
    assert status_res.get("status") == "ready", f"Servidor Blind AI não está pronto: {status_res}"

    log("ORACULO-WINDOWS-MCP", "1. Servidor 'windows' conectado e ferramentas oficiais no catálogo...")
    servers = {s["name"]: s for s in request_json("/api/mcp/servers", method="GET")}
    assert "windows" in servers, f"Servidor 'windows' ausente do mcp.json: {list(servers)}"
    assert servers["windows"]["status"] == "connected", f"Windows-MCP não conectou: {servers['windows']}"
    tools = {t["name"] for t in request_json("/api/mcp/tools", method="GET") if t["server"] == "windows"}
    for expected in ("Snapshot", "DisplayInventory", "Click", "Move", "Shortcut", "Process", "ControlStatus"):
        assert expected in tools, f"Ferramenta '{expected}' ausente em {sorted(tools)}"
    log("ORACULO-WINDOWS-MCP", f"   OK -> {len(tools)} ferramentas Windows-MCP no catálogo.")

    log("ORACULO-WINDOWS-MCP", "2. DisplayInventory...")
    disp = mcp_call("windows", "DisplayInventory")
    assert disp.get("ok"), f"DisplayInventory falhou: {disp}"
    displays = json.loads(disp["content"])
    assert len(displays) >= 1 and "resolution" in displays[0], f"Inventário de monitores inválido: {disp}"
    log("ORACULO-WINDOWS-MCP", f"   OK -> {len(displays)} monitor(es), principal {displays[0]['resolution']}.")

    log("ORACULO-WINDOWS-MCP", "3. Process (listar)...")
    proc = mcp_call("windows", "Process", {"mode": "list", "name": "python", "limit": 5})
    assert proc.get("ok") and proc.get("content"), f"Process list falhou: {proc}"
    log("ORACULO-WINDOWS-MCP", "   OK -> processos listados.")

    log("ORACULO-WINDOWS-MCP", "4. ControlStatus...")
    ctrl = mcp_call("windows", "ControlStatus")
    assert ctrl.get("ok"), f"ControlStatus falhou: {ctrl}"
    log("ORACULO-WINDOWS-MCP", "   OK -> política de controle do desktop respondeu.")

    log("ORACULO-WINDOWS-MCP", "5. PowerShell e Registry habilitados por padrão no catálogo...")
    for expected in ("PowerShell", "Registry"):
        assert expected in tools, f"Ferramenta '{expected}' deveria estar habilitada em {sorted(tools)}"
    log("ORACULO-WINDOWS-MCP", "   OK -> todas as ferramentas do Windows-MCP habilitadas no mcp.json.")

    log("ORACULO-WINDOWS-MCP", "STATUS: 100% APROVADO! Windows-MCP integrado como servidor MCP.")


if __name__ == "__main__":
    try:
        run_windows_mcp_oracle()
        sys.exit(0)
    except Exception as e:
        print(f"\n[FALHA NO ORÁCULO WINDOWS-MCP] {e}\n", file=sys.stderr)
        sys.exit(1)
