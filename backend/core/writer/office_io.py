"""Ler e criar planilhas (xlsx), apresentacoes (pptx) e PDFs de forma acessivel, sem depender do Office instalado.

Leitura: devolve "unidades" (uma por aba ou slide) em texto falavel, com cabecalhos e nomes, sem inventar nada.
Escrita: o texto da minuta vira o arquivo (formatos descritos em FORMATOS_AJUDA).
"""

from __future__ import annotations

import html
import re
from typing import List, Tuple

MAX_LINHAS_POR_ABA = 500

FORMATOS_AJUDA = (
    "xlsx: cada linha do texto e uma linha da planilha, celulas separadas por ';' (ou TAB); numeros viram numeros (150,5 ou "
    "150.5), '=SOMA' nao: use formulas em ingles como =SUM(B2:B3); a 1a linha e o cabecalho; '## Nome' comeca uma nova aba. "
    "pptx: blocos separados por linha em branco sao slides; a 1a linha do bloco e o titulo e as outras viram topicos. "
    "pdf: paragrafos separados por linha em branco; '# ' no inicio da linha e titulo."
)


# ---------------------------------------------------------------- leitura
def _celula(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def ler_xlsx(path: str) -> List[Tuple[str, str]]:
    import openpyxl

    wf = openpyxl.load_workbook(path, data_only=False, read_only=False)
    wv = openpyxl.load_workbook(path, data_only=True, read_only=False)
    saida: List[Tuple[str, str]] = []
    for ws in wf.worksheets:
        wsv = wv[ws.title]
        linhas: List[str] = []
        total = 0
        for r_idx, (rf, rv) in enumerate(zip(ws.iter_rows(), wsv.iter_rows()), start=1):
            partes = []
            for cf, cv in zip(rf, rv):
                val = cv.value
                f = cf.value
                if isinstance(f, str) and f.startswith("="):
                    texto = f"{_celula(val)} (formula {f})" if val is not None else f"formula {f} (sem valor guardado)"
                else:
                    texto = _celula(val)
                partes.append(texto)
            while partes and not partes[-1]:
                partes.pop()
            if not partes:
                continue
            total += 1
            if total <= MAX_LINHAS_POR_ABA:
                linhas.append(f"Linha {r_idx}: " + " | ".join(p if p else "(vazio)" for p in partes))
        cab = f"Aba '{ws.title}': {total} linha(s) com dados, {ws.max_column} coluna(s)."
        if total > MAX_LINHAS_POR_ABA:
            linhas.append(f"... mostrei so as primeiras {MAX_LINHAS_POR_ABA} linhas de {total}.")
        saida.append((ws.title, cab + "\n" + ("\n".join(linhas) if linhas else "A aba esta vazia.")))
    wf.close()
    wv.close()
    return saida


def ler_pptx(path: str) -> List[Tuple[str, str]]:
    from pptx import Presentation

    prs = Presentation(path)
    saida: List[Tuple[str, str]] = []
    for n, slide in enumerate(prs.slides, start=1):
        titulo = ""
        try:
            if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
                titulo = slide.shapes.title.text_frame.text.strip()
        except Exception:  # noqa: BLE001
            pass
        linhas: List[str] = []
        imagens = 0
        for shp in slide.shapes:
            if shp.has_text_frame:
                if slide.shapes.title is not None and shp.shape_id == slide.shapes.title.shape_id:
                    continue
                for p in shp.text_frame.paragraphs:
                    t = "".join(r.text for r in p.runs).strip()
                    if t:
                        linhas.append(("  " * p.level) + "- " + t)
            elif getattr(shp, "has_table", False) and shp.has_table:
                for row in shp.table.rows:
                    linhas.append("Tabela: " + " | ".join(c.text.strip() or "(vazio)" for c in row.cells))
            elif shp.shape_type == 13:  # imagem
                imagens += 1
                alt = ""
                try:
                    alt = shp._element.xpath(".//p:cNvPr")[0].get("descr") or ""
                except Exception:  # noqa: BLE001
                    pass
                linhas.append(f"[Imagem{': ' + alt if alt else ' sem texto alternativo'}]")
        notas = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notas = slide.notes_slide.notes_text_frame.text.strip()
        cab = f"Slide {n}" + (f": {titulo}" if titulo else " (sem titulo)")
        corpo = "\n".join(linhas) if linhas else "(sem texto)"
        saida.append((cab, cab + "\n" + corpo + (f"\nNotas do apresentador: {notas}" if notas else "")))
    return saida


# --------------------------------------------------------------- escrita
def _numero(txt: str):
    t = txt.strip()
    if not t:
        return None
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", t):  # 1.234,56
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d+,\d+", t):  # 150,5
        t = t.replace(",", ".")
    if re.fullmatch(r"-?\d+(\.\d+)?", t):
        return float(t) if "." in t else int(t)
    return None


def escrever_xlsx(destino: str, titulo: str, conteudo: str) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    wb.properties.title = titulo or "Planilha"
    ws = wb.active
    ws.title = (titulo or "Planilha")[:31].replace("/", "-").replace("\\", "-").replace("?", "").replace("*", "") or "Planilha"
    primeira = True
    for linha in conteudo.splitlines():
        if linha.startswith("## "):
            nome = linha[3:].strip()[:31] or "Aba"
            if primeira and ws.max_row == 1 and ws["A1"].value is None:
                ws.title = nome
            else:
                ws = wb.create_sheet(nome)
            primeira = False
            continue
        if not linha.strip():
            continue
        primeira = False
        sep = "\t" if "\t" in linha else ";"
        celulas = []
        for c in linha.split(sep):
            c = c.strip()
            n = _numero(c)
            celulas.append(n if n is not None else c)
        ws.append(celulas)
        if ws.max_row == 1:
            for c in ws[1]:
                c.font = Font(bold=True)
    for w in wb.worksheets:
        for col in w.columns:
            w.column_dimensions[col[0].column_letter].width = min(50, max(10, max(len(str(c.value or "")) for c in col) + 2))
    wb.save(destino)


def escrever_pptx(destino: str, titulo: str, conteudo: str) -> None:
    from pptx import Presentation

    prs = Presentation()
    prs.core_properties.title = titulo
    blocos = [b for b in re.split(r"\n\s*\n", conteudo.strip()) if b.strip()]
    capa = prs.slides.add_slide(prs.slide_layouts[0])
    capa.shapes.title.text = titulo
    capa.placeholders[1].text = ""
    for bloco in blocos:
        linhas = [l.rstrip() for l in bloco.strip().splitlines() if l.strip()]
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = linhas[0].lstrip("#- ").strip()
        tf = s.placeholders[1].text_frame
        tf.clear()
        topicos = [re.sub(r"^[-*•]\s*", "", l.strip()) for l in linhas[1:]] or [""]
        tf.text = topicos[0]
        for t in topicos[1:]:
            tf.add_paragraph().text = t
    prs.save(destino)


def escrever_pdf(destino: str, titulo: str, conteudo: str) -> None:
    import pymupdf

    partes = [f"<h1>{html.escape(titulo)}</h1>"] if titulo else []
    for par in re.split(r"\n\s*\n", conteudo.strip()):
        par = par.strip()
        if not par:
            continue
        if par.startswith("# "):
            partes.append(f"<h2>{html.escape(par[2:].strip())}</h2>")
        else:
            partes.append("<p>" + "<br>".join(html.escape(l) for l in par.splitlines()) + "</p>")
    css = "body{font-family:sans-serif;font-size:12pt;line-height:1.4} h1{font-size:20pt} h2{font-size:15pt} p{margin:0 0 10pt 0}"
    story = pymupdf.Story(html="".join(partes), user_css=css)
    pagina = pymupdf.paper_rect("a4")
    area = pagina + (56, 56, -56, -56)
    w = pymupdf.DocumentWriter(destino)
    mais = 1
    while mais:
        dev = w.begin_page(pagina)
        mais, _ = story.place(area)
        story.draw(dev)
        w.end_page()
    w.close()
    doc = pymupdf.open(destino)
    try:
        doc.set_metadata({"title": titulo or "", "producer": "Blind AI"})
        doc.xref_set_key(doc.pdf_catalog(), "Lang", "(pt-BR)")  # idioma do documento
        doc.saveIncr()
    finally:
        doc.close()


def achar_soffice() -> str:
    import os
    import shutil

    for c in (shutil.which("soffice"), r"C:\Program Files\LibreOffice\program\soffice.exe",
              r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
        if c and os.path.isfile(c):
            return c
    return ""


def recalcular_xlsx(caminho: str, tempo_max: int = 120) -> bool:
    """Calcula as formulas com o LibreOffice (em uma copia) e guarda os valores no arquivo, para leitores e previsualizadores
    verem os numeros sem abrir o Excel. Sem LibreOffice ou se algo falhar, deixa o arquivo como esta e devolve False."""
    import os
    import shutil
    import subprocess
    import tempfile

    import openpyxl

    soffice = achar_soffice()
    if not soffice:
        return False
    try:
        wb = openpyxl.load_workbook(caminho)
        if not any(isinstance(c.value, str) and c.value.startswith("=") for ws in wb.worksheets for row in ws.iter_rows() for c in row):
            return False  # sem formulas, nada a calcular
        with tempfile.TemporaryDirectory() as tmp:
            saida = os.path.join(tmp, "out")
            perfil = os.path.join(tmp, "perfil")
            os.makedirs(saida)
            subprocess.run(
                [soffice, f"-env:UserInstallation=file:///{perfil.replace(os.sep, '/')}", "--headless", "--norestore",
                 "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", saida, caminho],
                capture_output=True, timeout=tempo_max, check=False)
            novo = os.path.join(saida, os.path.basename(caminho))
            if not os.path.isfile(novo):
                return False
            vals = openpyxl.load_workbook(novo, data_only=True)
            forms = openpyxl.load_workbook(novo)
            ok = True
            for ws in forms.worksheets:
                for row in ws.iter_rows():
                    for c in row:
                        if isinstance(c.value, str) and c.value.startswith("=") and vals[ws.title][c.coordinate].value is None:
                            ok = False
            if not ok:
                return False
            vals.close()
            wbn = openpyxl.load_workbook(novo)
            wbn.properties.title = wb.properties.title  # o LibreOffice as vezes zera o titulo
            wbn.save(novo)
            # abrir e salvar de novo com openpyxl apaga os valores guardados: refaz o calculo uma vez e fica com essa versao
            saida2 = os.path.join(tmp, "out2")
            os.makedirs(saida2)
            subprocess.run(
                [soffice, f"-env:UserInstallation=file:///{perfil.replace(os.sep, '/')}", "--headless", "--norestore",
                 "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", saida2, novo],
                capture_output=True, timeout=tempo_max, check=False)
            final = os.path.join(saida2, os.path.basename(novo))
            if not os.path.isfile(final):
                return False
            shutil.copyfile(final, caminho)
            return True
    except Exception:  # noqa: BLE001 - melhor esforco: o arquivo original continua valido
        return False
