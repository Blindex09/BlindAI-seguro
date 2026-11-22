"""O gateway remoto e so de leitura: a lista, a configuracao, as ferramentas escondidas e a protecao de Host."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from blind_mcp import MCPManager, ServerSpec
from blind_mcp import remote_gateway
from blind_mcp.remote_allowlist import REMOTE_READ_ONLY, allowed, guia

BACKEND = Path(__file__).resolve().parents[2]
FAKE = str(Path(__file__).with_name("fake_server.py"))
# ferramentas que apagam, enviam, gravam, comandam o computador, leem arquivo por caminho ou abrem o cofre
PERIGO = ("send", "enviar", "enviar_arquivo", "delete", "apagar", "remove", "forget", "save", "salvar", "write", "fill",
          "cofre", "secret", "segredo", "powershell", "click", "type_text", "press_keys", "file", "move", "kill",
          "process", "registry", "clipboard", "read_document", "responder", "baixar", "download", "pair", "connect",
          "snooze", "create", "gmail", "drive")


def test_allowlist_has_nothing_that_deletes_sends_writes_or_commands_the_pc():
    for nome in REMOTE_READ_ONLY:
        ferramenta = nome.split("__", 1)[1]
        assert not any(p in ferramenta for p in PERIGO), nome
    assert not allowed("windows__PowerShell")
    assert not allowed("blind-commander__read_file")
    assert not allowed("blind-channels__whatsapp_send")
    assert not allowed("blind-memory__cofre_listar")
    assert not allowed("blind-mail__gmail_enviar")


def test_remote_config_starts_only_the_servers_of_the_allowlist():
    servers = json.loads((BACKEND / "mcp.remote.json").read_text(encoding="utf-8"))["mcpServers"]
    donos = {nome.split("__", 1)[0] for nome in REMOTE_READ_ONLY}
    assert set(servers) <= donos
    for fora in ("windows", "agent-desktop", "blind-commander", "blind-channels", "blind-mail", "blind-drive", "blind-a11y"):
        assert fora not in servers


def test_remote_gateway_reads_the_remote_config_never_the_pc_config(monkeypatch):
    monkeypatch.delenv("BLIND_REMOTE_CONFIG", raising=False)
    assert remote_gateway.remote_config_path().name == "mcp.remote.json"


def test_guia_names_only_allowed_tools_and_says_it_is_read_only():
    texto = guia()
    assert "so leitura" in texto
    for nome in REMOTE_READ_ONLY:
        assert nome in texto
    assert "PowerShell" not in texto and "cofre_" not in texto


def test_dns_rebinding_protection_is_on_and_host_list_is_explicit(monkeypatch):
    monkeypatch.setenv("BLIND_REMOTE_HOSTS", "blind.exemplo.net")
    assert f"127.0.0.1:{remote_gateway.PORT}" in remote_gateway.remote_hosts()
    assert "blind.exemplo.net" in remote_gateway.remote_hosts()
    assert "https://blind.exemplo.net" in remote_gateway.remote_origins()


def test_call_raw_respects_hidden_tools_when_the_caller_is_the_model(tmp_path):
    spec = ServerSpec(name="fake", command=sys.executable, args=[FAKE], model_hidden_tools=["secret"], startup_timeout=30, call_timeout=10)

    async def go():
        mgr = MCPManager([spec], log_dir=tmp_path)
        await mgr.start(wait=True, timeout=60)
        try:
            with pytest.raises(ValueError):
                await mgr.call_raw("fake__secret", {}, from_model=True)
            local = await mgr.call_raw("fake__secret", {})  # o Blind local ainda chama a escondida
            return local
        finally:
            await mgr.stop()

    assert asyncio.run(go()) is not None
