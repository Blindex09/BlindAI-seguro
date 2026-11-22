"""Melhorias de acessibilidade: diario de acoes, guia x ferramentas reais, saude do teclado, nao salvo, "o que mudou",
telegram em duas etapas, lembretes e posicao de leitura."""

import asyncio
import re
import sqlite3
from pathlib import Path

import pytest

from blind_mcp.servers import _audit, blind, system


# ------------------------------ diario ------------------------------

def test_diario_grava_inicio_e_fim_sem_texto_privado(tmp_path, monkeypatch):
    monkeypatch.setattr(_audit, "AUDIT_DIR", tmp_path)
    monkeypatch.setattr(_audit, "AUDIT_FILE", tmp_path / "acoes.jsonl")
    from mcp.server.fastmcp import FastMCP

    m = FastMCP("t")

    @m.tool()
    async def escreve(text: str, ref: str = "x") -> str:
        return "ok"

    @m.tool()
    async def quebra() -> str:
        raise RuntimeError("boom")

    _audit.install_audit(m, "teste")
    asyncio.run(m._tool_manager.get_tool("escreve").run({"text": "segredo da pessoa", "ref": "@e1"}))
    with pytest.raises(Exception):
        asyncio.run(m._tool_manager.get_tool("quebra").run({}))
    raw = (tmp_path / "acoes.jsonl").read_text(encoding="utf-8")
    assert "segredo da pessoa" not in raw  # so o tamanho
    rows = _audit.read_recent(10)
    assert [r["tool"] for r in rows] == ["quebra", "escreve"]
    assert rows[0]["ok"] is False and rows[1]["ok"] is True and rows[1]["args"]["ref"] == "@e1"


def test_diario_marca_acao_sem_fim(tmp_path, monkeypatch):
    monkeypatch.setattr(_audit, "AUDIT_DIR", tmp_path)
    monkeypatch.setattr(_audit, "AUDIT_FILE", tmp_path / "acoes.jsonl")
    _audit.write_entry({"id": "1", "server": "s", "tool": "t", "args": {}, "evento": "inicio", "quando": "x"})
    rows = _audit.read_recent(5)
    assert rows[0]["sem_fim"] is True


# ------------------------------ guia x realidade ------------------------------

def _tools_reais() -> set:
    from blind_mcp.servers import agent_desktop, channels, docs, drive, mail, memory, schedule, speech, stt

    nomes = set()
    for mod in (agent_desktop, channels, docs, drive, mail, memory, schedule, speech, stt, system, blind):
        nomes |= {t.name for t in mod.mcp._tool_manager.list_tools()}
    return nomes


def test_guia_so_cita_ferramentas_que_existem():
    reais = _tools_reais()
    removidas_ou_externas = {
        "press_keys",  # citada como REMOVIDA
        "claude_desktop_config",  # arquivo, nao ferramenta
        "element_action",
    }
    citadas = set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", blind.GUIA))
    desconhecidas = {c for c in citadas if c not in reais and c not in removidas_ou_externas}
    # parametros/valores que aparecem no texto, nao ferramentas
    parametros = {"ref_id", "window_id", "read_document", "blind_commander", "incluir_concluidos", "nomes_exatos", "entender_midias", "max_midias", "app", "jeito_de_falar", "habilidades_do_pedido", "scan_office_document", "scan_pdf_document", "run_axe_scan", "check_contrast", "da_area_de_transferencia"}
    assert not (desconhecidas - parametros), desconhecidas - parametros


def test_estado_servidores_cobre_o_mcp_json():
    est = blind.estado_servidores()
    assert "blind-system" in est["servidores_esperados"]
    assert "Shortcut" in est["windows_ferramentas_removidas"] and "Click" not in est["windows_ferramentas_removidas"]
    r = asyncio.run(blind.comecar("x"))
    assert r["estado"]["servidores_esperados"] and "guia" in r


# ------------------------------ saude do teclado / nao salvo ------------------------------

def test_saude_teclado_responde_so_leitura():
    r = asyncio.run(system.saude_teclado())
    assert r["ok"] and "resumo" in r and isinstance(r["teclas_pressionadas"], list)
    assert "teclas_de_aderencia" in r and "se_travar" in r
    assert {"botoes_mouse_pressionados", "teclas_do_mouse", "cursor_preso_em_area", "botoes_do_mouse_trocados"} <= set(r)


def test_trabalho_nao_salvo_reconhece_titulos():
    for t in ("*Sem titulo - Bloco de Notas", "Relatorio - Modificado", "doc.txt *", "Arquivo (nao salvo)"):
        assert system._UNSAVED.search(t), t
    for t in ("Calculadora", "Configuracoes", "Relatorio.docx - Word"):
        assert not system._UNSAVED.search(t), t
    r = asyncio.run(system.trabalho_nao_salvo())
    assert r["ok"] and "limite" in r and isinstance(r["janelas"], list)


# ------------------------------ o que mudou ------------------------------

def test_diferenca_de_janelas():
    from blind_mcp.servers import agent_desktop as ad

    antes = {"1": ("Bloco de Notas", "notepad.exe")}
    depois = {"1": ("*Bloco de Notas", "notepad.exe"), "2": ("Salvar como", "notepad.exe")}
    d = ad._diferenca(antes, depois)
    assert d["verificado"] and d["janelas_novas"][0]["titulo"] == "Salvar como"
    assert d["titulos_mudaram"][0]["depois"] == "*Bloco de Notas"
    assert "Abriu" in d["resumo"]
    assert ad._diferenca(None, depois)["verificado"] is False
    assert "Nenhuma janela" in ad._diferenca(antes, dict(antes))["resumo"]


# ------------------------------ telegram em duas etapas ------------------------------

def test_telegram_envio_em_duas_etapas(tmp_path, monkeypatch):
    from blind_mcp.servers import channels

    monkeypatch.setattr(channels, "CONTACTS_FILE", tmp_path / "c.json")
    enviados = []

    class FakeTG:
        def get_default_token(self, bot_id=None):
            return "tok"

        async def send_message(self, token, chat_id, text):
            enviados.append((chat_id, text))
            return {"ok": True}

    monkeypatch.setattr(channels, "telegram_manager", FakeTG())
    asyncio.run(channels.contato_salvar("Mãe", "123"))
    assert asyncio.run(channels.contato_listar())["total"] == 1

    rascunho = asyncio.run(channels.telegram_send("mae", "oi mae"))  # apelido sem acento/caixa
    assert rascunho["enviado"] is False and enviados == [] and "mae" in rascunho["destinatario"].lower().replace("ã", "a")
    code = rascunho["codigo_confirmacao"]

    with pytest.raises(Exception):  # texto mudou: o codigo nao vale
        asyncio.run(channels.telegram_send("mae", "outro texto", codigo_confirmacao=code))
    assert enviados == []
    with pytest.raises(Exception):  # sem rascunho previo
        asyncio.run(channels.telegram_send("123", "oi mae", codigo_confirmacao="zzzz"))

    ok = asyncio.run(channels.telegram_send("mae", "oi mae", codigo_confirmacao=code))
    assert ok["enviado"] is True and enviados == [("123", "oi mae")]
    with pytest.raises(Exception):  # codigo de uso unico
        asyncio.run(channels.telegram_send("mae", "oi mae", codigo_confirmacao=code))
    assert asyncio.run(channels.contato_remover("mae"))["removido"] is True


# ------------------------------ lembretes ------------------------------

def test_lembrete_repetido_atrasado_nao_dispara_varias_vezes():
    from blind_mcp.servers import schedule

    agora = 1_000_000.0
    tres_dias_atras = agora - 3 * 86400 - 100
    nxt = schedule._next_after(tres_dias_atras, 1, agora)
    assert nxt > agora and nxt - agora <= 86400
    assert schedule._next_after(agora - 10, 7, agora) == agora - 10 + 7 * 86400


def test_lembrete_semanal_e_adiar(tmp_path, monkeypatch):
    from blind_mcp.servers import schedule

    monkeypatch.setattr(schedule, "MEMORY_DB", tmp_path / "m.db")
    schedule._init_db()
    r = schedule._create_sync("Remedio", "tomar", delay_minutes=5, repeat="semanal")
    assert r["repete"] == "toda semana"
    with pytest.raises(ValueError):
        schedule._create_sync("x", "y", delay_minutes=1, repeat="quinzenal")
    uni = schedule._create_sync("Agua", "beber", delay_minutes=1)
    assert uni["repete"] == "nao repete"

    # adiar um unico: muda o horario do mesmo
    s = schedule._snooze_sync("agua", 30)
    assert s["ok"] and s["id"] == uni["id"] and s["adiado_por_minutos"] == 30
    # adiar um repetido: cria aviso unico novo e mantem o original
    s2 = schedule._snooze_sync(r["id"], 10)
    assert s2["ok"] and s2["id"] != r["id"]
    lista = schedule._list_sync()
    assert lista["count"] == 3
    assert {x["repete"] for x in lista["schedules"]} == {"toda semana", "nao repete"}
    assert schedule._snooze_sync("nao-existe", 5)["ok"] is False


def test_migracao_de_banco_antigo(tmp_path, monkeypatch):
    from blind_mcp.servers import schedule

    db = tmp_path / "old.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE schedules (id TEXT PRIMARY KEY, title TEXT NOT NULL, message TEXT NOT NULL, "
                  "next_run_at REAL NOT NULL, repeat_daily INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active', "
                  "created_at REAL NOT NULL)")
        c.execute("INSERT INTO schedules VALUES ('a','t','m',1,1,'active',1)")
    monkeypatch.setattr(schedule, "MEMORY_DB", db)
    schedule._init_db()
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT repeat_days FROM schedules WHERE id='a'").fetchone()[0] == 1


# ------------------------------ posicao de leitura ------------------------------

def test_ler_documento_continua_de_onde_parou(tmp_path, monkeypatch):
    pymupdf = pytest.importorskip("pymupdf")
    from blind_mcp.servers import docs

    monkeypatch.setattr(docs, "POSITIONS_FILE", tmp_path / "pos.json")
    pdf = tmp_path / "livro.pdf"
    d = pymupdf.open()
    for i in range(1, 8):
        d.new_page().insert_text((72, 72), f"Capitulo {i}\nTexto da pagina {i}")
    d.set_toc([[1, "Inicio", 1], [1, "Meio", 4]])
    d.save(str(pdf))
    d.close()

    a = asyncio.run(docs.read_document(file_path=str(pdf), pages="1-2"))
    assert a["ultima_pagina_lida"] == 2
    b = asyncio.run(docs.read_document(file_path=str(pdf), continuar=True))
    assert "Texto da pagina 3" in b["text"] and b["ultima_pagina_lida"] == 5 and b["retomado_depois_da_pagina"] == 2
    c = asyncio.run(docs.read_document(file_path=str(pdf), continuar=True))
    assert c["ultima_pagina_lida"] == 7
    fim = asyncio.run(docs.read_document(file_path=str(pdf), continuar=True))
    assert fim.get("fim_do_documento") is True

    o = asyncio.run(docs.document_outline(str(pdf)))
    assert o["origem"].startswith("indice") and o["itens"][1] == {"nivel": 1, "titulo": "Meio", "pagina": 4}
    assert o["posicao_guardada"]["ultima_pagina_lida"] == 7


def test_gmail_drive_usam_conectores_do_claude_e_servidores_proprios_estao_desligados():
    from blind_mcp.config import load_specs

    specs = {x.name: x for x in load_specs()}
    assert specs["blind-mail"].enabled is False and specs["blind-drive"].enabled is False
    guia = " ".join(blind.GUIA.split())
    assert "CONECTORES" in guia and "so envie depois do sim" in guia
    est = blind.estado_servidores()
    assert "blind-mail" not in est["servidores_esperados"] and "blind-drive" not in est["servidores_esperados"]


# ------------------------------ vigia automatico (sem apertar nada de verdade) ------------------------------

class FakeApi:
    def __init__(self):
        self.down = set()
        self.released = []
        self.flags = {"Teclas de Aderencia": False, "Filtragem de Teclas": False, "Teclas do Mouse": False}
        self.unsafe = []
        self.killed = []
        self.disabled = []

    def pressed(self):
        return set(self.down)

    def release(self, name):
        self.released.append(name)
        self.down.discard(name)

    def accessibility_flags(self):
        return dict(self.flags)

    def unsafe_windows_mcp(self):
        return list(self.unsafe)

    def terminate_tree_of(self, pid):
        self.killed.append(pid)
        return True

    def disable_flag(self, flag):
        self.disabled.append(flag)
        self.flags[flag] = False
        return True


def _vigia(api, cfg=None):
    from blind_mcp.servers import _vigia as V

    t = {"now": 0.0}
    falas, logs = [], []
    conf = dict(V.DEFAULTS, **(cfg or {}))
    v = V.Vigia(api=api, clock=lambda: t["now"], speak=falas.append, log=logs.append, config=lambda: conf)
    return v, t, falas, logs


def test_vigia_e_silencioso_por_padrao():
    import time as _t

    api = FakeApi()
    v, t, falas, logs = _vigia(api)  # padrao: sem voz
    api.down = {"Shift"}
    v.tick()
    t["now"] = 30
    v.tick()
    _t.sleep(0.1)
    assert api.released == ["Shift"] and falas == []  # corrigiu sem falar nada
    assert any(l["server"] == "vigia" for l in logs)


def test_vigia_avisa_depois_solta_tecla_presa():
    import time as _t

    api = FakeApi()
    v, t, falas, logs = _vigia(api, {"avisar_por_voz": True})
    api.down = {"Shift"}
    v.tick()  # t=0: comeca a contar
    t["now"] = 5
    v.tick()
    assert not api.released and not v.events  # ainda normal
    t["now"] = 13
    v.tick()
    assert [e["tipo"] for e in v.events] == ["tecla_presa_aviso"] and not api.released
    t["now"] = 26
    v.tick()
    assert api.released == ["Shift"] and v.events[-1]["tipo"] == "tecla_presa_liberada"
    _t.sleep(0.1)
    assert any("Shift" in f for f in falas)  # avisou por voz
    assert any(l["server"] == "vigia" for l in logs)  # entrou no diario


def test_vigia_nao_mexe_em_tecla_solta_rapido_nem_com_liberar_desligado():
    api = FakeApi()
    v, t, _, _ = _vigia(api)
    api.down = {"Ctrl"}
    v.tick()
    t["now"] = 3
    api.down = set()  # soltou normalmente
    v.tick()
    t["now"] = 40
    v.tick()
    assert api.released == [] and v.events == []

    api2 = FakeApi()
    v2, t2, _, _ = _vigia(api2, {"liberar_teclas_presas": False})
    api2.down = {"mouse esquerdo"}
    v2.tick()
    t2["now"] = 100
    v2.tick()
    assert api2.released == []  # so avisa, pois a pessoa desligou a liberacao
    assert v2.events[-1]["tipo"] == "tecla_presa_aviso"


def test_vigia_mouse_tem_limites_maiores():
    api = FakeApi()
    v, t, _, _ = _vigia(api)
    api.down = {"mouse esquerdo"}
    v.tick()
    t["now"] = 20  # modificador ja liberaria, mouse ainda nao (arrastar e normal)
    v.tick()
    assert not v.events
    t["now"] = 31
    v.tick()
    assert v.events[-1]["tipo"] == "tecla_presa_aviso"
    t["now"] = 46
    v.tick()
    assert api.released == ["mouse esquerdo"]


def test_vigia_corrige_sozinho_recurso_que_ligou_e_copia_insegura():
    api = FakeApi()
    api.flags["Teclas do Mouse"] = True  # ja estava ligado no inicio: escolha da pessoa
    v, t, falas, _ = _vigia(api)
    api.flags["Filtragem de Teclas"] = True  # ligou sozinho durante a sessao
    api.unsafe = [{"pid": 99}]
    v.tick()
    v.tick()  # nao repete
    tipos = [e["tipo"] for e in v.events]
    assert api.disabled == ["Filtragem de Teclas"] and tipos.count("recurso_desligado") == 1
    assert api.killed == [99] and tipos.count("windows_mcp_inseguro_encerrado") == 1
    assert falas == []  # nada de voz
    assert "Teclas do Mouse" not in api.disabled  # o que ja estava ligado fica como a pessoa deixou


def test_vigia_so_registra_se_correcao_automatica_estiver_desligada():
    api = FakeApi()
    v, _, _, _ = _vigia(api, {"restaurar_recursos_de_acessibilidade": False, "encerrar_copias_inseguras": False})
    api.flags["Teclas de Aderencia"] = True
    api.unsafe = [{"pid": 5}]
    v.tick()
    assert api.disabled == [] and api.killed == []
    assert {e["tipo"] for e in v.events} == {"recurso_ligado", "windows_mcp_inseguro_aviso"}


def test_vigia_desligado_nao_faz_nada():
    api = FakeApi()
    v, t, _, _ = _vigia(api, {"ligado": False})
    api.down = {"Alt"}
    api.unsafe = [{"pid": 1}]
    v.tick()
    t["now"] = 100
    v.tick()
    assert api.released == [] and v.events == [] and v.ticks == 0


def test_vigia_configuracao_persiste(tmp_path, monkeypatch):
    from blind_mcp.servers import _vigia as V

    monkeypatch.setattr(V, "CONFIG_FILE", tmp_path / "vigia.json")
    monkeypatch.setattr(V, "DATA_DIR", tmp_path)
    assert V.load_config()["liberar_teclas_presas"] is True
    V.save_config({"liberar_teclas_presas": False, "encerrar_copias_inseguras": True, "inexistente": 1})
    c = V.load_config()
    assert c["liberar_teclas_presas"] is False and c["encerrar_copias_inseguras"] is True and "inexistente" not in c
    r = asyncio.run(system.vigia_status())
    assert r["ok"] and "o_que_faz" in r


def test_agenda_do_blind_lista_concluidos_e_guia_cita_calendar(tmp_path, monkeypatch):
    from blind_mcp.servers import schedule

    monkeypatch.setattr(schedule, "MEMORY_DB", tmp_path / "m.db")
    schedule._init_db()
    a = schedule._create_sync("Medico", "consulta", delay_minutes=60)
    with sqlite3.connect(schedule.MEMORY_DB) as c:
        c.execute("INSERT INTO schedules VALUES ('velho','Ontem','x',1,0,'completed',1,0)")
    assert schedule._list_sync()["count"] == 1
    todos = schedule._list_sync(True)
    assert todos["count"] == 2 and todos["schedules"][0]["id"] == a["id"]  # ativos primeiro
    assert "Blind calendar" in blind.GUIA and "Vigia automatico" in blind.GUIA


# ------------------------------ nomes exatos das ferramentas ------------------------------

def test_manifesto_de_ferramentas_esta_em_dia_com_o_codigo():
    from blind_mcp.manifest import build_manifest, load_manifest

    assert load_manifest() == build_manifest(), "Rode: python scripts/gerar-manifesto-ferramentas.py"


def test_comecar_devolve_nomes_exatos_e_a_regra_de_tool_search():
    r = asyncio.run(blind.comecar("qualquer"))
    nomes = r["nomes_exatos"]
    assert "mcp__blind-system__saude_teclado" in nomes["blind-system"]
    assert "mcp__blind-schedule__blindschedule_snooze" in nomes["blind-schedule"]
    todos = [n for lista in nomes.values() for n in lista]
    assert all(n.startswith("mcp__") for n in todos)
    assert not any(n.endswith("__Type") or n.endswith("__Shortcut") for n in todos)  # teclado removido
    assert "mcp__windows__Click" in todos and "mcp__windows__Scroll" in todos  # mouse ativo
    assert "mcp__blind-channels__telegram_connect" not in todos  # escondida do modelo
    assert "blind-mail" not in nomes and "blind-drive" not in nomes  # desligados
    guia = " ".join(r["guia"].split())
    assert "PELO NOME EXATO" in guia and "ToolSearch" in guia and "NAO diga que nao tem" in guia


# ------------------------------ atividades (tela do Electron) ------------------------------

def _write_audit(tmp_path, monkeypatch, rows):
    monkeypatch.setattr(_audit, "AUDIT_DIR", tmp_path)
    monkeypatch.setattr(_audit, "AUDIT_FILE", tmp_path / "acoes.jsonl")
    for r in rows:
        _audit.write_entry(r)


def test_atividades_em_frases_simples(tmp_path, monkeypatch):
    t = "2026-11-17T12:00:00"
    _write_audit(tmp_path, monkeypatch, [
        {"id": "1", "server": "agent-desktop", "tool": "launch_app", "args": {}, "evento": "inicio", "quando": t},
        {"id": "1", "server": "agent-desktop", "tool": "launch_app", "evento": "fim", "ok": True, "ms": 1500, "quando": t},
        {"id": "2", "server": "agent-desktop", "tool": "click", "args": {}, "evento": "inicio", "quando": t},
        {"id": "2", "server": "agent-desktop", "tool": "click", "evento": "fim", "ok": False, "erro": "STALE_REF: tela mudou", "quando": t},
        {"id": "3", "server": "blind-docs", "tool": "read_document", "args": {}, "evento": "inicio", "quando": t},
        {"id": "v", "server": "vigia", "tool": "tecla_presa_liberada", "args": {"detalhe": "Tecla Ctrl liberada apos 25 s"},
         "evento": "fim", "ok": True, "quando": t},
    ])
    r = _audit.activity(10)
    por_tool = {a["ferramenta"]: a for a in r["atividades"]}
    assert por_tool["launch_app"]["estado"] == "deu_certo" and "Abri um aplicativo: deu certo" in por_tool["launch_app"]["frase"]
    assert por_tool["click"]["estado"] == "falhou" and "A tela mudou. Tente de novo." in por_tool["click"]["frase"]
    assert por_tool["read_document"]["estado"] == "em_andamento"
    assert por_tool["tecla_presa_liberada"]["estado"] == "corrigido" and "Ctrl" in por_tool["tecla_presa_liberada"]["frase"]
    assert r["total"] == 4 and r["falhas"] == 1 and "1 com falha" in r["resumo"]
    so_erros = _audit.activity(10, only_errors=True)
    assert [a["ferramenta"] for a in so_erros["atividades"]] == ["click"]
    assert _audit.activity(10, server="blind-docs")["total"] == 1


def test_alerta_do_vigia_nao_diz_deu_certo(tmp_path, monkeypatch):
    _write_audit(tmp_path, monkeypatch, [
        {"id": "a", "server": "vigia", "tool": "tecla_presa_aviso", "args": {"detalhe": "Tecla Shift apertada ha 12 s"},
         "evento": "fim", "ok": True, "quando": "2026-11-17T12:00:00"}])
    a = _audit.activity(5)["atividades"][0]
    assert a["estado"] == "aviso" and "deu certo" not in a["frase"].lower()


def test_rota_api_activity(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from blind_mcp.api import router

    _write_audit(tmp_path, monkeypatch, [
        {"id": "9", "server": "blind-schedule", "tool": "blindschedule_create", "args": {}, "evento": "inicio", "quando": "2026-11-17T12:00:00"},
        {"id": "9", "server": "blind-schedule", "tool": "blindschedule_create", "evento": "fim", "ok": True, "ms": 12, "quando": "2026-11-17T12:00:01"}])
    app = FastAPI()
    app.include_router(router)
    r = TestClient(app).get("/api/activity?limit=5").json()
    assert r["ok"] and r["atividades"][0]["frase"] == "Criei um lembrete: deu certo." and r["atividades"][0]["origem"] == "Tarefas e lembretes"


# ------------------------------ dono unico das tarefas de fundo ------------------------------

def test_so_um_processo_e_dono_e_outro_assume_quando_o_dono_morre(tmp_path):
    import subprocess
    import sys
    import time as _t

    from core.leader import Leader

    code = ("import sys,time;sys.path.insert(0, r'%s')\n"
            "from pathlib import Path\nfrom core.leader import Leader\n"
            "l=Leader('teste', Path(r'%s'))\nprint('DONO' if l.try_acquire() else 'RESERVA', flush=True)\ntime.sleep(60)\n"
            % (str(Path(__file__).resolve().parents[2]), str(tmp_path)))
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "DONO"
        mine = Leader("teste", tmp_path)
        assert mine.try_acquire() is False and not mine.is_leader  # outro processo e o dono
        p.kill()
        p.wait(timeout=10)
        _t.sleep(0.3)
        assert mine.try_acquire() is True and mine.is_leader  # dono morreu: esta copia assume
        assert mine.owner_info().get("pid")
    finally:
        if p.poll() is None:
            p.kill()
    mine.release()


def test_vigia_reserva_nao_age_e_dono_age():
    api = FakeApi()

    class L:
        def __init__(self, dono):
            self.dono = dono

        def try_acquire(self):
            return self.dono

    from blind_mcp.servers import _vigia as V

    t = {"now": 0.0}
    conf = dict(V.DEFAULTS)
    reserva = V.Vigia(api=api, clock=lambda: t["now"], speak=lambda m: None, log=lambda e: None, config=lambda: conf, leader=L(False))
    dono = V.Vigia(api=api, clock=lambda: t["now"], speak=lambda m: None, log=lambda e: None, config=lambda: conf, leader=L(True))
    api.down = {"Alt"}
    for v in (reserva, dono):
        v.tick()
    t["now"] = 30
    for v in (reserva, dono):
        v.tick()
    assert api.released == ["Alt"]  # so UMA copia soltou a tecla (a dona)
    assert reserva.ticks == 0 and dono.ticks == 2


# ------------------------------ WhatsApp pelo conector (falso nos testes) ------------------------------

@pytest.fixture
def whatsapp(tmp_path, monkeypatch):
    import sys

    from core.channels.whatsapp_manager import WhatsAppManager

    fake = str(Path(__file__).with_name("fake_whatsapp_bridge.py"))
    monkeypatch.setenv("BLIND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BLIND_WHATSAPP_BRIDGE_CMD", f"{sys.executable}|{fake}")
    monkeypatch.delenv("BLIND_WHATSAPP_SIMULADO", raising=False)
    m = WhatsAppManager(tmp_path / "w.db")
    yield m
    proc = getattr(m, "_bridge_proc", None)
    if proc and proc.poll() is None:
        proc.kill()


def test_whatsapp_pareia_pelo_conector_e_usa_o_codigo_dele(whatsapp):
    r = whatsapp.start_pairing("11999990001")
    assert r["status"] == "waiting_link" and r["code"] == "ABCD1234" and r["phone"] == "5511999990001"
    assert "A B C D 1 2 3 4" in r["spoken_instructions"] and "Aparelhos Conectados" in r["spoken_instructions"]
    assert "simulated" not in r
    assert whatsapp.get_status("11999990001")["status"] == "waiting_link"


def test_whatsapp_status_vira_pareado_quando_o_celular_confirma(whatsapp):
    import httpx

    whatsapp.start_pairing("11999990001")
    info = whatsapp._bridge_info()
    httpx.post(f"http://127.0.0.1:{info['port']}/connect-now", headers={"Authorization": f"Bearer {info['token']}"}, json={})
    st = whatsapp.get_status("11999990001")
    assert st["status"] == "paired" and st["conector"]["estado"] == "connected"
    assert whatsapp.messages(5)["mensagens"][0]["texto"] == "oi"


def test_outra_copia_reutiliza_o_conector_que_ja_roda(whatsapp, tmp_path):
    from core.channels.whatsapp_manager import WhatsAppManager

    whatsapp.start_pairing("11999990001")
    pid = whatsapp._bridge_info()["pid"]
    outra = WhatsAppManager(tmp_path / "w2.db")  # outra copia do Blind (Claude ou Electron)
    assert outra._bridge_info()["pid"] == pid and outra.get_status("11999990001")["status"] == "waiting_link"
    assert getattr(outra, "_bridge_proc", None) is None  # nao subiu um segundo conector


def test_whatsapp_sem_conector_instalado_da_erro_claro_e_nao_gera_codigo(tmp_path, monkeypatch):
    from core.channels.whatsapp_manager import WhatsAppManager

    monkeypatch.setenv("BLIND_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("BLIND_WHATSAPP_BRIDGE_CMD", raising=False)
    monkeypatch.delenv("BLIND_WHATSAPP_SIMULADO", raising=False)
    m = WhatsAppManager(tmp_path / "w.db")
    monkeypatch.setattr(m, "bridge_command", lambda: None)
    with pytest.raises(RuntimeError, match="nao esta instalado"):
        m.start_pairing("11999990001")
    assert m.get_status("11999990001")["status"] == "not_found"  # nada foi gravado
    with pytest.raises(ValueError):
        m.start_pairing("123")


# ------------------------------ carregamento sob demanda: cache e configuracao gerada ------------------------------

def test_cache_de_ferramentas_dos_servidores_sob_demanda_esta_em_dia():
    import json as _json
    from blind_mcp.config import load_specs
    from blind_mcp.manifest import OWN_SERVERS, build_manifest

    proprios = build_manifest()["proprios"]
    cache_dir = Path(__file__).resolve().parents[1] / "tools_cache"
    lazy = [s for s in load_specs() if s.lazy and s.enabled]
    assert {s.name for s in lazy} >= {"agent-desktop", "blind-docs", "blind-channels", "windows", "blind-commander"}
    for s in lazy:
        cache = _json.loads((cache_dir / f"{s.name}.json").read_text(encoding="utf-8"))
        nomes = {t["name"] for t in cache["tools"]}
        if s.name in OWN_SERVERS:  # servidores proprios: o cache tem de bater com o codigo
            assert nomes == set(proprios[s.name]), f"{s.name}: rode python scripts/gerar-manifesto-ferramentas.py --cache"
        assert all("inputSchema" in t for t in cache["tools"])
    win = _json.loads((cache_dir / "windows.json").read_text(encoding="utf-8"))
    nomes_win = {t["name"] for t in win["tools"]}
    assert not {"Type", "Shortcut", "MultiEdit", "MultiSelect"} & nomes_win  # teclado: continua removido
    assert {"Click", "Move", "Scroll"} <= nomes_win  # mouse: reativado em 17/11/2026 (com o guarda)


def test_gerador_poe_so_o_proxy_nos_servidores_pesados_e_deixa_memoria_e_sistema_diretos():
    import json as _json
    import subprocess
    import sys as _sys

    root = Path(__file__).resolve().parents[3]
    out = subprocess.run([_sys.executable, str(root / "scripts" / "gerar-mcp-claude.py"), "--stdout"], capture_output=True, text=True,
                         timeout=60).stdout
    servers = _json.loads(out[: out.index("deny:")])["mcpServers"]
    for lazy in ("agent-desktop", "blind-docs", "blind-channels", "blind-speech", "windows", "blind-commander"):
        assert servers[lazy]["args"][:3] == ["-m", "blind_mcp.lazy_proxy", "--server"] and servers[lazy]["args"][3] == lazy
    for eager in ("blind", "blind-memory", "blind-schedule", "blind-system"):  # lembretes e vigia precisam estar rodando desde o inicio
        assert "lazy_proxy" not in " ".join(servers[eager]["args"])
    assert "blind-mail" not in servers and "blind-drive" not in servers


def test_whatsapp_messages_entende_midias_sozinho_com_limite(tmp_path, monkeypatch):
    import asyncio

    from blind_mcp.servers import channels

    arqs = {}
    for nome in ("a.ogg", "f.jpg", "v.mp4", "b.ogg"):
        (tmp_path / nome).write_bytes(b"x")
        arqs[nome] = str(tmp_path / nome)
    msgs = [{"id": "1", "tipo": "audio", "arquivo": arqs["a.ogg"]}, {"id": "2", "tipo": "imagem", "arquivo": arqs["f.jpg"]},
            {"id": "3", "tipo": "video", "arquivo": arqs["v.mp4"]}, {"id": "4", "tipo": "texto", "texto": "oi"},
            {"id": "5", "tipo": "audio", "arquivo": arqs["b.ogg"]}]
    monkeypatch.setattr(channels.whatsapp_manager, "messages", lambda limit: {"ok": True, "mensagens": [dict(m) for m in msgs]})
    monkeypatch.setattr(channels, "_transcribe_file_sync", lambda path, lang="pt": {"text": "ola mozao"})
    monkeypatch.setattr(channels, "_video_frame", lambda path: str(tmp_path / "f.jpg"))
    vistos = []

    async def fake_desc(file_path=None, **kw):
        vistos.append(file_path)
        return {"description": "foto de um gato"}

    monkeypatch.setattr(channels, "channel_describe_image", fake_desc)
    full = asyncio.run(channels.whatsapp_messages(10))  # sem pedir nada: tudo entendido
    m = full["mensagens"]
    assert m[0]["transcricao"] == "ola mozao" and m[1]["descricao"] == "foto de um gato"
    assert m[2]["transcricao"] and m[2]["descricao"] and m[3].get("texto") == "oi" and "transcricao" not in m[3]
    lim = asyncio.run(channels.whatsapp_messages(10, max_midias=2))  # limite: so as 2 mais novas, o resto avisa
    assert lim["midias_nao_processadas"] == 2 and "nao_processada" in lim["mensagens"][2] and "descricao" in lim["mensagens"][1]
    cru = asyncio.run(channels.whatsapp_messages(10, entender_midias=False))
    assert "transcricao" not in cru["mensagens"][0]

    def boom(path, lang="pt"):
        raise RuntimeError("sem modelo")

    monkeypatch.setattr(channels, "_transcribe_file_sync", boom)
    erro = asyncio.run(channels.whatsapp_messages(10))
    assert "sem modelo" in erro["mensagens"][0]["erro_midia"] and erro["mensagens"][3]["texto"] == "oi"  # erro nao derruba a lista


def test_whatsapp_send_em_duas_etapas(tmp_path, monkeypatch):
    import asyncio

    from blind_mcp.servers import channels

    monkeypatch.setattr(channels, "DATA_DIR", tmp_path)
    enviados = []
    monkeypatch.setattr(channels.whatsapp_manager, "send_text",
                        lambda text, phone="", jid="": enviados.append((text, phone, jid)) or {"ok": True, "id": "X1"})
    channels._PENDING.clear()
    asyncio.run(channels.contato_salvar("Mozão", "(11) 99999-0001", app="whatsapp"))
    assert asyncio.run(channels.contato_listar("telegram"))["total"] == 0  # separado do Telegram
    r1 = asyncio.run(channels.whatsapp_send("mozao", "Oi amor"))
    assert r1["enviado"] is False and enviados == [] and "5511999990001" in r1["destinatario"] and "Mozão" in r1["destinatario"]
    with pytest.raises(ValueError):  # texto diferente do rascunho
        asyncio.run(channels.whatsapp_send("mozao", "Outra coisa", r1["codigo_confirmacao"]))
    r2 = asyncio.run(channels.whatsapp_send("mozao", "Oi amor", r1["codigo_confirmacao"]))
    assert r2["enviado"] is True and enviados == [("Oi amor", "5511999990001", "")]
    with pytest.raises(ValueError):  # codigo so vale uma vez
        asyncio.run(channels.whatsapp_send("mozao", "Oi amor", r1["codigo_confirmacao"]))
    # resposta direta pelo jid de uma mensagem recebida
    r3 = asyncio.run(channels.whatsapp_send("123456@lid", "ok"))
    asyncio.run(channels.whatsapp_send("123456@lid", "ok", r3["codigo_confirmacao"]))
    assert enviados[-1] == ("ok", "", "123456@lid")
    # um rascunho de WhatsApp nao serve para o Telegram
    with pytest.raises(Exception):
        asyncio.run(channels.telegram_send("123", "ok", codigo_confirmacao=asyncio.run(channels.whatsapp_send("123456@lid", "ok"))["codigo_confirmacao"]))


def test_whatsapp_acha_contato_pelo_nome_da_agenda_e_pelo_parentesco(tmp_path, monkeypatch):
    import asyncio

    from blind_mcp.servers import channels

    monkeypatch.setattr(channels, "DATA_DIR", tmp_path)
    agenda = [
        {"jid": "1@s.whatsapp.net", "nome": "Mozão", "nome_publico": "", "telefone": "5511999990002"},
        {"jid": "2@s.whatsapp.net", "nome": "Mãe", "nome_publico": "", "telefone": "5511999990003"},
        {"jid": "3@s.whatsapp.net", "nome": "João Silva", "nome_publico": "", "telefone": "5511988881111"},
        {"jid": "4@s.whatsapp.net", "nome": "João Souza", "nome_publico": "", "telefone": "5511988882222"},
        {"jid": "5@lid", "nome": "Ana", "nome_publico": "", "telefone": ""},
    ]
    monkeypatch.setattr(channels.whatsapp_manager, "contacts", lambda: agenda)
    enviados = []
    monkeypatch.setattr(channels.whatsapp_manager, "send_text",
                        lambda text, phone="", jid="": enviados.append((phone, jid)) or {"ok": True, "id": "Z"})
    channels._PENDING.clear()
    assert channels._wa_resolve("mozao")[0] == "5511999990002"  # sem acento nem caixa
    assert channels._wa_resolve("MÃE")[2] == "Mãe"
    with pytest.raises(ValueError) as e:  # dois Joaos: pergunta qual, nao escolhe
        channels._wa_resolve("joao")
    assert "Silva" in str(e.value) and "Souza" in str(e.value) and "final 1111" in str(e.value)
    assert channels._wa_resolve("joao silva")[0] == "5511988881111"
    assert channels._wa_resolve("ana") == ("", "5@lid", "Ana")  # sem telefone: usa o jid
    with pytest.raises(ValueError):
        channels._wa_resolve("fulano inexistente")
    # parentesco: "minha mulher" guarda o nome da agenda; depois o envio entende
    out = asyncio.run(channels.contato_salvar("minha mulher", "Mozão", app="whatsapp"))
    assert out["chat_id"] == "5511999990002"
    assert channels._wa_resolve("minha mulher")[0] == "5511999990002"
    r = asyncio.run(channels.whatsapp_send("minha mulher", "Oi"))
    assert "minha mulher" in r["destinatario"] and enviados == []  # rascunho primeiro
    asyncio.run(channels.whatsapp_send("minha mulher", "Oi", r["codigo_confirmacao"]))
    assert enviados == [("5511999990002", "")]
    achados = asyncio.run(channels.whatsapp_contatos("mae"))
    assert achados["total"] == 1 and achados["contatos"][0]["final_telefone"] == "0003"
