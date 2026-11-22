"""Confere a acessibilidade de um documento (Word, planilha, apresentacao ou PDF) para quem usa leitor de tela.

Verificacoes simples e locais, no espirito das regras do projeto aberto Community-Access/accessibility-agents (MIT) e da
WebAIM: titulo do arquivo, titulos de secao ou de slide, texto alternativo de imagens, cabecalhos de tabela, linhas vazias,
celulas mescladas, texto real no PDF. Nada sai do computador. Nao substitui uma auditoria completa: diz o que conferiu.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def _p(grav: str, texto: str, corrigir: str) -> Dict[str, str]:
    return {"gravidade": grav, "problema": texto, "como_corrigir": corrigir}


def _docx(path: str) -> Dict[str, Any]:
    from docx import Document

    d = Document(path)
    probs: List[Dict[str, str]] = []
    bons: List[str] = []
    conferiu = ["titulo do arquivo", "titulos de secao", "imagens sem texto alternativo", "tabelas"]
    if (d.core_properties.title or "").strip():
        bons.append("O arquivo tem título.")
    else:
        probs.append(_p("media", "O arquivo não tem título nas propriedades.", "Definir o título do documento."))
    palavras = sum(len(par.text.split()) for par in d.paragraphs)
    titulos = [par for par in d.paragraphs if (par.style.name or "").lower().startswith(("heading", "título", "titulo", "title"))]
    if titulos:
        bons.append(f"Tem {len(titulos)} título(s) de seção.")
    elif palavras > 300:
        probs.append(_p("alta", f"Texto longo ({palavras} palavras) sem títulos de seção.",
                        "Usar estilos de título para o leitor de tela pular entre partes."))
    sem_alt = 0
    for shp in d.inline_shapes:
        try:
            alt = shp._inline.docPr.get("descr") or ""
        except Exception:  # noqa: BLE001
            alt = ""
        if not alt.strip():
            sem_alt += 1
    if sem_alt:
        probs.append(_p("alta", f"{sem_alt} imagem(ns) sem texto alternativo.", "Descrever cada imagem em poucas palavras."))
    if d.tables:
        probs.append(_p("info", f"Tem {len(d.tables)} tabela(s). Confira se a primeira linha é cabeçalho e se não há células mescladas.",
                        "Marcar a primeira linha como cabeçalho e evitar mesclar."))
    return {"tipo": "Word", "problemas": probs, "pontos_bons": bons, "conferiu": conferiu}


def _xlsx(path: str) -> Dict[str, Any]:
    import openpyxl

    wb = openpyxl.load_workbook(path)
    probs: List[Dict[str, str]] = []
    bons: List[str] = []
    conferiu = ["titulo do arquivo", "nomes das abas", "cabecalho na primeira linha", "linhas vazias", "celulas mescladas"]
    if (wb.properties.title or "").strip():
        bons.append("O arquivo tem título.")
    else:
        probs.append(_p("media", "O arquivo não tem título nas propriedades.", "Definir o título da planilha."))
    for ws in wb.worksheets:
        if ws.title.lower().startswith(("sheet", "planilha", "plan")) and ws.title[-1:].isdigit():
            probs.append(_p("media", f"A aba '{ws.title}' tem nome genérico.", "Dar um nome que diga o conteúdo."))
        if ws.merged_cells.ranges:
            probs.append(_p("alta", f"A aba '{ws.title}' tem {len(ws.merged_cells.ranges)} grupo(s) de células mescladas.",
                            "Desmesclar: leitores de tela se perdem em células mescladas."))
        linhas = [r for r in ws.iter_rows(values_only=True)]
        ocupadas = [i for i, r in enumerate(linhas) if any(v not in (None, "") for v in r)]
        if not ocupadas:
            continue
        primeira = linhas[ocupadas[0]]
        textos = [v for v in primeira if v not in (None, "")]
        if textos and not all(isinstance(v, str) for v in textos):
            probs.append(_p("alta", f"Na aba '{ws.title}', a primeira linha não parece um cabeçalho (tem números).",
                            "Colocar uma linha de cabeçalho com o nome de cada coluna."))
        buracos = (ocupadas[-1] - ocupadas[0] + 1) - len(ocupadas)
        if buracos:
            probs.append(_p("media", f"A aba '{ws.title}' tem {buracos} linha(s) vazia(s) no meio dos dados.",
                            "Remover as linhas vazias: o leitor de tela pode achar que a planilha acabou."))
    if not probs:
        bons.append("Abas com nome claro, cabeçalho na primeira linha, sem linhas vazias no meio nem células mescladas.")
    return {"tipo": "planilha", "problemas": probs, "pontos_bons": bons, "conferiu": conferiu}


def _pptx(path: str) -> Dict[str, Any]:
    from pptx import Presentation

    prs = Presentation(path)
    probs: List[Dict[str, str]] = []
    bons: List[str] = []
    conferiu = ["titulo do arquivo", "titulo em cada slide", "imagens sem texto alternativo"]
    if (prs.core_properties.title or "").strip():
        bons.append("O arquivo tem título.")
    else:
        probs.append(_p("media", "O arquivo não tem título nas propriedades.", "Definir o título da apresentação."))
    sem_titulo: List[int] = []
    sem_alt = 0
    for n, slide in enumerate(prs.slides, start=1):
        t = slide.shapes.title
        if t is None or not t.has_text_frame or not t.text_frame.text.strip():
            sem_titulo.append(n)
        for shp in slide.shapes:
            if shp.shape_type == 13:
                try:
                    alt = shp._element.xpath(".//p:cNvPr")[0].get("descr") or ""
                except Exception:  # noqa: BLE001
                    alt = ""
                if not alt.strip():
                    sem_alt += 1
    if sem_titulo:
        probs.append(_p("alta", "Slide(s) sem título: " + ", ".join(map(str, sem_titulo[:10])) + ".",
                        "Dar um título único a cada slide: é por ele que o leitor de tela navega."))
    else:
        bons.append("Todos os slides têm título.")
    if sem_alt:
        probs.append(_p("alta", f"{sem_alt} imagem(ns) sem texto alternativo.", "Descrever cada imagem."))
    return {"tipo": "apresentação", "problemas": probs, "pontos_bons": bons, "conferiu": conferiu}


def _pdf(path: str) -> Dict[str, Any]:
    import pymupdf

    doc = pymupdf.open(path)
    probs: List[Dict[str, str]] = []
    bons: List[str] = []
    conferiu = ["texto de verdade (nao so imagem)", "titulo", "marcacao de estrutura (PDF com tags)", "idioma"]
    try:
        paginas = len(doc)
        com_texto = sum(1 for pg in doc if (pg.get_text() or "").strip())
        if paginas and com_texto == 0:
            probs.append(_p("alta", "O PDF não tem texto: são só imagens (escaneado).", "Refazer com texto ou aplicar reconhecimento de texto (OCR)."))
        elif com_texto < paginas:
            probs.append(_p("media", f"{paginas - com_texto} de {paginas} página(s) sem texto.", "Aplicar OCR nessas páginas."))
        else:
            bons.append("Todas as páginas têm texto.")
        if (doc.metadata or {}).get("title", "").strip():
            bons.append("Tem título.")
        else:
            probs.append(_p("media", "O PDF não tem título nas propriedades.", "Definir o título."))
        try:
            cat = doc.pdf_catalog()
            marcado = "true" in (doc.xref_get_key(cat, "MarkInfo")[1] or "").lower()
            idioma = doc.xref_get_key(cat, "Lang")[1] not in (None, "null")
        except Exception:  # noqa: BLE001
            marcado, idioma = False, False
        if not marcado:
            probs.append(_p("media", "O PDF não tem marcação de estrutura (PDF com tags): títulos e tabelas podem não ser reconhecidos.",
                            "Exportar de novo marcando 'PDF acessível' ou 'com tags'."))
        if not idioma:
            probs.append(_p("baixa", "O PDF não declara o idioma.", "Definir o idioma do documento."))
    finally:
        doc.close()
    return {"tipo": "PDF", "problemas": probs, "pontos_bons": bons, "conferiu": conferiu}


def verificar(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    ext = p.suffix.lower()
    fn = {".docx": _docx, ".xlsx": _xlsx, ".xlsm": _xlsx, ".pptx": _pptx, ".pdf": _pdf}.get(ext)
    if fn is None:
        raise ValueError("Formato não suportado. Use .docx, .xlsx, .pptx ou .pdf.")
    r = fn(str(p))
    probs = r["problemas"]
    graves = [x for x in probs if x["gravidade"] == "alta"]
    if not probs:
        falado = f"Conferi o {r['tipo']} {p.name} e não achei problemas de acessibilidade nos itens que verifico."
    else:
        falado = (f"Conferi o {r['tipo']} {p.name}: {len(probs)} ponto(s) a melhorar, {len(graves)} importante(s). "
                  + " ".join(x["problema"] for x in probs[:3]))
    return {
        "ok": True, "arquivo": p.name, "tipo": r["tipo"], "problemas": probs, "pontos_bons": r["pontos_bons"],
        "conferiu": r["conferiu"], "resumo_falado": falado,
        "aviso": "É uma conferência rápida e local dos itens listados em `conferiu`; não substitui uma auditoria completa nem um teste com leitor de tela.",
    }
