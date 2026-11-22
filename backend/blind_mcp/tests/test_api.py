"""Testes das rotas /api/mcp/* e, opcionalmente, da integracao real com todos os servidores do mcp.json."""

import os
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from blind_mcp import MCPManager, ServerSpec
from blind_mcp.api import router

FAKE = str(Path(__file__).with_name("fake_server.py"))


def fake_manager(tmp_path) -> MCPManager:
    return MCPManager(
        [
            ServerSpec(
                name="fake",
                command=sys.executable,
                args=[FAKE],
                model_hidden_tools=["secret"],
                disabled_tools=["blocked_tool"],
                startup_timeout=30,
            )
        ],
        log_dir=tmp_path,
    )


def test_routes_without_manager_return_503():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/api/mcp/servers").status_code == 503


def test_mcp_routes(tmp_path):

    app = FastAPI()
    app.include_router(router)
    mgr = fake_manager(tmp_path)

    # O TestClient roda o app em outro loop; o manager precisa viver no mesmo loop das chamadas.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(a):
        a.state.mcp = mgr
        await mgr.start(wait=True, timeout=60)
        yield
        await mgr.stop()

    app.router.lifespan_context = lifespan
    with TestClient(app) as client:
        servers = client.get("/api/mcp/servers").json()
        assert servers[0]["name"] == "fake" and servers[0]["status"] == "connected" and servers[0]["tool_count"] >= 6

        tools = {t["name"]: t for t in client.get("/api/mcp/tools").json()}
        assert tools["secret"]["hidden_from_model"] is True and tools["echo"]["hidden_from_model"] is False
        assert "blocked_tool" not in tools

        ok = client.post("/api/mcp/call", json={"server": "fake", "tool": "echo", "arguments": {"text": "oi"}}).json()
        assert ok["ok"] and ok["content"] == "oi"
        bad = client.post("/api/mcp/call", json={"server": "fake", "tool": "fail"}).json()
        assert not bad["ok"] and bad["is_error"]
        ui_hidden = client.post(
            "/api/mcp/call", json={"server": "fake", "tool": "secret", "arguments": {"token": "xyz"}}
        ).json()
        assert ui_hidden["ok"]  # a interface pode chamar; so o modelo nao enxerga

        assert client.post("/api/mcp/servers/fake/restart").json()["ok"] is True
        assert client.post("/api/mcp/servers/nada/restart").json()["ok"] is False
        assert client.post("/api/mcp/call", json={"server": "fake", "tool": "echo", "arguments": {"text": "pos"}}).json()["ok"]


@pytest.mark.skipif(os.environ.get("BLIND_INTEGRATION") != "1", reason="defina BLIND_INTEGRATION=1 (usa o desktop real, somente leitura)")
def test_real_stack_boots_and_shuts_down_cleanly():
    """Sobe server.py de verdade: todos os servidores do mcp.json conectam, uma ferramenta real responde
    e o encerramento nao deixa processos MCP para tras."""
    import psutil

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import server  # noqa: WPS433

    def mcp_children():
        me = psutil.Process()
        return [
            p for p in me.children(recursive=True)
            if "blind_mcp.servers" in " ".join(p.cmdline()) or "windows-mcp" in " ".join(p.cmdline())
        ]

    with TestClient(server.app) as client:
        deadline = time.time() + 120
        rows = []
        while time.time() < deadline:
            rows = client.get("/api/mcp/servers").json()
            if rows and all(r["status"] == "connected" for r in rows):
                break
            time.sleep(1)
        assert {r["name"]: r["status"] for r in rows} == {
            n: "connected"
            for n in ("windows", "agent-desktop", "blind-speech", "blind-docs", "blind-channels", "blind-stt")
        }
        assert client.get("/").status_code == 200
        status = client.get("/api/status").json()
        assert len(status["mcp"]) == 6
        res = client.post("/api/mcp/call", json={"server": "windows", "tool": "DisplayInventory"}).json()
        assert res["ok"] and "DISPLAY" in res["content"]
        # PowerShell e Registry habilitados por padrao no catalogo
        win_tools = {t["name"] for t in client.get("/api/mcp/tools").json() if t["server"] == "windows"}
        assert {"PowerShell", "Registry"} <= win_tools
        assert mcp_children()

    time.sleep(2)
    assert mcp_children() == [], "processos MCP ficaram vivos apos o desligamento"
