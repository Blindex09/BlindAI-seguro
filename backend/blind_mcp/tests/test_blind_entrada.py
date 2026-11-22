"""Servidor `blind` (entrada do Claude): guia correto e fora do app Electron."""
import asyncio

from blind_mcp.config import load_specs
from blind_mcp.manager import MCPManager
from blind_mcp.servers import blind


def test_comecar_devolve_guia_e_pedido():
    r = asyncio.run(blind.comecar("ler um pdf"))
    assert r["ok"] and r["pedido"] == "ler um pdf"
    for ferramenta in ("read_document", "screen_context", "whatsapp_pair", "writer_save"):
        assert ferramenta in r["guia"]


def test_mcp_json_marca_blind_so_para_claude():
    specs = {s.name: s for s in load_specs()}
    assert specs["blind"].client_only == "claude"
    so_claude = {"blind", "blind-mail", "blind-drive"}
    assert all(specs[n].client_only == "claude" for n in so_claude)
    assert all(s.client_only is None for n, s in specs.items() if n not in so_claude)


def test_app_nao_inicia_servidor_so_do_claude():
    mgr = MCPManager(specs=load_specs())
    nomes = [s.name for s in mgr._specs]
    assert not ({"blind", "blind-mail", "blind-drive"} & set(nomes))  # Gmail e Drive nao entram no app Electron
    assert "windows" in [s.name for s in mgr._specs]


def test_habilidades_chegam_pelo_comecar():
    from blind_mcp import habilidades

    nomes = {h["nome"] for h in habilidades.indice()}
    assert {"jeito-de-falar", "descrevendo-imagens", "lendo-mensagens", "lendo-documentos", "navegando-na-web",
            "agindo-no-computador", "dizendo-o-que-aconteceu", "tarefas-em-varios-passos", "dados-sensiveis"} <= nomes
    r = asyncio.run(blind.comecar("descreva essa foto que a minha mãe mandou no WhatsApp"))
    assert "A pessoa ouve" in r["jeito_de_falar"]
    do_pedido = {h["nome"] for h in r["habilidades_do_pedido"]}
    assert {"descrevendo-imagens", "lendo-mensagens"} <= do_pedido and "jeito-de-falar" not in do_pedido
    assert "Tipo e assunto" in asyncio.run(blind.comecar("x", habilidade="descrevendo-imagens"))["habilidade_pedida"]["texto"]


def test_toda_habilidade_tem_cabecalho_e_cabe_na_conversa():
    from blind_mcp import habilidades

    for h in habilidades.carregar().values():
        assert h["quando"] and h["texto"], h["nome"]
        assert len(h["texto"].splitlines()) < 60, h["nome"]  # curtas: modelos menores precisam de instrucao enxuta


def test_bloco_para_o_app_vai_sem_marcacao_e_cabe_no_limite():
    from blind_mcp import habilidades

    bloco = habilidades.bloco_para("descreva essa foto do WhatsApp e depois faça uma planilha")
    assert "Responda ao que foi perguntado" in bloco
    assert "*" not in bloco and "#" not in bloco and "`" not in bloco
    assert len(bloco) <= 7500
    assert "descrevendo imagens" in bloco


def test_descritor_trata_recusa_e_nao_finge_sucesso(monkeypatch):
    import base64

    from core.vision import smart_vision_router as svr

    r = svr.smart_vision_router
    assert svr.parece_recusa("Desculpe, não posso identificar pessoas em imagens.")
    assert svr.parece_recusa("I'm sorry, but I can't help with that.")
    assert not svr.parece_recusa("Foto de duas pessoas sentadas à mesa. Uma delas sorri.")
    assert "não se recuse" in svr.PROMPT_PADRAO and "não identifique" in svr.PROMPT_PADRAO.lower()
    for k in ("OLLAMA_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")

    class _Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "Desculpe, não posso descrever imagens com pessoas."}}]}

    async def _post_recusa(self, url, **kwargs):
        return _Resp()

    monkeypatch.setattr(svr.httpx.AsyncClient, "post", _post_recusa)
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    out = asyncio.run(r.describe_multimodal(image_base64=b64))
    assert "recusaram" in out and "processada com sucesso" not in out
