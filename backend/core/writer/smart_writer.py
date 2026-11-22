"""
Smart Writer Acessível - Blind AI
Permite a pessoas com deficiência visual ditar, redigir textos/notas/cartas,
ouvir a confirmação falada e salvar os arquivos no disco com gravação atômica, backup automático e segurança.
Clonado e enriquecido a partir dos módulos de escrita do Hermes Agent (file_tools.py e file_operations.py).
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("blind.writer")


def _documents_dir() -> Path:
    """Pasta Documentos do usuario (respeita redirecionamento para o OneDrive); cai em ~/Documents."""
    try:
        import ctypes
        import uuid

        folder_id = (ctypes.c_ubyte * 16)(*uuid.UUID("FDD39AD0-238F-46AF-ADB4-6C85480369C7").bytes_le)  # FOLDERID_Documents
        buf = ctypes.c_wchar_p()
        shell32 = ctypes.windll.shell32
        if shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(buf)) == 0 and buf.value:
            path = Path(buf.value)
            ctypes.windll.ole32.CoTaskMemFree(buf)
            return path
    except Exception:  # noqa: BLE001
        pass
    return Path.home() / "Documents"


class SmartWriter:
    """Gerencia a criação e edição de arquivos guiada por voz e acessibilidade com segurança atômica."""

    def __init__(self, workspace_dir: Optional[Path] = None):
        # Nunca o diretorio de trabalho do processo: um servidor MCP pode nascer em C:\Windows\System32.
        self.workspace_dir = Path(workspace_dir or os.environ.get("BLIND_DOCS_DIR") or _documents_dir())

    def draft_document(
        self,
        title: str,
        content: str,
        filename: Optional[str] = None,
        doc_format: str = "txt",
    ) -> Dict[str, Any]:
        """
        Prepara a minuta do documento e gera a confirmação falada para revisão do usuário cego.
        Calcula estatísticas de palavras, parágrafos e tempo estimado de leitura.
        """
        extension = doc_format.strip(".").lower() if doc_format else "txt"
        if filename:
            filename = Path(filename).name  # so o nome: nunca sai da pasta de documentos
            suffix = Path(filename).suffix.lstrip(".").lower()
            if suffix in ("docx", "txt", "md", "xlsx", "pptx", "pdf"):
                extension = suffix  # "carta.docx" pede um Word de verdade
        if not filename:
            clean_title = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in title.lower())
            safe_filename = f"{clean_title.strip('_')}.{extension}"
        else:
            safe_filename = filename if filename.endswith(f".{extension}") else f"{filename}.{extension}"

        target_path = self.workspace_dir / safe_filename
        from blind_mcp import seguranca

        seguranca.conferir_gravacao_blind_docs(target_path)  # avisa ja na minuta, antes de a pessoa aprovar

        words = content.split()
        word_count = len(words)
        paragraphs = [p for p in content.split("\n\n") if p.strip()]
        para_count = len(paragraphs) or 1
        est_read_minutes = max(1, round(word_count / 130))  # Média de fala/leitura de 130 ppm

        preview_snip = content[:180].strip().replace("\n", " ")

        spoken_review = (
            f"Documento redigido: '{title}'. "
            f"Formato: {extension.upper()}. "
            f"Total de {word_count} palavras em {para_count} parágrafos. "
            f"Início do texto: {preview_snip}... "
            f"Deseja confirmar a gravação no arquivo {safe_filename}?"
        )

        return {
            "title": title,
            "filename": safe_filename,
            "target_path": str(target_path),
            "content": content,
            "format": extension,
            "word_count": word_count,
            "paragraph_count": para_count,
            "estimated_read_minutes": est_read_minutes,
            "spoken_review": spoken_review,
            "ready_to_save": True,
        }

    def save_document(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        """
        Salva o documento no disco de forma 100% segura e atômica:
        1. Cria backup .bak se o arquivo já existir.
        2. Grava em arquivo temporário no mesmo volume de disco.
        3. Executa os.replace (rename atômico) para garantir que o arquivo nunca fique corrompido ou incompleto.
        """
        from blind_mcp import seguranca

        seguranca.conferir_gravacao_blind_docs(draft["target_path"])  # so Downloads, Documentos, Musicas e Videos
        target_path = Path(draft["target_path"])
        target_path.parent.mkdir(parents=True, exist_ok=True)

        backup_created = None
        if target_path.exists():
            backup_path = target_path.with_suffix(f"{target_path.suffix}.bak")
            shutil.copy2(target_path, backup_path)
            backup_created = str(backup_path)
            logger.info(f"Backup automático criado em {backup_path}")

        # Escrita atômica via arquivo temporário no mesmo diretório
        temp_fd, temp_path_str = tempfile.mkstemp(
            dir=str(target_path.parent),
            prefix="blind_wr_",
            suffix=".tmp" + target_path.suffix,
        )
        try:
            ext = target_path.suffix.lower()
            if ext in (".xlsx", ".pptx", ".pdf"):
                os.close(temp_fd)
                from . import office_io

                {".xlsx": office_io.escrever_xlsx, ".pptx": office_io.escrever_pptx, ".pdf": office_io.escrever_pdf}[ext](
                    temp_path_str, str(draft.get("title") or ""), str(draft["content"]))
                if ext == ".xlsx":
                    office_io.recalcular_xlsx(temp_path_str)  # com LibreOffice, as formulas ja saem com valor (senao, so no Excel)
            elif ext == ".docx":
                os.close(temp_fd)
                from docx import Document

                doc = Document()
                doc.core_properties.title = str(draft.get("title") or "")
                from docx.oxml import OxmlElement
                from docx.oxml.ns import qn

                rpr = doc.styles["Normal"].element.get_or_add_rPr()  # idioma do documento: leitores de tela escolhem a voz por ele
                lang = rpr.find(qn("w:lang"))
                if lang is None:
                    lang = OxmlElement("w:lang")
                    rpr.append(lang)
                lang.set(qn("w:val"), "pt-BR")
                if draft.get("title"):
                    doc.add_heading(str(draft["title"]), level=1)
                for par in str(draft["content"]).split("\n\n"):
                    if par.strip():
                        doc.add_paragraph(par.strip())
                doc.save(temp_path_str)
            else:
                with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                    f.write(draft["content"])
                    f.flush()
                    os.fsync(f.fileno())

            # Substituição atômica
            os.replace(temp_path_str, target_path)
            logger.info(f"Documento salvo atomicamente em {target_path}")
        except Exception:
            if os.path.exists(temp_path_str):
                try:
                    os.unlink(temp_path_str)
                except OSError:
                    pass
            raise

        confirmation_speech = (
            f"Arquivo {draft['filename']} salvo com sucesso. "
            f"{'Backup do anterior preservado. ' if backup_created else ''}"
            f"Tamanho gravado: {len(draft['content'])} caracteres."
        )

        return {
            "status": "success",
            "path": str(target_path),
            "size_bytes": target_path.stat().st_size,
            "backup_path": backup_created,
            "confirmation_speech": confirmation_speech,
        }


writer = SmartWriter()
