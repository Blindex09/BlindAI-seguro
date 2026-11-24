"""Download com IP fixo (sem DNS rebinding) e transcricao de audio no remoto e no local."""

import asyncio
import base64
import socket

import httpcore
import httpx
import pytest

from blind_mcp import remote_fetch
from blind_mcp.remote_allowlist import AUDIO_MAX_BYTES, allowed, forbidden_args, guia

PUBLICO = "93.184.216.34"


def test_the_connection_uses_the_ip_it_just_checked_never_a_second_dns_answer(monkeypatch):
    """O nome e resolvido uma vez DENTRO da conexao e o socket abre nesse IP, nao no nome."""
    chamadas = []
    conectou = []

    def resolvedor(host, port):
        chamadas.append(host)
        return [PUBLICO]

    async def falso(self, host, port, timeout=None, local_address=None, socket_options=None):
        conectou.append(host)
        return "stream"

    monkeypatch.setattr(remote_fetch, "_resolver", resolvedor)
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", falso)
    assert asyncio.run(remote_fetch._PinnedBackend().connect_tcp("site.exemplo.net", 443)) == "stream"
    assert conectou == [PUBLICO] and chamadas == ["site.exemplo.net"]


def test_a_name_that_turns_private_between_check_and_connect_never_reaches_the_pc(monkeypatch):
    """Rebinding: 1a resposta publica (a conferencia do link), 2a resposta 127.0.0.1 (a conexao). Ninguem conecta."""
    respostas = iter([[PUBLICO], ["127.0.0.1"]])
    monkeypatch.setattr(remote_fetch, "_resolver", lambda host, port: next(respostas))

    async def go():
        vistas = []

        async def atende(reader, writer):
            vistas.append(1)
            writer.close()

        servidor = await asyncio.start_server(atende, "127.0.0.1", 0)
        porta = servidor.sockets[0].getsockname()[1]
        try:
            with pytest.raises(ValueError, match="privado ou interno"):
                await remote_fetch.baixar(f"http://rebind.exemplo.net:{porta}/segredo", 1000)
            await asyncio.sleep(0.2)
        finally:
            servidor.close()
        return vistas

    assert asyncio.run(go()) == []  # o servidor local nunca recebeu conexao


def test_one_private_address_in_the_answer_refuses_the_whole_link(monkeypatch):
    monkeypatch.setattr(remote_fetch, "_resolver", lambda host, port: [PUBLICO, "10.0.0.7"])
    with pytest.raises(ValueError, match="privado ou interno"):
        asyncio.run(remote_fetch._PinnedBackend().connect_tcp("misto.exemplo.net", 80))


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "192.168.0.9", "169.254.169.254", "100.64.0.1", "0.0.0.0",
                                "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "224.0.0.1"])
def test_internal_and_special_addresses_are_blocked(ip):
    with pytest.raises(ValueError):
        remote_fetch._checar_ip(ip)
    with pytest.raises(ValueError):
        remote_fetch.validar(f"http://[{ip}]/x" if ":" in ip else f"http://{ip}/x")


def test_a_public_address_passes():
    assert remote_fetch._checar_ip(PUBLICO) == PUBLICO


def test_the_gateway_client_pins_the_ip_ignores_env_proxies_and_never_follows_redirects(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.interno:3128")
    cliente = remote_fetch.novo_cliente()
    assert isinstance(cliente._transport._pool._network_backend, remote_fetch._PinnedBackend)
    assert cliente.follow_redirects is False
    assert cliente._trust_env is False


def test_each_redirect_hop_is_checked_before_it_is_requested(monkeypatch):
    pedidos = []

    def handler(request):
        pedidos.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://10.0.0.5/admin"})

    monkeypatch.setattr(remote_fetch, "_resolver", lambda host, port: [PUBLICO])
    cliente = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    with pytest.raises(ValueError):
        asyncio.run(remote_fetch.buscar("http://publico.exemplo.net/a", 1000, client=cliente))
    assert pedidos == ["http://publico.exemplo.net/a"]  # o salto para 10.0.0.5 nem foi pedido


def test_web_read_goes_through_the_pinned_fetch_and_refuses_internal_links(monkeypatch):
    from blind_mcp.servers import docs

    async def falso(url, max_bytes, client=None, headers=None):
        return b"<html><head><title>Ola</title></head><body><main><h1>Titulo</h1><p>Texto da pagina.</p></main></body></html>", url, "text/html; charset=utf-8"

    monkeypatch.setattr(remote_fetch, "buscar", falso)
    out = asyncio.run(docs.web_read("https://exemplo.net/p"))
    assert out["ok"] and "Texto da pagina" in out["content"]
    monkeypatch.undo()
    with pytest.raises(ValueError):
        asyncio.run(docs.web_read("http://127.0.0.1:8765/api/status"))


# ---------------------------------------------------------------- audio

def test_blindaudio_is_offered_remotely_by_content_or_public_link_never_by_path():
    from blind_mcp.remote_allowlist import BLINDAUDIO, BLINDAUDIO_SCHEMA

    assert BLINDAUDIO == "blindaudio"
    assert set(BLINDAUDIO_SCHEMA["properties"]) == {"audio_base64", "url", "language"}  # sem file_path
    assert forbidden_args({"file_path": "C:/audio.wav"}) == ["file_path"]
    assert "blindaudio" in guia() and AUDIO_MAX_BYTES == 3_000_000
    assert not allowed("blind-stt__transcribe")  # o ditado ao vivo continua so no app


def test_blindaudio_takes_base64_a_link_or_a_local_path_and_auto_language(monkeypatch):
    from blind_mcp import audio_tool

    vistos = []

    async def falso(payload):
        vistos.append(payload)
        return {"text": "ola mundo", "language": payload["language"] or "pt", "audio_seconds": 1.0}

    monkeypatch.setattr(audio_tool, "_rodar", falso)
    WAV = b"RIFF\x24\x00\x00\x00WAVEfmt "
    b64 = base64.b64encode(WAV).decode()
    assert asyncio.run(audio_tool.transcrever(audio_base64=b64))["text"] == "ola mundo"
    assert vistos[-1] == {"audio_base64": b64, "file_path": None, "language": "pt"}

    asyncio.run(audio_tool.transcrever(audio_base64=b64, language="auto"))
    assert vistos[-1]["language"] is None

    async def baixa(url, max_bytes, client=None):
        return b"ID3\x04\x00\x00BYTES"

    monkeypatch.setattr(remote_fetch, "baixar", baixa)
    asyncio.run(audio_tool.transcrever(url="https://exemplo.net/voz.mp3", language="en"))
    assert vistos[-1] == {"audio_base64": base64.b64encode(b"ID3\x04\x00\x00BYTES").decode(), "file_path": None, "language": "en"}

    asyncio.run(audio_tool.transcrever(file_path="C:/voz.wav"))  # Blind local
    assert vistos[-1]["file_path"] == "C:/voz.wav" and vistos[-1]["audio_base64"] is None

    with pytest.raises(ValueError):
        asyncio.run(audio_tool.transcrever())


def test_the_worker_process_answers_json_and_reports_errors(monkeypatch, capsys):
    import io
    import json
    import sys

    from blind_mcp import audio_worker
    from blind_mcp.servers import stt

    monkeypatch.setattr(stt, "_decode", lambda b64, path: "audio")
    monkeypatch.setattr(stt, "_transcribe", lambda src, lang, prompt: {"text": "oi", "language": lang})
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(json.dumps({"audio_base64": "AA", "language": "pt"}).encode())})())
    assert audio_worker.main() == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {"text": "oi", "language": "pt"}

    monkeypatch.setattr(stt, "_decode", lambda b64, path: (_ for _ in ()).throw(ValueError("Audio grande demais")))
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(b"{}")})())
    assert audio_worker.main() == 1
    assert "Audio grande demais" in json.loads(capsys.readouterr().out.strip().splitlines()[-1])["error"]


def test_the_blind_server_has_the_blindaudio_tool_of_its_own():
    from blind_mcp.servers import blind

    assert "blindaudio" in {t.name for t in asyncio.run(blind.mcp.list_tools())}


AUDIOS = {
    "wav": b"RIFF\x24\x00\x00\x00WAVEfmt ", "mp3": b"ID3\x04\x00\x00\x00\x00\x00\x00", "mp3 sem tag": b"\xff\xfb\x90\x00",
    "m4a": b"\x00\x00\x00\x20ftypM4A ", "ogg": b"OggS\x00\x02\x00\x00", "flac": b"fLaC\x00\x00\x00\x22", "webm": b"\x1a\x45\xdf\xa3\x01\x00\x00\x00",
}
NAO_AUDIO = {"html": b"<!doctype html><html>", "exe": b"MZ\x90\x00\x03\x00\x00\x00", "pdf": b"%PDF-1.7\n", "zip": b"PK\x03\x04\x14\x00", "texto": b"ola mundo, isto nao e audio", "vazio": b""}


def test_the_audio_type_is_read_from_the_first_bytes_of_the_file():
    from blind_mcp import audio_tool

    for nome, inicio in AUDIOS.items():
        assert audio_tool.tipo_do_audio(inicio) is not None, nome
    assert audio_tool.tipo_do_audio(AUDIOS["wav"]) == "wav" and audio_tool.tipo_do_audio(AUDIOS["flac"]) == "flac"
    for nome, inicio in NAO_AUDIO.items():
        assert audio_tool.tipo_do_audio(inicio) is None, nome


def test_a_link_that_is_not_audio_is_refused_before_anything_is_decoded(monkeypatch):
    from blind_mcp import audio_tool

    chamadas = []

    async def nao_pode(payload):
        chamadas.append(payload)
        return {}

    monkeypatch.setattr(audio_tool, "_rodar", nao_pode)
    for nome, corpo in NAO_AUDIO.items():
        async def baixa(url, max_bytes, client=None, _c=corpo):
            return _c  # o site pode dizer audio/mpeg no cabecalho: so o conteudo vale

        monkeypatch.setattr(remote_fetch, "baixar", baixa)
        with pytest.raises(ValueError, match="nao parece um audio"):
            asyncio.run(audio_tool.transcrever(url="https://exemplo.net/voz.mp3"))
        with pytest.raises(ValueError):
            asyncio.run(audio_tool.transcrever(audio_base64=base64.b64encode(corpo or b"x").decode()))
    assert chamadas == []  # o Whisper nunca foi chamado


def test_transcriptions_run_one_at_a_time(monkeypatch):
    from blind_mcp import audio_tool

    ativas, maximo, feitas = [0], [0], []

    async def lenta(payload):
        ativas[0] += 1
        maximo[0] = max(maximo[0], ativas[0])
        await asyncio.sleep(0.05)
        ativas[0] -= 1
        feitas.append(payload["language"])
        return {"text": "ok"}

    monkeypatch.setattr(audio_tool, "_rodar", lenta)
    b64 = base64.b64encode(AUDIOS["wav"]).decode()

    async def varias():
        return await asyncio.gather(*(audio_tool.transcrever(audio_base64=b64, language=l) for l in ("pt", "en", "es", "fr")))

    assert len(asyncio.run(varias())) == 4
    assert maximo[0] == 1 and sorted(feitas) == ["en", "es", "fr", "pt"]  # as quatro rodaram, uma por vez


def test_web_read_of_a_pdf_link_passes_the_ocr_choice_to_the_reader(monkeypatch):
    from blind_mcp.servers import docs

    async def pdf(url, max_bytes, headers=None, client=None):
        return b"%PDF-1.4", url, "application/pdf"

    vistos = []

    async def leitor(**kw):
        vistos.append(kw["ocr_scanned"])
        return {"filename": "a.pdf", "text": "texto"}

    monkeypatch.setattr(remote_fetch, "buscar", pdf)
    monkeypatch.setattr(docs, "read_document", leitor)
    asyncio.run(docs.web_read("https://exemplo.net/a.pdf"))  # Blind local: o padrao continua usando a visao
    asyncio.run(docs.web_read("https://exemplo.net/a.pdf", ocr_scanned=False))  # gateway remoto: fixo em False
    assert vistos == [True, False]


def test_a_scanned_pdf_link_tells_why_it_is_empty_and_hands_over_the_pages(monkeypatch):
    from blind_mcp.servers import docs

    async def pdf(url, max_bytes, headers=None, client=None):
        return b"%PDF-1.4", url, "application/pdf"

    async def escaneado(**kw):
        return {"filename": "a.pdf", "text": "", "scanned": True, "total_pages": 1, "note": "PDF escaneado",
                "page_images": [{"page": 1, "image_base64": "AAAA"}] if kw["devolver_imagens"] else None}

    monkeypatch.setattr(remote_fetch, "buscar", pdf)
    monkeypatch.setattr(docs, "read_document", escaneado)
    r = asyncio.run(docs.web_read("https://exemplo.net/a.pdf", ocr_scanned=False, devolver_imagens=True))
    assert r["content"] == "" and r["note"] == "PDF escaneado" and r["scanned"] is True and r["page_images"][0]["page"] == 1
    vazio = asyncio.run(docs.web_read("https://exemplo.net/a.pdf", ocr_scanned=False))  # sem imagens pedidas: ainda diz o porque
    assert vazio["note"] == "PDF escaneado" and "page_images" in vazio


def test_read_document_returns_the_scanned_pages_as_images_only_when_asked():
    from blind_mcp.servers.docs import _paginas_como_imagem

    renders = [(1, "AAAA"), (2, "BBBB")]
    assert _paginas_como_imagem(renders, False) == {} and _paginas_como_imagem([], True) == {}
    r = _paginas_como_imagem(renders, True)
    assert [p["page"] for p in r["page_images"]] == [1, 2] and "2 pagina" in r["note"]
