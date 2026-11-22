"""Testes das ferramentas MCP de acessibilidade integradas ao Blind AI (blind-docs, blind-memory, blind-channels)."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

import pymupdf
import pytest

from blind_mcp.servers import channels as srv_channels
from blind_mcp.servers import docs as srv_docs
from blind_mcp.servers import memory as srv_memory
from blind_mcp.servers import schedule as srv_schedule


def test_pdf_forms_fill_and_merge_split(tmp_path: Path):
    """Cria um PDF real com formulario interativo, lista os campos, preenche e divide paginas."""
    pdf_path = tmp_path / "form.pdf"
    doc = pymupdf.open()
    page1 = doc.new_page()
    page1.insert_text((50, 50), "Formulario de Cadastro Acessivel")
    widget = pymupdf.Widget()
    widget.field_name = "nome_completo"
    widget.field_label = "Nome Completo"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.rect = pymupdf.Rect(50, 80, 300, 110)
    widget.field_value = ""
    page1.add_widget(widget)

    page2 = doc.new_page()
    page2.insert_text((50, 50), "Segunda pagina do contrato")
    doc.save(str(pdf_path))
    doc.close()

    # 1. Lista campos do formulario
    forms_res = asyncio.run(srv_docs.pdf_forms(str(pdf_path)))
    assert forms_res["ok"] is True
    assert forms_res["count"] == 1
    assert forms_res["fields"][0]["name"] == "nome_completo"

    # 2. Preenche o campo e salva em novo PDF
    filled_path = tmp_path / "filled.pdf"
    fill_res = asyncio.run(
        srv_docs.pdf_fill(str(pdf_path), str(filled_path), {"nome_completo": "Maria Silva", "inexistente": "x"})
    )
    assert fill_res["ok"] is True
    assert "nome_completo" in fill_res["filled"]
    assert "inexistente" in fill_res["missing"]

    # Confirma valor gravado
    forms_after = asyncio.run(srv_docs.pdf_forms(str(filled_path)))
    assert forms_after["fields"][0]["value"] == "Maria Silva"

    # 3. Extrai apenas a pagina 2 (split)
    split_path = tmp_path / "page2.pdf"
    split_res = asyncio.run(
        srv_docs.pdf_merge_split("split", str(split_path), [str(filled_path)], pages="2")
    )
    assert split_res["ok"] is True
    assert split_res["pages"] == 1

    read_res = asyncio.run(srv_docs.read_document(file_path=str(split_path), ocr_scanned=False))
    assert "Segunda pagina" in read_res["text"]


def test_scanned_pdf_triggers_ocr_vision(tmp_path: Path, monkeypatch):
    """Quando um PDF nao tem texto selecionavel (escaneado), read_document usa o roteador de visao para OCR."""
    scanned_pdf = tmp_path / "scanned.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    # Desenha apenas forma grafica sem texto selecionavel
    page.draw_rect(pymupdf.Rect(40, 40, 200, 100), color=(0, 0, 0), fill=(0.8, 0.8, 0.8))
    doc.save(str(scanned_pdf))
    doc.close()

    async def fake_describe_multimodal(**kwargs):
        assert kwargs.get("image_base64")
        return "Conta de Energia - Valor R$ 184,90 - Vencimento 20/11/2026"

    monkeypatch.setattr(srv_docs.smart_vision_router, "describe_multimodal", fake_describe_multimodal)

    res = asyncio.run(srv_docs.read_document(file_path=str(scanned_pdf), ocr_scanned=True))
    assert res["ocr_pages_read"] == 1
    assert "184,90" in res["text"]


def test_url_safety_and_clean_html_extraction():
    """Bloqueia URLs com credenciais ou loopback (SSRF) e limpa anuncios/menus do HTML."""
    with pytest.raises(ValueError, match="usuario/senha"):
        srv_docs._validate_safe_public_url("https://admin:1234@example.com/secret")
    with pytest.raises(ValueError, match="locais|privado"):
        srv_docs._validate_safe_public_url("http://127.0.0.1:8765/api/status")

    raw_html = """
    <html>
      <head><title>Portal de Noticias</title><script>alert(1)</script></head>
      <body>
        <nav>Menu Principal | Assine</nav>
        <article>
          <h1>Novo Leitor Acessivel</h1>
          <p>O sistema permite leitura limpa sem banners.</p>
        </article>
        <footer>Rodape comercial</footer>
      </body>
    </html>
    """
    title, text = srv_docs._html_to_clean_accessible_text(raw_html)
    assert title == "Portal de Noticias"
    assert "# Novo Leitor Acessivel" in text
    assert "O sistema permite leitura limpa sem banners." in text
    assert "Menu Principal" not in text
    assert "alert(1)" not in text


def test_memory_session_search_and_schedules(tmp_path: Path, monkeypatch):
    """Testa memoria persistente, busca no historico de sessoes e agendamento de lembretes."""
    mem_db = tmp_path / "blind_memory.db"
    sess_db = tmp_path / "blind_sessions.db"
    monkeypatch.setattr(srv_memory, "MEMORY_DB", mem_db)
    monkeypatch.setattr(srv_memory, "SESSIONS_DB", sess_db)
    srv_memory._init_db()
    monkeypatch.setattr(srv_schedule, "MEMORY_DB", mem_db)
    srv_schedule._init_db()

    # 1. Salva e recupera memoria pessoal
    saved = asyncio.run(srv_memory.memory_save("cpf", "123.456.789-00", category="documentos"))
    assert saved["ok"] is True

    recalled = asyncio.run(srv_memory.memory_recall(query="123.456"))
    assert recalled["count"] == 1
    assert recalled["memories"][0]["key"] == "cpf"

    forgotten = asyncio.run(srv_memory.memory_forget("cpf"))
    assert forgotten["deleted"] is True

    # 2. Cria sessao de teste e busca via session_search
    now = time.time()
    with sqlite3.connect(sess_db) as conn:
        conn.execute(
            "CREATE TABLE chat_sessions (id TEXT PRIMARY KEY, title TEXT, source TEXT, created_at REAL, updated_at REAL)"
        )
        conn.execute(
            "CREATE TABLE chat_history (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, sender TEXT, text TEXT, is_user INTEGER, created_at REAL)"
        )
        conn.execute(
            "INSERT INTO chat_sessions VALUES ('s1', 'Fatura de Luz Novembro', 'docs', ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO chat_history (session_id, sender, text, is_user, created_at) VALUES ('s1', 'Blind AI', 'O protocolo da CEMIG e 99887766 e o valor e R$ 210,00.', 0, ?)",
            (now,),
        )
        conn.commit()

    search_res = asyncio.run(srv_memory.session_search("protocolo 99887766"))
    assert search_res["ok"] is True
    assert search_res["count"] == 1
    assert "210,00" in search_res["matches"][0]["text"]

    # 3. Cria, lista e remove lembrete falado
    sched = asyncio.run(srv_schedule.blindschedule_create("Tomar remedio", "Comprimido da pressao", delay_minutes=30))
    assert sched["ok"] is True
    listed = asyncio.run(srv_schedule.blindschedule_list())
    assert listed["count"] == 1
    deleted = asyncio.run(srv_schedule.blindschedule_delete(sched["id"]))
    assert deleted["deleted"] is True


def test_telegram_media_update_and_channel_describe(tmp_path: Path, monkeypatch):
    """Verifica persistencia de fotos/audios no Telegram e audiodescricao via channel_describe_image."""
    from core.channels.telegram_manager import TelegramManager

    tg = TelegramManager(db_path=tmp_path / "channels.db")
    tg._store_update(
        1001,
        {
            "update_id": 1,
            "message": {
                "chat": {"id": 555},
                "photo": [{"file_id": "small_id"}, {"file_id": "large_photo_id"}],
                "caption": "Comprovante PIX",
            },
        },
    )
    msgs = tg.get_messages(chat_id=555)
    assert len(msgs) == 1
    assert msgs[0]["media_type"] == "photo"
    assert msgs[0]["file_id"] == "large_photo_id"

    async def fake_dl(file_id: str, bot_id=None):
        assert file_id == "large_photo_id"
        return b"\x89PNG\r\n\x1a\nfake", "photos/pix.jpg"

    async def fake_desc(**kwargs):
        return "Comprovante PIX no valor de R$ 95,00 enviado para Joao."

    monkeypatch.setattr(srv_channels.telegram_manager, "download_file_bytes", fake_dl)
    monkeypatch.setattr(srv_channels.smart_vision_router, "describe_multimodal", fake_desc)

    desc_res = asyncio.run(srv_channels.channel_describe_image(telegram_file_id="large_photo_id"))
    assert desc_res["ok"] is True
    assert "R$ 95,00" in desc_res["description"]
