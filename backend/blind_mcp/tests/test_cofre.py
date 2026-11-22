"""Cofre do Blind: guarda criptografado, fala sem expor, e dado sensivel nao vai para memoria, diario nem historico."""

import asyncio
import json

import pytest

from blind_mcp import cofre
from blind_mcp.servers import _audit, channels, memory

CARTAO = "4539 1488 0343 6467"  # numero de teste que passa no Luhn
CPF = "529.982.247-25"  # CPF valido de exemplo


@pytest.fixture(autouse=True)
def cofre_isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(cofre, "COFRE_FILE", tmp_path / "cofre.json")
    monkeypatch.setattr(cofre, "DATA_DIR", tmp_path)
    cofre.PENDENTES.clear()


def test_detecta_e_mascara_sem_revelar_o_valor():
    assert cofre.detectar(f"meu cartão é {CARTAO}") == ["cartão"]
    assert "CPF" in cofre.detectar(f"CPF {CPF}")
    assert "senha" in cofre.detectar("a senha é Tr0ub4dor&3")
    assert "chave" in cofre.detectar("use sk-abcdefghijklmnopqrstuvwxyz123456")
    assert cofre.detectar("o telefone é 11 99999-0001 e a conta tem 300 reais") == []  # nao confunde numero comum
    m = cofre.mascarar(f"cartão {CARTAO}, CPF {CPF}, senha: segredo123, sk-abcdefghijklmnopqrstuvwxyz123456")
    assert "6467" in m and "4539" not in m and "[cartão terminado em 6467]" in m
    assert "segredo123" not in m and "529" not in m and "sk-abc" not in m


def test_guarda_criptografado_e_nunca_em_texto_puro(tmp_path):
    cofre.guardar("cartão do banco", CARTAO)
    bruto = (tmp_path / "cofre.json").read_text(encoding="utf-8")
    assert "4539" not in bruto and "cartão do banco" in bruto
    assert cofre.ler("cartão do banco") == CARTAO
    assert cofre.ler("banco") == CARTAO  # acha por parte do nome, se so houver um
    assert cofre.listar()[0]["tipo"] == "cartão" and "dados" not in cofre.listar()[0]
    with pytest.raises(ValueError):
        cofre.guardar(CARTAO, "x")  # o nome nao pode ser o proprio segredo
    assert cofre.apagar("cartão do banco") and cofre.listar() == []


def test_para_voz_agrupa_numeros_e_soletra_senhas():
    assert cofre.para_voz("4539148803436467") == "4 5 3 9, 1 4 8 8, 0 3 4 3, 6 4 6 7."
    voz = cofre.para_voz("aB3@")
    assert "B maiúsculo" in voz and "arroba" in voz and "3" in voz


def test_falar_e_copiar_em_duas_etapas_e_nunca_devolvem_o_valor(monkeypatch):
    ditos, copiados = [], []

    async def fake_falar(texto, devagar=True):
        ditos.append(texto)

    monkeypatch.setattr(cofre, "falar", fake_falar)
    monkeypatch.setattr(cofre, "copiar_e_limpar_depois", lambda v, s=20: copiados.append((v, s)))
    cofre.guardar("senha do wifi", "Casa2026!")

    r1 = asyncio.run(memory.cofre_falar("senha do wifi"))
    assert r1["falado"] is False and "Casa2026" not in json.dumps(r1) and ditos == []
    with pytest.raises(ValueError):
        asyncio.run(memory.cofre_falar("senha do wifi", codigo_confirmacao="0000"))
    r2 = asyncio.run(memory.cofre_falar("senha do wifi", codigo_confirmacao=r1["codigo_confirmacao"]))
    assert r2["falado"] is True and "Casa2026" not in json.dumps(r2)
    assert ditos and "C maiúsculo" in ditos[0]
    with pytest.raises(ValueError):  # o codigo vale uma vez
        asyncio.run(memory.cofre_falar("senha do wifi", codigo_confirmacao=r1["codigo_confirmacao"]))

    c1 = asyncio.run(memory.cofre_copiar("senha do wifi", 30))
    c2 = asyncio.run(memory.cofre_copiar("senha do wifi", 30, c1["codigo_confirmacao"]))
    assert c2["copiado"] is True and copiados == [("Casa2026!", 30)] and "Casa2026" not in json.dumps(c2)
    # codigo de falar nao serve para copiar
    f = asyncio.run(memory.cofre_falar("senha do wifi"))
    with pytest.raises(ValueError):
        asyncio.run(memory.cofre_copiar("senha do wifi", 30, f["codigo_confirmacao"]))


def test_guardar_da_area_de_transferencia_limpa_a_area(monkeypatch):
    area = {"t": "Segredo-do-Banco-99"}
    monkeypatch.setattr(cofre, "ler_e_limpar_area", lambda: area.__setitem__("t", "") or "Segredo-do-Banco-99")
    r = asyncio.run(memory.cofre_guardar("senha do banco", da_area_de_transferencia=True))
    assert r["ok"] and "Segredo" not in json.dumps(r) and r["aviso"] is None
    assert area["t"] == "" and cofre.ler("senha do banco") == "Segredo-do-Banco-99"


def test_memoria_comum_recusa_dado_sensivel(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DB", tmp_path / "m.db")
    memory._init_db()
    with pytest.raises(ValueError, match="cofre"):
        memory._memory_save_sync("cartao", f"meu cartão {CARTAO}")
    with pytest.raises(ValueError):
        memory._memory_save_sync("wifi", "a senha é abc12345")
    memory._memory_save_sync("endereco", "Rua das Flores, 10")  # dado comum continua indo


def test_diario_de_acoes_mascara_argumentos_sensiveis():
    saida = _audit._clean_args({"query": f"cartão {CARTAO}", "segredo": "abc", "nome": "senha do wifi"})
    assert "4539" not in json.dumps(saida) and saida["segredo"] == "<3 itens/caracteres>" and saida["nome"] == "senha do wifi"


def test_rascunho_de_mensagem_avisa_dado_sensivel_e_busca_recusa():
    assert channels._aviso_sensivel("oi, tudo bem?") is None
    assert "cartão" in channels._aviso_sensivel(f"meu cartão é {CARTAO}")
    from blind_mcp.servers import docs

    r = asyncio.run(docs.web_search(f"saldo do cartão {CARTAO}"))
    assert r["ok"] is False and "sensível" in r["error"]


def test_historico_de_conversa_guardado_sai_mascarado(tmp_path):
    from core.channels.session_manager import SessionManager

    sm = SessionManager(db_path=str(tmp_path / "s.db")) if "db_path" in SessionManager.__init__.__code__.co_varnames else None
    if sm is None:
        pytest.skip("assinatura do SessionManager diferente")
    sm.add_message("s1", "Você", f"minha senha é Abc12345 e o cartão {CARTAO}", is_user=True)
    msgs = json.dumps(sm.get_messages("s1"), ensure_ascii=False, default=str)
    assert "Abc12345" not in msgs and "4539" not in msgs and "6467" in msgs
