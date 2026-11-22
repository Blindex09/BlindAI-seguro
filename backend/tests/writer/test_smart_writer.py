"""Testes unitários para o SmartWriter Acessível."""

import os
from pathlib import Path
from core.writer.smart_writer import SmartWriter


def test_smart_writer_draft_and_save(tmp_path: Path):
    writer = SmartWriter(workspace_dir=tmp_path)
    
    draft = writer.draft_document(
        title="Lista de Compras",
        content="1. Leite desnatado\n2. Pão integral\n3. Café em pó",
        filename="compras.txt"
    )

    assert draft["ready_to_save"] is True
    assert "compras.txt" in draft["spoken_review"]
    assert "Lista de Compras" in draft["spoken_review"]

    result = writer.save_document(draft)
    assert result["status"] == "success"

    saved_file = tmp_path / "compras.txt"
    assert saved_file.exists()
    assert "Café em pó" in saved_file.read_text(encoding="utf-8")


def test_nome_com_docx_gera_word_de_verdade(tmp_path):
    from docx import Document

    w = SmartWriter(tmp_path)
    d = w.draft_document("Carta", "Linha um.\n\nLinha dois.", "../fora/carta.docx")
    assert d["format"] == "docx" and d["target_path"].startswith(str(tmp_path))
    r = w.save_document(d)
    assert [p.text for p in Document(r["path"]).paragraphs] == ["Carta", "Linha um.", "Linha dois."]


def test_planilha_apresentacao_e_pdf_ida_e_volta(tmp_path):
    from blind_mcp.servers.docs import _extract_pdf_sync

    w = SmartWriter(tmp_path)
    casos = {
        "g.xlsx": ("Gastos", "Item;Valor\nMercado;150,5\nTotal;=SUM(B2:B2)", ["Item | Valor", "Mercado | 150.5", "Total | 150.5 (formula =SUM"]),
        "a.pptx": ("Aula", "Intro\n- um\n- dois\n\nFim\n- ok", ["Slide 2: Intro", "- um", "Slide 3: Fim"]),
        "c.pdf": ("Carta", "# Oi\nmãe e ação", ["Carta", "mãe e ação"]),
    }
    for nome, (titulo, texto, esperado) in casos.items():
        r = w.save_document(w.draft_document(titulo, texto, nome))
        lido = _extract_pdf_sync(r["path"], None)["digital_text"]
        for trecho in esperado:
            assert trecho in lido, (nome, trecho, lido)


def test_verificacao_de_acessibilidade_acha_defeitos_e_aprova_o_que_o_blind_cria(tmp_path):
    import openpyxl
    from core.writer import acessibilidade_docs as ac

    w = SmartWriter(tmp_path)
    for nome, texto in {"a.xlsx": "Item;Valor\nLuz;98", "b.pptx": "Intro\n- um", "c.docx": "Oi\n\nTudo bem."}.items():
        r = w.save_document(w.draft_document("Titulo", texto, nome))
        res = ac.verificar(r["path"])
        assert not [p for p in res["problemas"] if p["gravidade"] == "alta"], (nome, res["problemas"])
        assert res["conferiu"] and "resumo_falado" in res
    # planilha ruim: sem titulo, aba generica, celulas mescladas, linha vazia no meio, 1a linha com numeros
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([1, 2])
    ws.append([])
    ws.append(["x", "y"])
    ws.merge_cells("A3:B3")
    wb.save(tmp_path / "ruim.xlsx")
    gravs = {p["problema"] for p in ac.verificar(str(tmp_path / "ruim.xlsx"))["problemas"]}
    assert any("mescladas" in g for g in gravs) and any("vazia" in g for g in gravs) and any("cabeçalho" in g for g in gravs)
    # PDF sem texto
    import pymupdf

    d = pymupdf.open()
    d.new_page()
    d.save(tmp_path / "vazio.pdf")
    assert any("não tem texto" in p["problema"] for p in ac.verificar(str(tmp_path / "vazio.pdf"))["problemas"])


def test_planilha_gravada_pelo_blind_ja_tem_valor_nas_formulas(tmp_path):
    import openpyxl
    import pytest
    from core.writer import office_io

    if not office_io.achar_soffice():
        pytest.skip("LibreOffice nao instalado")
    w = SmartWriter(tmp_path)
    r = w.save_document(w.draft_document("Gastos", "Item;Valor\nA;10\nB;5,5\nTotal;=SUM(B2:B3)", "g.xlsx"))
    assert openpyxl.load_workbook(r["path"], data_only=True).active["B4"].value == 15.5
    assert openpyxl.load_workbook(r["path"]).active["B4"].value == "=SUM(B2:B3)"
