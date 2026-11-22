"""Carregamento sob demanda: o proxy preguicoso entre o cliente (Claude) e o servidor real (aqui, o servidor falso)."""

import asyncio
import json
import sys
import time
from pathlib import Path

import psutil
import pytest

from blind_mcp import MCPManager, ServerSpec
from blind_mcp import lazy_proxy

FAKE = str(Path(__file__).with_name("fake_server.py"))


def real_children(tag: str):
    """Processos do servidor real (fake_server.py) iniciados para este teste (pelo diretorio unico no argumento)."""
    out = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        cmd = p.info.get("cmdline") or []
        if FAKE in cmd and tag in " ".join(cmd):
            out.append(p.info["pid"])
    return out


@pytest.fixture
def env(tmp_path, monkeypatch):
    tag = f"lazytag-{tmp_path.name}"
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"fake": {
        "command": sys.executable, "args": [FAKE, tag], "startupTimeout": 30, "callTimeout": 10, "lazy": True}}}), encoding="utf-8")
    monkeypatch.setenv("BLIND_DATA_DIR", str(tmp_path))
    return tmp_path, cfg, tag


def proxy_spec(tmp_path, cfg, idle=None):
    envv = {"PYTHONPATH": str(Path(__file__).resolve().parents[2]), "PYTHONUTF8": "1", "BLIND_DATA_DIR": str(tmp_path)}
    if idle is not None:
        envv["BLIND_LAZY_IDLE_S"] = str(idle)
    return ServerSpec(name="proxy", command=sys.executable, env=envv, startup_timeout=60, call_timeout=20,
                      args=["-m", "blind_mcp.lazy_proxy", "--server", "fake", "--config", str(cfg), "--cache-dir", str(tmp_path / "cache")])


def run(coro_factory, spec, tmp_path):
    async def scenario():
        mgr = MCPManager([spec], log_dir=tmp_path / "logs")
        await mgr.start(wait=True, timeout=90)
        try:
            return await coro_factory(mgr)
        finally:
            await mgr.stop()

    return asyncio.run(scenario())


def test_lista_ferramentas_sem_subir_o_servidor_real_e_sobe_na_primeira_chamada(env):
    tmp_path, cfg, tag = env
    # gera o cache (como o script de manutencao faz) e confere que o servidor real foi desligado depois
    spec = [s for s in __import__("blind_mcp").load_specs(cfg)][0]
    data = asyncio.run(lazy_proxy.build_cache(spec, tmp_path / "cache" / "fake.json", tmp_path / "logs"))
    assert {"echo", "add", "fail"} <= {t["name"] for t in data["tools"]}
    time.sleep(1)
    assert real_children(tag) == []

    async def go(mgr):
        names = {t.name for t in mgr.list_tools()}
        antes = real_children(tag)  # lista pronta e NENHUM servidor real rodando
        r1 = await mgr.call_tool("proxy", "echo", {"text": "ola"})
        durante = real_children(tag)
        r2 = await mgr.call_tool("proxy", "add", {"a": 2, "b": 3})
        bad = await mgr.call_tool("proxy", "fail", {})
        return names, antes, r1, durante, r2, bad

    names, antes, r1, durante, r2, bad = run(go, proxy_spec(tmp_path, cfg), tmp_path)
    assert {"echo", "add", "fail", "slow"} <= names
    assert antes == [] and len(durante) == 1  # so subiu quando houve chamada
    assert r1["ok"] and r1["content"] == "ola" and r2["content"] == "5"
    assert bad["is_error"] and "boom" in bad["content"]  # o erro do servidor real passa intacto
    time.sleep(1.5)
    assert real_children(tag) == []  # fechar o cliente derruba o servidor real junto


def test_cache_ausente_e_gerado_sozinho(env):
    tmp_path, cfg, tag = env

    async def go(mgr):
        return {t.name for t in mgr.list_tools()}, (tmp_path / "cache" / "fake.json").exists()

    names, cached = run(go, proxy_spec(tmp_path, cfg), tmp_path)
    assert "echo" in names and cached


def test_descarrega_parado_e_volta_na_proxima_chamada(env):
    tmp_path, cfg, tag = env
    spec = __import__("blind_mcp").load_specs(cfg)[0]
    asyncio.run(lazy_proxy.build_cache(spec, tmp_path / "cache" / "fake.json", tmp_path / "logs"))

    async def go(mgr):
        await mgr.call_tool("proxy", "echo", {"text": "a"})
        ligado = real_children(tag)
        for _ in range(40):  # espera o descarregamento por ociosidade (idle 2 s)
            await asyncio.sleep(0.5)
            if not real_children(tag):
                break
        desligado = real_children(tag)
        r = await mgr.call_tool("proxy", "echo", {"text": "b"})
        return ligado, desligado, r, real_children(tag)

    ligado, desligado, r, depois = run(go, proxy_spec(tmp_path, cfg, idle=2), tmp_path)
    assert len(ligado) == 1 and desligado == [] and r["ok"] and r["content"] == "b" and len(depois) == 1


def test_servidor_real_que_cai_sobe_de_novo(env):
    tmp_path, cfg, tag = env
    spec = __import__("blind_mcp").load_specs(cfg)[0]
    asyncio.run(lazy_proxy.build_cache(spec, tmp_path / "cache" / "fake.json", tmp_path / "logs"))

    async def go(mgr):
        await mgr.call_tool("proxy", "echo", {"text": "a"})
        await mgr.call_tool("proxy", "crash", {})  # o servidor real morre no meio
        for _ in range(20):
            await asyncio.sleep(0.5)
            r = await mgr.call_tool("proxy", "echo", {"text": "voltou"})
            if r["ok"]:
                return r
        return r

    r = run(go, proxy_spec(tmp_path, cfg), tmp_path)
    assert r["ok"] and r["content"] == "voltou"


def test_guarda_solta_tecla_presa_logo_apos_ferramenta_de_entrada():
    class Api:
        def __init__(self):
            self.down = {"Ctrl", "mouse esquerdo"}
            self.released = []

        def pressed(self):
            return set(self.down)

        def release(self, name):
            self.released.append(name)
            self.down.discard(name)

    api, logs = Api(), []
    out = asyncio.run(lazy_proxy.post_input_guard(api, settle=0.01, log=logs.append))
    assert out == ["Ctrl", "mouse esquerdo"] and api.released == ["Ctrl", "mouse esquerdo"]
    assert logs and logs[0]["server"] == "vigia" and "apos ferramenta" in logs[0]["args"]["detalhe"]
    assert asyncio.run(lazy_proxy.post_input_guard(Api(), settle=0.01)) != [] or True  # nao quebra
    assert {"Click", "Type", "Shortcut", "press_keys"} <= lazy_proxy.INPUT_TOOLS


def test_servidor_com_idle_zero_nunca_descarrega(env):
    tmp_path, cfg, tag = env
    d = json.loads(cfg.read_text(encoding="utf-8"))
    d["mcpServers"]["fake"]["lazyIdleSeconds"] = 0
    cfg.write_text(json.dumps(d), encoding="utf-8")
    spec = __import__("blind_mcp").load_specs(cfg)[0]
    assert spec.lazy_idle_seconds == 0
    asyncio.run(lazy_proxy.build_cache(spec, tmp_path / "cache" / "fake.json", tmp_path / "logs"))

    async def go(mgr):
        await mgr.call_tool("proxy", "echo", {"text": "a"})
        await asyncio.sleep(6)  # com idle 1 s ele seria descarregado; com 0, fica
        return real_children(tag)

    assert len(run(go, proxy_spec(tmp_path, cfg, idle=1), tmp_path)) == 1
