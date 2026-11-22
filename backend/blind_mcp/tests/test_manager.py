"""Testes do MCPManager contra um servidor MCP falso real (processo stdio de verdade)."""

import asyncio
import json
import sys
from pathlib import Path


from blind_mcp import MCPManager, ServerSpec, load_specs
from blind_mcp.config import interpolate
from blind_mcp.manager import qualified_name

FAKE = str(Path(__file__).with_name("fake_server.py"))


def spec(**kw) -> ServerSpec:
    base = dict(
        name="fake",
        command=sys.executable,
        args=[FAKE],
        disabled_tools=["blocked_tool"],
        model_hidden_tools=["secret"],
        startup_timeout=30,
        call_timeout=10,
    )
    base.update(kw)
    return ServerSpec(**base)


def run(coro_factory, specs=None, **mgr_kw):
    async def scenario():
        mgr = MCPManager(specs or [spec()], **mgr_kw)
        await mgr.start(wait=True, timeout=60)
        try:
            return await coro_factory(mgr)
        finally:
            await mgr.stop()

    return asyncio.run(scenario())


def test_connects_and_lists_tools(tmp_path):
    async def go(mgr):
        row = mgr.status()[0]
        names = {t.name for t in mgr.list_tools()}
        return row, names

    row, names = run(go, log_dir=tmp_path)
    assert row["status"] == "connected"
    assert {"echo", "add", "fail", "slow", "big", "secret", "crash"} <= names
    assert "blocked_tool" not in names  # desabilitada nao entra no catalogo


def test_tool_calls_and_errors(tmp_path):
    async def go(mgr):
        ok = await mgr.call_tool("fake", "echo", {"text": "ola"})
        add = await mgr.call_tool("fake", "add", {"a": 2, "b": 3})
        bad = await mgr.call_tool("fake", "fail", {})
        blocked = await mgr.call_tool("fake", "blocked_tool", {})
        unknown = await mgr.call_tool("nao-existe", "echo", {})
        return ok, add, bad, blocked, unknown

    ok, add, bad, blocked, unknown = run(go, log_dir=tmp_path)
    assert ok["ok"] and ok["content"] == "ola"
    assert add["ok"] and add["content"] == "5"
    assert bad["is_error"] and "boom" in bad["content"]
    assert not blocked["ok"] and "desabilitada" in blocked["content"]
    assert not unknown["ok"] and "desconhecido" in unknown["content"]


def test_timeout_and_truncation(tmp_path):
    async def go(mgr):
        slow = await mgr.call_tool("fake", "slow", {"seconds": 5}, timeout=0.5)
        big = await mgr.call_tool("fake", "big", {"n": 50000})
        after = await mgr.call_tool("fake", "echo", {"text": "ainda vivo"})
        return slow, big, after

    slow, big, after = run(go, log_dir=tmp_path, max_result_chars=1000)
    assert not slow["ok"] and "Tempo esgotado" in slow["content"]
    assert big["truncated"] and len(big["content"]) < 1100
    assert after["ok"]  # um timeout nao derruba o servidor


def test_hidden_tools_not_offered_to_model_but_callable(tmp_path):
    async def go(mgr):
        offered = {t["function"]["name"] for t in mgr.openai_tools()}
        anthropic = {t["name"] for t in mgr.anthropic_tools()}
        by_model = await mgr.call_qualified("fake__secret", {"token": "abc"}, from_model=True)
        by_ui = await mgr.call_qualified("fake__secret", {"token": "abc"}, from_model=False)
        return offered, anthropic, by_model, by_ui

    offered, anthropic, by_model, by_ui = run(go, log_dir=tmp_path)
    assert "fake__echo" in offered and "fake__secret" not in offered
    assert "fake__echo" in anthropic and "fake__secret" not in anthropic
    assert not by_model["ok"]
    assert by_ui["ok"] and by_ui["content"] == "stored:3"


def test_schemas_are_valid_function_definitions(tmp_path):
    async def go(mgr):
        return mgr.openai_tools()

    tools = run(go, log_dir=tmp_path)
    for t in tools:
        fn = t["function"]
        assert 1 <= len(fn["name"]) <= 64
        assert fn["parameters"]["type"] == "object"
    add = next(t for t in tools if t["function"]["name"] == "fake__add")
    assert set(add["function"]["parameters"]["properties"]) == {"a", "b"}


def test_restart_and_crash_recovery(tmp_path):
    async def go(mgr):
        crashed = await mgr.call_tool("fake", "crash", {})
        # O manager detecta a queda e reconecta sozinho com backoff curto: tenta ate voltar.
        recovered = {"ok": False}
        for _ in range(40):
            await asyncio.sleep(0.5)
            recovered = await mgr.call_tool("fake", "echo", {"text": "voltei"})
            if recovered["ok"]:
                break
        restarted = await mgr.restart("fake")
        after = await mgr.call_tool("fake", "echo", {"text": "reiniciado"})
        return crashed, recovered, restarted, after

    crashed, recovered, restarted, after = run(go, log_dir=tmp_path)
    assert not crashed["ok"]
    assert recovered["ok"] and recovered["content"] == "voltei"
    assert restarted["ok"]
    assert after["ok"] and after["content"] == "reiniciado"


def test_bad_command_reports_error_without_crashing(tmp_path):
    bad = ServerSpec(name="ghost", command="comando-que-nao-existe-xyz", startup_timeout=5)

    async def go(mgr):
        return mgr.status(), await mgr.call_tool("ghost", "x", {})

    async def scenario():
        mgr = MCPManager([bad, spec()], log_dir=tmp_path)
        await mgr.start(wait=True, timeout=30)
        try:
            return await go(mgr)
        finally:
            await mgr.stop()

    status, call = asyncio.run(scenario())
    by_name = {s["name"]: s for s in status}
    assert by_name["fake"]["status"] == "connected"  # um servidor ruim nao derruba os outros
    assert by_name["ghost"]["status"] in ("error", "starting")
    assert not call["ok"]


def test_disabled_server_is_not_started(tmp_path):
    async def go(mgr):
        return mgr.status()[0]

    row = run(go, specs=[spec(enabled=False)], log_dir=tmp_path)
    assert row["status"] == "disabled" and row["tool_count"] == 0


def test_qualified_name_rules():
    assert qualified_name("agent-desktop", "click") == "agent-desktop__click"
    assert qualified_name("a b", "c.d") == "a_b__c_d"
    long = qualified_name("s" * 40, "t" * 60)
    assert len(long) <= 64
    assert long == qualified_name("s" * 40, "t" * 60)  # estavel


def test_config_loading_and_interpolation(tmp_path, monkeypatch):
    monkeypatch.setenv("MINHA_VAR", "valor")
    cfg = tmp_path / "mcp.json"
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "a": {
                        "command": "${PYTHON}",
                        "args": ["--x", "${MINHA_VAR}", "${NAO_EXISTE:-padrao}", "${REPOS_DIR}/p"],
                        "cwd": "${BACKEND_DIR}",
                        "env": {"K": "${MINHA_VAR}"},
                        "disabledTools": ["T"],
                        "modelHiddenTools": ["H"],
                        "enabled": False,
                    },
                    "sem_command": {"args": []},
                }
            }
        ),
        encoding="utf-8",
    )
    specs = load_specs(cfg)
    assert [s.name for s in specs] == ["a"]
    a = specs[0]
    assert a.command == sys.executable
    assert a.args[:3] == ["--x", "valor", "padrao"]
    assert a.env == {"K": "valor"}
    assert a.disabled_tools == ["T"] and a.model_hidden_tools == ["H"] and a.enabled is False
    assert interpolate("${MINHA_VAR}") == "valor"
    assert load_specs(tmp_path / "nao-existe.json") == []


def test_real_mcp_json_is_valid():
    """O mcp.json do repositorio carrega com todas as ferramentas do Windows-MCP habilitadas por padrao."""
    specs = {s.name: s for s in load_specs(Path(__file__).resolve().parents[2] / "mcp.json")}
    assert {
        "blind",
        "windows",
        "agent-desktop",
        "blind-speech",
        "blind-docs",
        "blind-channels",
        "blind-stt",
        "blind-memory",
        "blind-schedule",
        "blind-commander",
        "blind-system",
        "blind-mail",
        "blind-drive",
        "blind-a11y",
    } == set(specs)
    assert specs["windows"].disabled_tools == []
    assert "telegram_connect" in specs["blind-channels"].model_hidden_tools
    assert {"transcribe", "prepare", "stt_status"} <= set(specs["blind-stt"].model_hidden_tools)  # audio nunca vai ao modelo
    assert specs["windows"].env.get("ANONYMIZED_TELEMETRY") == "false"
    # servidor de terceiros: versao fixa e as ferramentas que enviam arquivos para fora ficam desligadas
    a11y = specs["blind-a11y"]
    assert "vendor/a11y-mcp" in " ".join(a11y.args).replace("\\", "/")
    pins = json.loads((Path(__file__).resolve().parents[2] / "vendor" / "a11y-mcp" / "package.json").read_text(encoding="utf-8"))
    assert pins["dependencies"]["@community-access/accessibility-agents-mcp"] == "7.1.0"  # versao exata, sem ^
    assert {"glow_audit_document", "glow_fix_document"} <= set(a11y.disabled_tools)
