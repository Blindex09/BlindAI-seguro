"""Servidor MCP: documentos acessiveis (PDF digital e escaneado com OCR/visao, formularios PDF),
escrita assistida, audiodescricao de imagens e leitura/busca limpa da web.

Integra capacidades adaptadas do Hermes Agent (web_tools / web_tools_extract) e
do Abacus AI Bot (pdf-ops: forms, fill, merge, split + seguranca de URL).
"""

from __future__ import annotations

import base64
import html
import ipaddress
import os
import re
import socket
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from mcp.server.fastmcp import FastMCP

from ._common import BACKEND_DIR, run_blocking

from config.settings import config  # noqa: E402
from core.vision.smart_vision_router import smart_vision_router  # noqa: E402
from core.writer.smart_writer import writer as smart_writer  # noqa: E402

mcp = FastMCP("blind-docs")

MAX_TEXT_CHARS = 20000
MAX_URL_CHARS = 4096
MAX_OCR_PAGES = 5
CONTINUE_PAGES = 3  # quantas paginas "continuar" le de cada vez

POSITIONS_FILE = Path(os.environ.get("BLIND_DATA_DIR") or (BACKEND_DIR / "data")) / "leitura_posicoes.json"


def _pos_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _load_positions() -> Dict[str, Any]:
    import json

    try:
        return json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_position(path: str, last_page: int, total: int) -> None:
    import json
    import time

    try:
        data = _load_positions()
        data[_pos_key(path)] = {"ultima_pagina_lida": last_page, "total_paginas": total, "quando": time.strftime("%Y-%m-%dT%H:%M:%S")}
        POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        POSITIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass  # guardar posicao nunca pode atrapalhar a leitura


def _parse_page_spec(spec: Optional[str], total: int) -> List[int]:
    """Converte especificacao '1-3,5' (base 1) em indices base 0 validos (adaptado de pdf-ops.ts do Abacus)."""
    if not spec or not spec.strip():
        return list(range(total))
    pages: List[int] = []
    for raw in spec.split(","):
        part = raw.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            lo, hi = int(start_s.strip()), int(end_s.strip())
        else:
            lo = hi = int(part)
        for p in range(lo, hi + 1):
            idx = p - 1
            if 0 <= idx < total and idx not in pages:
                pages.append(idx)
    return pages


def _extract_pdf_sync(
    path: Optional[str],
    b64: Optional[str],
    pages_spec: Optional[str] = None,
) -> Dict[str, Any]:
    import pymupdf

    filename = "documento.pdf"
    if path and os.path.exists(path) and Path(path).suffix.lower() in (".xlsx", ".xlsm", ".pptx"):
        # Planilha/apresentacao: cada aba ou slide conta como uma "pagina", com cabecalhos e nomes (nao so valores soltos).
        from core.writer import office_io

        unidades = office_io.ler_pptx(path) if path.lower().endswith(".pptx") else office_io.ler_xlsx(path)
        indices = _parse_page_spec(pages_spec, len(unidades))
        return {
            "filename": Path(path).name,
            "total_pages": len(unidades),
            "digital_text": "\n\n".join(f"--- Pagina {i + 1} ---\n{unidades[i][1]}" for i in indices).strip(),
            "scanned_renders": [],
        }
    if b64:
        raw = b64.split(",")[-1]
        doc = pymupdf.open(stream=base64.b64decode(raw), filetype="pdf")
    elif path and os.path.exists(path):
        filename = Path(path).name
        doc = pymupdf.open(path)
    else:
        raise FileNotFoundError("Arquivo nao encontrado e nenhum conteudo base64 informado.")

    try:
        total_pages = len(doc)
        indices = _parse_page_spec(pages_spec, total_pages)
        page_texts: List[str] = []
        scanned_renders: List[tuple[int, str]] = []

        for idx in indices:
            page = doc[idx]
            txt = (page.get_text() or "").strip()
            if txt:
                page_texts.append(f"--- Pagina {idx + 1} ---\n{txt}")
            elif len(scanned_renders) < MAX_OCR_PAGES:
                pix = page.get_pixmap(dpi=150)
                png_b64 = base64.b64encode(pix.tobytes("png")).decode("ascii")
                scanned_renders.append((idx + 1, png_b64))

        return {
            "filename": filename,
            "total_pages": total_pages,
            "digital_text": "\n\n".join(page_texts).strip(),
            "scanned_renders": scanned_renders,
        }
    finally:
        doc.close()


def _resolve_vision_key(api_key: Optional[str] = None) -> str:
    return (
        api_key
        or getattr(config, "gemini_api_key", "")
        or os.getenv("GEMINI_API_KEY", "")
        or getattr(config, "openai_api_key", "")
        or os.getenv("OPENAI_API_KEY", "")
    )


@mcp.tool()
async def read_document(
    file_path: Optional[str] = None,
    file_base64: Optional[str] = None,
    pages: Optional[str] = None,
    ocr_scanned: bool = True,
    continuar: bool = False,
) -> Dict[str, Any]:
    """Extrai o texto de um PDF (por caminho ou base64, opcionalmente filtrando paginas ex: '1-3,5').
    Se o PDF for digitalizado como imagem (sem texto selecionavel) e ocr_scanned=True, renderiza as
    paginas e executa OCR/audiodescricao automatica via modelo de visao.
    O Blind guarda ate onde voce leu cada arquivo (`ultima_pagina_lida`). Com continuar=true le as proximas 3 paginas depois
    dessa posicao ("continua de onde parou"). Veja document_outline para pular por titulo."""
    retomada: Optional[int] = None
    if continuar and file_path and not (pages or "").strip():
        saved = _load_positions().get(_pos_key(file_path))
        retomada = int(saved["ultima_pagina_lida"]) if saved else 0
        total_known = int(saved["total_paginas"]) if saved else 0
        if saved and total_known and retomada >= total_known:
            return {"filename": Path(file_path).name, "total_pages": total_known, "text": "", "fim_do_documento": True,
                    "note": "Voce ja leu ate a ultima pagina. Use pages='1-3' para reler do comeco."}
        pages = f"{retomada + 1}-{retomada + CONTINUE_PAGES}"
    extracted = await run_blocking(_extract_pdf_sync, file_path, file_base64, pages)
    filename = extracted["filename"]
    text = extracted["digital_text"]
    scanned_renders: List[tuple[int, str]] = extracted["scanned_renders"]

    ocr_pages_read = 0
    if not text and ocr_scanned and scanned_renders:
        ocr_parts: List[str] = []
        api_key = _resolve_vision_key()
        for page_num, png_b64 in scanned_renders:
            try:
                desc = await smart_vision_router.describe_multimodal(
                    image_base64=png_b64,
                    provider="auto",
                    api_key=api_key,
                    prompt_override=(
                        f"Este e um documento PDF escaneado (pagina {page_num}). "
                        "Transcreva fielmente todo o texto visivel, valores, datas e tabelas em portugues "
                        "para leitura por sintetizador de voz (NVDA/JAWS), sem omitir dados."
                    ),
                )
                if desc and desc.strip():
                    ocr_parts.append(f"--- Pagina {page_num} (OCR/Visao) ---\n{desc.strip()}")
                    ocr_pages_read += 1
            except Exception as exc:
                ocr_parts.append(f"--- Pagina {page_num} (falha no OCR: {exc}) ---")
        text = "\n\n".join(ocr_parts).strip()

    if not text:
        return {
            "filename": filename,
            "total_pages": extracted["total_pages"],
            "total_words": 0,
            "text": "",
            "scanned": bool(scanned_renders),
            "note": "O arquivo nao tem texto digital legivel; pode ser imagem digitalizada.",
        }

    shown = text[:MAX_TEXT_CHARS]
    result: Dict[str, Any] = {
        "filename": filename,
        "total_pages": extracted["total_pages"],
        "total_words": len(text.split()),
        "ocr_pages_read": ocr_pages_read,
        "text": shown,
        "truncated": len(text) > MAX_TEXT_CHARS,
    }
    nums = [int(n) for n in re.findall(r"--- Pagina (\d+)", shown)]
    if nums and file_path:
        # Se o texto foi cortado no meio de uma pagina, ela nao conta como lida.
        last = max(nums) - 1 if result["truncated"] and len(nums) > 1 else max(nums)
        await run_blocking(_save_position, file_path, last, extracted["total_pages"])
        result["ultima_pagina_lida"] = last
        result["para_continuar"] = "Chame read_document com continuar=true para as proximas paginas."
    if retomada is not None:
        result["retomado_depois_da_pagina"] = retomada
    return result


def _outline_sync(file_path: str) -> Dict[str, Any]:
    import pymupdf

    if not file_path or not os.path.exists(file_path):
        raise FileNotFoundError("Arquivo nao encontrado.")
    doc = pymupdf.open(file_path)
    try:
        total = len(doc)
        toc = doc.get_toc()  # [nivel, titulo, pagina]
        if toc:
            itens = [{"nivel": lvl, "titulo": (title or "").strip(), "pagina": page} for lvl, title, page in toc[:200]]
            origem = "indice do proprio PDF"
        else:
            itens = []
            for i in range(min(total, 60)):
                first = next((ln.strip() for ln in (doc[i].get_text() or "").splitlines() if ln.strip()), "")
                itens.append({"nivel": 1, "titulo": first[:90] or "(pagina sem texto digital)", "pagina": i + 1})
            origem = "primeira linha de cada pagina (o PDF nao tem indice)"
        saved = _load_positions().get(_pos_key(file_path))
        return {"ok": True, "filename": Path(file_path).name, "total_paginas": total, "origem": origem, "itens": itens,
                "posicao_guardada": saved or None}
    finally:
        doc.close()


@mcp.tool()
async def document_outline(file_path: str) -> Dict[str, Any]:
    """Mostra o sumario de um PDF (titulos e paginas) e ate onde a pessoa ja leu. Use para pular direto a uma parte:
    depois chame read_document com pages='12-14'."""
    return await run_blocking(_outline_sync, file_path)


def _pdf_forms_sync(file_path: str) -> Dict[str, Any]:
    import pymupdf

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Arquivo PDF nao encontrado: {file_path}")
    doc = pymupdf.open(file_path)
    try:
        fields: List[Dict[str, Any]] = []
        for idx, page in enumerate(doc):
            for widget in page.widgets() or []:
                fields.append(
                    {
                        "page": idx + 1,
                        "name": widget.field_name or "",
                        "label": widget.field_label or widget.field_name or "",
                        "type": widget.field_type_string or str(widget.field_type),
                        "value": widget.field_value,
                        "choices": list(widget.choice_values) if widget.choice_values else [],
                    }
                )
        return {
            "ok": True,
            "file_path": file_path,
            "count": len(fields),
            "fields": fields,
        }
    finally:
        doc.close()


@mcp.tool()
async def pdf_forms(file_path: str) -> Dict[str, Any]:
    """Lista todos os campos de formulario preenchiveis de um PDF (nome, rotulo, tipo, valor atual e pagina)."""
    return await run_blocking(_pdf_forms_sync, file_path)


def _pdf_fill_sync(file_path: str, output_path: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    from blind_mcp import seguranca

    seguranca.conferir_gravacao_blind_docs(output_path)
    import pymupdf

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Arquivo PDF nao encontrado: {file_path}")
    doc = pymupdf.open(file_path)
    try:
        filled: List[str] = []
        available: set[str] = set()
        for page in doc:
            for widget in page.widgets() or []:
                fname = widget.field_name or ""
                available.add(fname)
                if fname in fields:
                    val = fields[fname]
                    if widget.field_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
                        widget.field_value = bool(val and str(val).lower() not in ("false", "0", "no", "off", "nao", "não"))
                    else:
                        widget.field_value = str(val)
                    widget.update()
                    filled.append(fname)
        missing = [k for k in fields if k not in available]
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out))
        return {
            "ok": True,
            "output_path": str(out),
            "filled": filled,
            "missing": missing,
        }
    finally:
        doc.close()


@mcp.tool()
async def pdf_fill(file_path: str, output_path: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Preenche os campos de um formulario PDF (fields = {'nome_do_campo': 'valor'}) e salva em output_path."""
    return await run_blocking(_pdf_fill_sync, file_path, output_path, fields)


def _pdf_merge_split_sync(
    action: str,
    output_path: str,
    input_paths: List[str],
    pages: Optional[str] = None,
) -> Dict[str, Any]:
    import pymupdf

    act = (action or "").strip().lower()
    if act not in ("merge", "split"):
        raise ValueError("action deve ser 'merge' (juntar PDFs) ou 'split' (extrair paginas de um PDF).")
    if not input_paths:
        raise ValueError("Informe ao menos um caminho em input_paths.")

    from blind_mcp import seguranca

    seguranca.conferir_gravacao_blind_docs(output_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    result_doc = pymupdf.open()
    try:
        if act == "merge":
            for p in input_paths:
                if not os.path.isfile(p):
                    raise FileNotFoundError(f"Arquivo nao encontrado: {p}")
                with pymupdf.open(p) as src:
                    result_doc.insert_pdf(src)
        else:
            src_path = input_paths[0]
            if not os.path.isfile(src_path):
                raise FileNotFoundError(f"Arquivo nao encontrado: {src_path}")
            with pymupdf.open(src_path) as src:
                indices = _parse_page_spec(pages, len(src))
                for idx in indices:
                    result_doc.insert_pdf(src, from_page=idx, to_page=idx)
        result_doc.save(str(out))
        return {"ok": True, "action": act, "output_path": str(out), "pages": len(result_doc)}
    finally:
        result_doc.close()


@mcp.tool()
async def pdf_merge_split(
    action: str,
    output_path: str,
    input_paths: List[str],
    pages: Optional[str] = None,
) -> Dict[str, Any]:
    """Junta varios PDFs ('merge') ou extrai um intervalo de paginas ('split', ex: pages='1-3,5') em um novo PDF."""
    return await run_blocking(_pdf_merge_split_sync, action, output_path, input_paths, pages)


def _validate_safe_public_url(raw_url: str) -> str:
    """Defesa de URL adaptada de Abacus (tools_url_safety) e Hermes (url_safety):
    bloqueia credenciais embutidas, esquemas nao-HTTP e enderecos privados/loopback (SSRF)."""
    url = (raw_url or "").strip()
    if not url:
        raise ValueError("URL vazia.")
    if len(url) > MAX_URL_CHARS:
        raise ValueError("URL longa demais.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Apenas URLs http:// ou https:// sao permitidas.")
    if parsed.username or parsed.password:
        raise ValueError("URLs com usuario/senha embutidos nao sao permitidas.")
    host = (parsed.hostname or "").strip().lower()
    if not host or host in ("localhost", "0.0.0.0") or host.endswith(".local"):
        raise ValueError("Acesso a enderecos locais/internos nao e permitido.")
    try:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            ip_str = info[4][0]
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
            ):
                raise ValueError(f"Endereco privado/interno bloqueado por seguranca: {host}")
    except socket.gaierror:
        pass
    return url


_SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe", "nav", "footer", "aside", "header", "form", "template",
              "button", "select", "dialog", "head"}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_SKIP_CLASS = re.compile(
    r"(?:^|\s)(?:navbox|infobox|sidebar|metadata|noprint|mw-editsection|reference|reflist|toc|hatnote|"
    r"mw-empty-elt|cookie|cookies|consent|banner|advert|ads|popup|modal|breadcrumb|share|social|newsletter|"
    r"catlinks|printfooter|mw-jump-link|vector-toc|vector-header|vector-page-toolbar|vector-column-start|"
    r"vector-sticky-header)(?:$|\s)",
    re.I,
)
_MAIN_IDS = {"mw-content-text", "bodycontent", "content-main", "main-content", "maincontent", "article-body"}
_BLOCK_TAGS = {"p", "div", "section", "article", "main", "br", "tr", "ul", "ol", "table", "blockquote", "figure", "dd", "dt"}


class _TextExtractor(HTMLParser):
    """Extrai o texto legivel. Ignora menus, rodapes, ocultos e caixas laterais; prefere o miolo da pagina."""

    def __init__(self, main_only: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.main_only = main_only
        self.parts: List[str] = []
        self.title = ""
        self._in_title = False
        self._stack: List[tuple] = []  # (tag, skip, main)
        self._skip = 0
        self._main = 0

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        if tag in _VOID_TAGS:
            if tag == "br" and not self._skip:
                self.parts.append("\n")
            return
        style = a.get("style", "").replace(" ", "").lower()
        skip = (
            tag in _SKIP_TAGS
            or "hidden" in a
            or a.get("aria-hidden", "").lower() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
            or (tag not in {"html", "body"} and bool(_SKIP_CLASS.search(a.get("class", ""))))
            or a.get("role", "").lower() in {"navigation", "banner", "contentinfo", "complementary", "search"}
        )
        is_main = tag in {"main", "article"} or a.get("role", "").lower() == "main" or a.get("id", "").lower() in _MAIN_IDS
        self._stack.append((tag, skip, is_main))
        self._skip += int(skip)
        self._main += int(is_main)
        if self._skip or (self.main_only and not self._main):
            return
        if tag in {"h1", "h2", "h3", "h4"}:
            self.parts.append("\n\n" + "#" * min(int(tag[1]), 3) + " ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in _VOID_TAGS:
            return
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                for _t, skip, is_main in self._stack[i:]:
                    self._skip -= int(skip)
                    self._main -= int(is_main)
                del self._stack[i:]
                break
        if tag in {"h1", "h2", "h3", "h4", "p", "tr"} and not self._skip:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._skip or (self.main_only and not self._main):
            return
        self.parts.append(data)


def _extract_text(raw_html: str, main_only: bool) -> tuple[str, str]:
    parser = _TextExtractor(main_only)
    parser.feed(raw_html)
    parser.close()
    lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in "".join(parser.parts).splitlines()]
    text = "\n".join(ln for ln in lines if ln)
    return html.unescape(re.sub(r"\s+", " ", parser.title)).strip(), text


def _html_to_clean_accessible_text(raw_html: str) -> tuple[str, str]:
    """Converte HTML em texto limpo para leitor de tela: so o miolo da pagina quando existe, sem menus, rodape,
    ocultos, caixas laterais, referencias nem listas de idiomas."""
    title, text = _extract_text(raw_html, main_only=True)
    if len(text) < 300:  # pagina sem <main>/<article>: usa o corpo inteiro, ainda filtrado
        title2, text2 = _extract_text(raw_html, main_only=False)
        title, text = title or title2, text2 if len(text2) > len(text) else text
    return title, text


_SEARCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


def _clean_html(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def _bing_real_url(href: str) -> str:
    """O Bing envolve o link real em /ck/a?...&u=a1<base64url>. Devolve o destino real."""
    href = html.unescape(href)
    if "bing.com/ck/a" in href:
        token = parse_qs(urlparse(href).query).get("u", [""])[0]
        if token.startswith("a1"):
            raw = token[2:]
            try:
                return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
            except Exception:  # noqa: BLE001
                return href
    return href


def _parse_bing(body: str, limit: int) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    for block in re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', body, flags=re.I | re.S):
        h2 = re.search(r"<h2[^>]*>\s*<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", block, re.I | re.S)
        if not h2:
            continue
        snip = re.search(r'<div class="b_caption"[^>]*>.*?<p[^>]*>(.*?)</p>', block, re.I | re.S)
        results.append(
            {
                "title": _clean_html(h2.group(2)),
                "url": _bing_real_url(h2.group(1)),
                "snippet": _clean_html(snip.group(1)) if snip else "",
            }
        )
        if len(results) >= limit:
            break
    return results


def _parse_duckduckgo(body: str, limit: int) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    blocks = re.findall(
        r'<div[^>]+class="[^"]*result__body[^"]*"[^>]*>(.*?)</div>\s*</div>', body, flags=re.I | re.S
    )
    for block in blocks:
        a_m = re.search(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.I | re.S)
        if not a_m:
            continue
        raw_href = a_m.group(1)
        if "uddg=" in raw_href:
            raw_href = unquote(parse_qs(urlparse(raw_href).query).get("uddg", [raw_href])[0])
        snip_m = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|div|span)>', block, re.I | re.S)
        results.append(
            {
                "title": _clean_html(a_m.group(2)),
                "url": raw_href,
                "snippet": _clean_html(snip_m.group(1)) if snip_m else "",
            }
        )
        if len(results) >= limit:
            break
    return results


def _parse_yahoo(body: str, limit: int) -> List[Dict[str, str]]:
    """Yahoo Brasil: resultados organicos (div.algo-sr). O link real fica em RU=<url codificada> no redirecionador."""
    out: List[Dict[str, str]] = []
    for block in re.split(r'<div class="[^"]*algo-sr[^"]*"', body)[1:]:
        h3 = re.search(r'<h3[^>]*class="title"[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*aria-label="([^"]*)"', block, flags=re.S)
        if not h3:
            continue
        href = html.unescape(h3.group(1))
        ru = re.search(r"/RU=([^/]+)/R[KS]=", href)
        url = unquote(ru.group(1)) if ru else href
        if not url.startswith("http"):
            continue
        snip = re.search(r'<div class="compText[^"]*"[^>]*>(.*?)</div>', block, flags=re.S)
        out.append({"title": _clean_html(h3.group(2)), "url": url, "snippet": _clean_html(snip.group(1)) if snip else ""})
        if len(out) >= limit:
            break
    return out


def _fold(text: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", (text or "").lower()) if unicodedata.category(c) != "Mn")


_STOP = {"que", "como", "para", "uma", "uns", "com", "por", "das", "dos", "nao", "hoje", "agora", "qual", "quais", "the", "and"}


def _relevant(results: List[Dict[str, str]], query: str) -> bool:
    """Os buscadores devolvem lixo aleatorio a clientes automatizados. Exige que a maioria dos resultados mencione
    ao menos uma palavra da consulta (sem acento) no titulo, link ou resumo."""
    words = [w for w in re.findall(r"[a-z0-9]+", _fold(query)) if len(w) > 3 and w not in _STOP]
    if not words or not results:
        return bool(results)
    hits = sum(1 for r in results if any(w in _fold(f"{r.get('title','')} {r.get('url','')} {r.get('snippet','')}") for w in words))
    return hits * 2 >= len(results)


@mcp.tool()
async def web_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Pesquisa na web e devolve resultados limpos (titulo, link e resumo) sem anuncios ou poluicao visual."""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "Informe uma consulta de busca."}
    from blind_mcp import cofre

    if cofre.detectar(q):
        return {"ok": False, "error": "A busca parece conter dado sensível (senha, chave, cartão ou CPF). Não enviei: "
                                      "buscadores guardam o que se pesquisa. Tire o dado da busca."}
    limit = max(1, min(int(max_results or 5), 10))
    errors: List[str] = []
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=_SEARCH_HEADERS) as client:
        # O DuckDuckGo responde 202 (anti-bot) e o Bing devolve resultados aleatorios a clientes automatizados:
        # o Yahoo Brasil e a fonte principal; Bing e DuckDuckGo ficam como reserva.
        for engine, fetch, parse in (
            (
                "yahoo",
                lambda: client.get("https://br.search.yahoo.com/search", params={"p": q, "ei": "UTF-8"}),
                _parse_yahoo,
            ),
            (
                "bing",
                lambda: client.get("https://www.bing.com/search", params={"q": q, "setlang": "pt-BR"}),
                _parse_bing,
            ),
            (
                "duckduckgo",
                lambda: client.get("https://html.duckduckgo.com/html/", params={"q": q}),
                _parse_duckduckgo,
            ),
        ):
            try:
                resp = await fetch()
                results = parse(resp.text, limit)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{engine}: {exc}")
                continue
            if results and not _relevant(results, q):
                errors.append(f"{engine}: resultados sem relacao com a busca")
                continue
            if results:
                return {"ok": True, "engine": engine, "query": q, "count": len(results), "results": results}
            errors.append(f"{engine}: sem resultados (HTTP {resp.status_code})")
    return {
        "ok": False,
        "query": q,
        "count": 0,
        "results": [],
        "error": "Nenhum buscador devolveu resultados. " + "; ".join(errors),
    }


@mcp.tool()
async def web_read(url: str, max_chars: int = 15000) -> Dict[str, Any]:
    """Abre uma pagina web e extrai apenas o texto principal e os titulos, sem banners, menus ou anuncios,
    ideal para leitura direta por pessoas cegas."""
    safe_url = await run_blocking(_validate_safe_public_url, url)
    cap = max(500, min(int(max_chars or 15000), MAX_TEXT_CHARS))
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
        resp = await client.get(safe_url)
        # Valida tambem o destino final apos redirects contra SSRF
        await run_blocking(_validate_safe_public_url, str(resp.url))
        ctype = (resp.headers.get("content-type") or "").lower()
        if "application/pdf" in ctype:
            b64_pdf = base64.b64encode(resp.content).decode("ascii")
            doc_res = await read_document(file_base64=b64_pdf, ocr_scanned=True)
            return {"ok": True, "url": str(resp.url), "title": doc_res.get("filename", "PDF"), "content": doc_res.get("text", "")}
        raw_html = resp.text

    title, content = _html_to_clean_accessible_text(raw_html)
    return {
        "ok": True,
        "url": safe_url,
        "title": title,
        "content": content[:cap],
        "truncated": len(content) > cap,
    }


@mcp.tool()
async def describe_image(
    file_path: Optional[str] = None,
    image_base64: Optional[str] = None,
    prompt: Optional[str] = None,
    provider: str = "auto",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> str:
    """Gera audiodescricao acessivel de uma imagem com um modelo multimodal (roteado por capacidade de visao). Se voltar que
    nenhum modelo de visao respondeu, use ver_imagem: ela entrega a imagem ao modelo da conversa para descrever."""
    resolved_key = _resolve_vision_key(api_key)
    return await smart_vision_router.describe_multimodal(
        image_base64=image_base64,
        file_path=file_path,
        provider=provider,
        requested_model=model,
        api_key=resolved_key,
        prompt_override=prompt,
    )


@mcp.tool(structured_output=False)
async def ver_imagem(file_path: str, pergunta: Optional[str] = None) -> List[Any]:
    """Entrega uma imagem (foto, captura, anexo) ao modelo de IA da conversa para ELE descrever, sem depender de chave de visao.
    Use quando describe_image falhar (sem modelo de visao) ou quando o proprio Claude estiver conversando. A imagem e reduzida
    (maximo 1568 px) e segue para o modelo da conversa: a mesma nuvem que a pessoa ja usa. Depois de ver, descreva seguindo a
    habilidade descrevendo-imagens. Se a imagem tiver dado sensivel (remedio, conta, documento), leia com falar_em_segredo."""
    import io

    from mcp.server.fastmcp import Image
    from mcp.types import TextContent
    from PIL import Image as PILImage

    p = Path(file_path).expanduser()
    if not p.is_file():
        raise ValueError("Não achei esse arquivo de imagem.")
    if p.stat().st_size > 30 * 1024 * 1024:
        raise ValueError("A imagem é grande demais (mais de 30 MB).")

    def _preparar() -> bytes:
        with PILImage.open(p) as im:
            im = im.convert("RGB")
            im.thumbnail((1568, 1568))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=85)
            return buf.getvalue()

    try:
        dados = await run_blocking(_preparar)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Não consegui abrir como imagem: {type(e).__name__}.") from e
    nota = ("Imagem entregue para você descrever para uma pessoa cega, com a habilidade descrevendo-imagens. "
            + (f"Pergunta da pessoa: {pergunta}" if pergunta else "Sem pergunta específica: faça a descrição na ordem da habilidade.")
            + " Diga que a descrição é sua e pode errar; não identifique ninguém pelo rosto.")
    return [TextContent(type="text", text=nota), Image(data=dados, format="jpeg").to_image_content()]


@mcp.tool()
async def documento_acessibilidade(file_path: str) -> Dict[str, Any]:
    """Confere a acessibilidade de um documento (.docx, .xlsx, .pptx ou .pdf) para leitor de tela: titulo do arquivo, titulos
    de secao ou slide, texto alternativo de imagens, cabecalho de planilha, linhas vazias, celulas mescladas, texto real no PDF.
    Devolve `problemas` com como corrigir e `resumo_falado`. E uma conferencia rapida e local; diga o que ela conferiu (`conferiu`).
    Use depois de criar um documento ou quando a pessoa perguntar se um arquivo e acessivel."""
    from core.writer import acessibilidade_docs

    return await run_blocking(acessibilidade_docs.verificar, file_path)


@mcp.tool()
async def writer_draft(title: str, content: str, filename: Optional[str] = None) -> Dict[str, Any]:
    """Prepara a minuta de um documento com revisao falada. Nada e gravado ate writer_save. O formato vem da extensao do
    `filename`: .docx (Word), .xlsx (planilha), .pptx (apresentacao), .pdf, .txt ou .md. Como escrever o `content`:
    xlsx = uma linha por linha da planilha, celulas separadas por ';' (1a linha = cabecalho, '## Nome' = nova aba; formulas
    como =SUM(B2:B3)); pptx = slides separados por linha em branco (1a linha = titulo, o resto = topicos); docx/pdf =
    paragrafos separados por linha em branco ('# ' = titulo no pdf)."""
    return await run_blocking(smart_writer.draft_document, title, content, filename)


@mcp.tool()
async def writer_save(draft: Dict[str, Any]) -> Dict[str, Any]:
    """Grava no disco a minuta aprovada pelo usuario, de forma segura e atomica."""
    return await run_blocking(smart_writer.save_document, draft)


if __name__ == "__main__":
    from . import _audit

    _audit.install_audit(mcp, "blind-docs")
    mcp.run()
