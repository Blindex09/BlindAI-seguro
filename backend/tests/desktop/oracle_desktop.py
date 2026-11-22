"""
Oráculo da Capacidade: Interação com a Tela Desktop via servidor MCP (agent-desktop)
Local: tests/desktop/oracle_desktop.py

Valida, somente leitura (nada é clicado nem digitado):
1. agent-desktop conectado, com permissão de acessibilidade concedida.
2. Snapshot da janela ativa com @ref e lista de janelas.
3. Contexto de tela e bandeja (agent-desktop).
4. Área de transferência legível.
5. Chat: pergunta livre sobre a tela é respondida com tool calling nativo (ferramenta MCP realmente chamada).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oracle_base import log, request_json


def mcp_call(server: str, tool: str, arguments: dict | None = None) -> dict:
    return request_json(
        "/api/mcp/call", method="POST", data={"server": server, "tool": tool, "arguments": arguments or {}}
    )


def run_desktop_oracle():
    log("ORACULO-DESKTOP", "Iniciando validação de Interação com a Tela Desktop (MCP)...")

    log("ORACULO-DESKTOP", "1. Servidor agent-desktop conectado...")
    servers = {s["name"]: s for s in request_json("/api/mcp/servers", method="GET")}
    assert servers.get("agent-desktop", {}).get("status") == "connected", f"Servidor 'agent-desktop' não conectou: {servers.get('agent-desktop')}"
    caps = mcp_call("agent-desktop", "status")
    assert caps.get("ok") and '"granted"' in caps["content"], f"agent-desktop sem permissão de acessibilidade: {caps}"
    log("ORACULO-DESKTOP", "   OK -> agent-desktop conectado e com acessibilidade concedida.")

    log("ORACULO-DESKTOP", "2. Snapshot com @ref e lista de janelas...")
    apps_res = mcp_call("agent-desktop", "list_apps")
    assert apps_res.get("ok"), f"list_apps falhou: {apps_res}"
    app_names = [a["name"] for a in json.loads(apps_res["content"]).get("apps", [])]
    assert app_names, "Nenhum aplicativo com janela encontrado."
    # Nao depende de qual janela esta em foco: tenta os aplicativos abertos ate achar uma arvore com @ref.
    snap, target_app = {}, None
    for name in app_names[:8]:
        snap = mcp_call("agent-desktop", "snapshot", {"app": name, "interactive_only": True})
        if snap.get("ok") and "@" in snap["content"]:
            target_app = name
            break
    assert target_app, f"Nenhum dos aplicativos {app_names[:8]} devolveu snapshot com @ref (ultimo: {snap})"
    wins = mcp_call("agent-desktop", "list_windows")
    assert wins.get("ok"), f"list_windows falhou: {wins}"
    log("ORACULO-DESKTOP", "   OK -> snapshot com @ref e janelas listadas.")

    log("ORACULO-DESKTOP", "3. Contexto de tela e bandeja (screen_context)...")
    ctx = mcp_call("agent-desktop", "screen_context")
    assert ctx.get("ok") and ctx.get("content"), f"screen_context vazio: {ctx}"
    tray = mcp_call("agent-desktop", "list_tray")
    assert tray.get("ok"), f"list_tray falhou: {tray}"
    log("ORACULO-DESKTOP", "   OK -> contexto de tela e bandeja lidos.")

    log("ORACULO-DESKTOP", "4. Área de transferência legível...")
    clip = mcp_call("agent-desktop", "clipboard", {"action": "get"})
    assert clip.get("ok"), f"clipboard get falhou: {clip}"
    log("ORACULO-DESKTOP", "   OK -> clipboard lido.")

    log("ORACULO-DESKTOP", "5. Chat com tool calling nativo (pergunta somente leitura)...")
    sess = request_json("/api/sessions", method="POST", data={"title": "Oráculo Desktop MCP", "source": "chat"})
    chat = request_json(
        "/api/chat",
        method="POST",
        data={"message": "quais janelas estão abertas agora? Use as ferramentas da tela.", "session_id": sess.get("id")},
    )
    reply = (chat.get("reply") or "").strip()
    assert chat.get("status") == "success" and reply, f"Chat falhou: {chat}"
    assert chat.get("actions"), f"O modelo respondeu sem chamar nenhuma ferramenta MCP: {chat}"
    assert all(a["status"] == "success" for a in chat["actions"]), f"Ferramenta falhou: {chat['actions']}"
    assert "*" not in reply, f"Resposta contém asteriscos proibidos: {reply}"
    log("ORACULO-DESKTOP", f"   OK -> {len(chat['actions'])} chamada(s) MCP reais; resposta: '{reply[:80]}...'")

    log("ORACULO-DESKTOP", "STATUS: 100% APROVADO! Interação com a tela validada via MCP.")


if __name__ == "__main__":
    try:
        run_desktop_oracle()
        sys.exit(0)
    except Exception as e:
        print(f"\n[FALHA NO ORÁCULO DESKTOP] {e}\n", file=sys.stderr)
        sys.exit(1)
