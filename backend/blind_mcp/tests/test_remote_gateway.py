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
          "process", "registry", "clipboard", "responder", "baixar", "download", "pair", "connect",
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


def test_files_are_read_from_content_never_from_a_path_on_the_pc():
    from blind_mcp.remote_allowlist import clean_schema, forbidden_args

    assert forbidden_args({"file_path": "C:/Users/x/segredo.pdf"}) == ["file_path"]
    assert forbidden_args({"file_base64": "AAAA"}) == []
    limpo = clean_schema({"type": "object", "properties": {"file_path": {}, "file_base64": {}}, "required": ["file_path"]})
    assert "file_path" not in limpo["properties"] and "file_base64" in limpo["properties"] and limpo["required"] == []
    assert allowed("blind-docs__read_document") and allowed("blind-docs__describe_image")
    assert not allowed("blind-docs__ver_imagem") and not allowed("blind-docs__document_outline")  # so aceitam caminho


def test_describe_image_hands_the_image_to_claude_and_needs_no_ai_key():
    import base64
    import io

    from PIL import Image

    from blind_mcp import remote_image

    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 10, 10)).save(buf, format="PNG")
    out = remote_image.entregar(base64.b64encode(buf.getvalue()).decode(), "que cor e?")
    assert [b.type for b in out] == ["text", "image"]
    assert "que cor e?" in out[0].text and out[1].mimeType == "image/jpeg"
    assert set(remote_image.SCHEMA["properties"]) == {"image_base64", "url", "prompt"}  # sem file_path, api_key, provider, model
    with pytest.raises(ValueError):
        remote_image.entregar("isto nao e uma imagem")


def test_scanned_pdf_never_uses_the_owners_ai_key():
    from blind_mcp.remote_allowlist import clean_schema, with_forced

    assert with_forced("blind-docs__read_document", {"file_base64": "AA", "ocr_scanned": True})["ocr_scanned"] is False
    sch = clean_schema({"type": "object", "properties": {"file_base64": {}, "ocr_scanned": {}}}, "blind-docs__read_document")
    assert "ocr_scanned" not in sch["properties"]


def test_no_system_tool_is_offered_remotely():
    assert not any(n.startswith("blind-system__") for n in REMOTE_READ_ONLY)
    for nome in ("saude_teclado", "vigia_status", "vigia_configurar", "acoes_recentes", "trabalho_nao_salvo"):
        assert not allowed(f"blind-system__{nome}")


def test_public_links_never_reach_the_pc_or_the_local_network():
    from blind_mcp import remote_fetch

    for ruim in ("http://localhost/x.pdf", "http://127.0.0.1/x.pdf", "http://10.0.0.5/x.pdf", "http://192.168.1.2/x",
                 "http://169.254.169.254/latest", "ftp://exemplo.com/x.pdf", "http://user:senha@exemplo.com/x.pdf",
                 "file:///C:/Windows/win.ini", "http://impressora.local/x", ""):
        with pytest.raises(ValueError):
            remote_fetch.validar(ruim)


def test_a_redirect_to_a_private_address_is_refused():
    import httpx

    from blind_mcp import remote_fetch

    def handler(request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1:8770/segredo"})

    async def go():
        cliente = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
        try:
            with pytest.raises(ValueError):
                await remote_fetch.baixar("http://exemplo.com/x.pdf", 1000, client=cliente)
        finally:
            await cliente.aclose()

    # exemplo.com precisa resolver para o primeiro salto passar; se a rede estiver fora, o primeiro salto ja e recusado
    asyncio.run(go())


def test_document_tools_take_a_public_url_and_never_a_path():
    from blind_mcp.remote_allowlist import clean_schema

    sch = clean_schema({"type": "object", "properties": {"file_path": {}, "file_base64": {}}}, "blind-docs__read_document")
    assert "url" in sch["properties"] and "file_path" not in sch["properties"]


def test_guia_carries_the_blind_rules_for_a_blind_listener_without_local_only_tools():
    texto = guia()
    for regra in ("Jeito de falar", "Descrevendo imagens", "Lendo documentos", "Nunca identifique alguem pelo rosto".replace("alguem", "alguém")):
        assert regra in texto
    for fora in ("ver_imagem", "document_outline", "falar_em_segredo", "documento_acessibilidade"):
        assert fora not in texto


def test_local_document_tools_take_a_public_url_and_refuse_internal_ones():
    from blind_mcp.servers import docs

    async def go():
        for ruim in ("http://127.0.0.1/x.pdf", "http://169.254.169.254/x", "file:///C:/Windows/win.ini"):
            with pytest.raises(ValueError):
                await docs.read_document(url=ruim)
            with pytest.raises(ValueError):
                await docs.ver_imagem(url=ruim)

    asyncio.run(go())


def test_every_remote_server_gets_the_data_folder_explicitly():
    """Um servidor filho nao herda o ambiente do gateway: sem BLIND_DATA_DIR no env dele, a memoria real nao e lida."""
    servers = json.loads((BACKEND / "mcp.remote.json").read_text(encoding="utf-8"))["mcpServers"]
    for nome, spec in servers.items():
        assert spec.get("env", {}).get("BLIND_DATA_DIR") == "${DATA_DIR}", nome


def test_the_data_folder_reaches_the_child_server_through_the_remote_config(monkeypatch, tmp_path):
    from blind_mcp.config import load_specs

    monkeypatch.setenv("BLIND_DATA_DIR", str(tmp_path))
    specs = {s.name: s for s in load_specs(BACKEND / "mcp.remote.json")}
    assert specs["blind-memory"].env["BLIND_DATA_DIR"] == str(tmp_path)
