"""Canais do Blind (core/channels/blind_bridge.py): so o dono e atendido, vinculo por codigo de uso unico, fila do Claude,
reserva local e midia."""

import asyncio
import time
import zipfile

import pytest

from core.channels import blind_bridge as bb
from core.channels import midia_canais as mc


@pytest.fixture(autouse=True)
def _dados(tmp_path, monkeypatch):
    monkeypatch.setattr(bb, "DATA_DIR", tmp_path)
    monkeypatch.setattr(bb, "CONFIG", tmp_path / "canais_blind.json")
    monkeypatch.setattr(bb, "CODIGO", tmp_path / "canais_codigo.json")
    monkeypatch.setattr(bb, "FILA", tmp_path / "google_fila.json")
    monkeypatch.setattr(bb, "VIVO", tmp_path / "canal_claude_vivo.json")
    monkeypatch.setattr(bb, "ESPERA_PEGAR_S", 0.1)
    enviados = []

    async def falso(canal, destino, texto, audio=False):
        enviados.append((canal, destino, texto, audio))

    monkeypatch.setattr(bb, "enviar", falso)
    return enviados


def _msg(chat_id, texto, idade=0.0):
    return {"message_id": 1, "chat_id": chat_id, "text": texto, "media_type": None, "file_id": None,
            "created_at": time.time() - idade}


def _ponte(resposta=None):
    async def chat(chave, texto):
        return resposta or ("ok:" + texto.split("]\n")[-1])

    return bb.Ponte(chat)


def _dono(chat_id=42):
    cfg = bb.config()
    cfg["telegram_donos"] = [chat_id]
    bb.salvar_config(cfg)


def _vivo():
    bb._gravar(bb.VIVO, {"ts": time.time()})


# ------------------------------------------------------------------------------------------ vinculo e dono
def test_codigo_vale_uma_vez_e_vincula(_dados):
    cod = bb.gerar_codigo_vinculo()["codigo"]
    p = _ponte()
    asyncio.run(p._telegram_uma(_msg(42, f"/vincular {cod}"), bb.config()))
    assert bb.config()["telegram_donos"] == [42]
    assert "Vinculado" in _dados[0][2]
    asyncio.run(p._telegram_uma(_msg(99, f"/vincular {cod}"), bb.config()))  # codigo ja usado
    assert bb.config()["telegram_donos"] == [42]


def test_codigo_errado_ou_vencido_nao_vincula(_dados, monkeypatch):
    bb.gerar_codigo_vinculo()
    asyncio.run(_ponte()._telegram_uma(_msg(7, "/vincular 000000x"), bb.config()))
    assert bb.config()["telegram_donos"] == []
    cod = bb.gerar_codigo_vinculo()["codigo"]
    agora = time.time()
    monkeypatch.setattr(bb.time, "time", lambda: agora + bb.CODIGO_TTL + 5)
    assert not bb._consumir_codigo(f"/vincular {cod}")


def test_so_o_dono_e_atendido(_dados):
    _dono()
    p = _ponte()
    asyncio.run(p._telegram_uma(_msg(99, "apague tudo"), bb.config()))  # estranho: silencio
    assert _dados == []
    asyncio.run(p._telegram_uma(_msg(42, "que horas sao"), bb.config()))
    assert _dados[0][:2] == ("telegram", "42") and "que horas sao" in _dados[0][2]


def test_mensagem_velha_nao_e_respondida(_dados):
    _dono()
    asyncio.run(_ponte()._telegram_uma(_msg(42, "oi", idade=bb.MAX_ANTIGA_S + 60), bb.config()))
    assert _dados == []


def test_erro_do_modelo_vira_aviso_curto(_dados):
    async def quebra(chave, texto):
        raise RuntimeError("x")

    async def entender():
        return "oi", False

    asyncio.run(bb.Ponte(quebra)._atender("telegram", "42", entender))
    assert "Nao consegui" in _dados[0][2]


# ------------------------------------------------------------------------------------------ cerebro Claude
def test_com_claude_vivo_o_pedido_vai_para_a_fila_e_nao_para_o_modelo_local(_dados):
    _vivo()

    async def entender():
        return "me lembra de ligar", True

    async def roda():
        p = _ponte("RESPOSTA LOCAL")
        await p._atender("telegram", "42", entender)
        item = bb.proxima()
        assert item["pedido"] == "me lembra de ligar" and item["audio"] is True and item["tipo"] == "canal"
        assert (await bb.responder(item["id"], "Feito"))["ok"]
        await asyncio.sleep(2.2)  # a reserva ve que ja foi respondido e nao faz nada
        await asyncio.gather(*list(p._vigias))

    asyncio.run(roda())
    assert _dados == [("telegram", "42", "Feito", True)]  # voz espelhada, uma resposta so


def test_sem_claude_vivo_usa_modelo_local(_dados):
    async def entender():
        return "oi", False

    asyncio.run(_ponte("RESPOSTA LOCAL")._atender("telegram", "42", entender))
    assert _dados == [("telegram", "42", "RESPOSTA LOCAL", False)]


def test_reserva_local_responde_quando_o_claude_nao_pega(_dados):
    _vivo()

    async def entender():
        return "oi", False

    async def roda():
        p = _ponte("RESERVA")
        await p._atender("telegram", "42", entender)
        await asyncio.gather(*list(p._vigias))

    asyncio.run(roda())
    assert _dados == [("telegram", "42", "RESERVA", False)]
    assert bb.proxima() is None  # o pedido foi marcado como local: a sessao nao pega depois


def test_cerebro_local_ignora_a_sessao(_dados):
    _vivo()
    cfg = bb.config()
    cfg["cerebro"] = "local"
    bb.salvar_config(cfg)

    async def entender():
        return "oi", False

    asyncio.run(_ponte("LOCAL")._atender("telegram", "42", entender))
    assert _dados[0][2] == "LOCAL" and bb.proxima() is None


def test_responder_duas_vezes_so_vale_a_primeira(_dados):
    item = bb.canal_pedir("x", "telegram", "42")
    bb.proxima()
    assert asyncio.run(bb.responder(item["id"], "a"))["ok"]
    assert not asyncio.run(bb.responder(item["id"], "b"))["ok"]
    assert len(_dados) == 1


def test_batimento_vencido_conta_como_sessao_fora():
    bb._gravar(bb.VIVO, {"ts": time.time() - bb.VIVO_TTL - 1})
    assert not bb.claude_vivo()
    _vivo()
    assert bb.claude_vivo()


# ------------------------------------------------------------------------------------------ fila do Google
def test_fila_do_google_ida_e_volta(_dados):
    item = bb.google_pedir("o que tenho amanha?", "telegram", "42")
    assert bb.proxima(("canal",)) is None  # a sessao de canal nao pega o pedido de outro tipo
    prox = bb.google_proxima()
    assert prox["id"] == item["id"] and bb.google_proxima() is None
    res = asyncio.run(bb.google_responder(item["id"], "Reuniao as 11h"))
    assert res["ok"] and _dados[0][:3] == ("telegram", "42", "Reuniao as 11h")


def test_mensagens_longas_sao_partidas():
    assert len(bb._partir("a" * 9000)) == 3


def test_arquivo_so_vai_para_o_destino_do_pedido(_dados, tmp_path, monkeypatch):
    enviados = []

    async def falso(canal, destino, caminho, legenda=""):
        enviados.append((canal, destino, caminho))

    monkeypatch.setattr(bb, "enviar_arquivo", falso)
    item = bb.canal_pedir("manda o relatorio", "whatsapp", "5511@s.whatsapp.net")
    bb.proxima()
    arq = tmp_path / "r.pdf"
    arq.write_bytes(b"x")
    assert asyncio.run(bb.enviar_arquivo_do_pedido(item["id"], str(arq)))["ok"]
    assert enviados == [("whatsapp", "5511@s.whatsapp.net", str(arq))]
    assert not asyncio.run(bb.enviar_arquivo_do_pedido(item["id"], str(tmp_path / "nao-existe.pdf")))["ok"]


# ------------------------------------------------------------------------------------------ midia
def test_documento_de_texto_e_docx_viram_trecho(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "MIDIA_DIR", tmp_path)
    t = tmp_path / "nota.txt"
    t.write_text("compra leite", encoding="utf-8")
    assert "compra leite" in mc._trecho_documento(t)
    d = tmp_path / "a.docx"
    with zipfile.ZipFile(d, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:p><w:t>Ola mundo</w:t></w:p></w:document>")
    assert "Ola mundo" in mc._trecho_documento(d)


def test_entender_documento_traz_caminho_e_conteudo(tmp_path):
    t = tmp_path / "recibo.txt"
    t.write_text("Total 50 reais", encoding="utf-8")
    texto = asyncio.run(mc.entender_arquivo(t, "documento"))
    assert str(t) in texto and "Total 50 reais" in texto


def test_nome_de_arquivo_nao_escapa_da_pasta(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "MIDIA_DIR", tmp_path)
    p = mc.novo_caminho(r"..\..\Windows\evil.exe")
    assert p.parent == tmp_path and ".." not in p.name


def test_limpeza_para_voz_tira_simbolos():
    assert mc._limpar_para_voz("**Oi** `x`\n## titulo") == "Oi x titulo"


def test_estado_inclui_voz_espelho_e_config_http(_dados):
    import server as srv

    est = bb.estado()
    assert est["voz_espelho"] is True

    out = asyncio.run(
        srv.canais_configurar_http(srv.CanaisConfigRequest(ativo=False, cerebro="local", voz_espelho=False))
    )
    assert out["ativo"] is False
    assert out["cerebro"] == "local"
    assert out["voz_espelho"] is False


def test_user_preferences_block_limpa_markdown():
    import server as srv

    bloco = srv._build_user_preferences_block("curto", "## Regra\nMe chame de **João** `amigo`")
    assert "curta, objetiva e direta" in bloco
    assert "Me chame de João amigo" in bloco
    assert "*" not in bloco and "#" not in bloco and "`" not in bloco
    assert srv._build_user_preferences_block("normal", "") == ""
