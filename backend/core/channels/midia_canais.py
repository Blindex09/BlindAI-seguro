"""Midia dos canais (Telegram/WhatsApp): entender o que a pessoa manda e devolver voz.

Entrada: audio/voz (transcricao local), foto (audiodescricao), video (quadro descrito + fala transcrita) e documentos
(PDF, planilha, apresentacao, Word e texto: trecho do conteudo). Todo arquivo fica em `data/canais/midia/`
e o caminho vai junto, para o Blind abrir o resto com as ferramentas de documentos.
Saida: sintetiza voz (SAPI -> ffmpeg/opus) para responder em audio.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Optional

DATA_DIR = Path(os.environ.get("BLIND_DATA_DIR") or (Path(__file__).resolve().parents[2] / "data"))
MIDIA_DIR = DATA_DIR / "canais" / "midia"
MAX_TRECHO = 4000
MAX_VOZ_CARACTERES = 1500
_TEXTO = {".txt", ".md", ".csv", ".json", ".log", ".xml", ".html", ".srt"}


def _nome_seguro(nome: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(nome or "arquivo").name).strip(" .") or "arquivo"
    return base[:120]


def novo_caminho(nome: str) -> Path:
    MIDIA_DIR.mkdir(parents=True, exist_ok=True)
    return MIDIA_DIR / f"{int(time.time())}-{_nome_seguro(nome)}"


async def baixar_telegram(file_id: str, nome_sugerido: str = "") -> Path:
    from core.channels.telegram_manager import telegram_manager

    raw, remoto = await telegram_manager.download_file_bytes(file_id)
    destino = novo_caminho(nome_sugerido or Path(remoto).name)
    destino.write_bytes(raw)
    return destino


def _docx_texto(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def _trecho_documento(path: Path) -> str:
    suf = path.suffix.lower()
    try:
        if suf in (".pdf", ".xlsx", ".xlsm", ".pptx"):
            from blind_mcp.servers.docs import _extract_pdf_sync

            r = _extract_pdf_sync(str(path), None, None)
            texto = (r.get("digital_text") or "").strip()
            if not texto and r.get("scanned_renders"):
                return "(PDF escaneado, sem texto digital: peca para eu ler com OCR)"
            return f"({r.get('total_pages')} paginas) {texto}"
        if suf == ".docx":
            return _docx_texto(str(path))
        if suf in _TEXTO:
            return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"(nao consegui ler o conteudo: {type(exc).__name__})"
    return ""


async def entender_arquivo(caminho: Path, tipo: str, legenda: str = "") -> str:
    """tipo: audio | imagem | video | documento. Devolve o texto que o Blind deve receber."""
    from blind_mcp.servers import channels as ch

    cab = f"[Arquivo recebido ({tipo}): {caminho.name}, guardado em {caminho}]"
    extra = ""
    try:
        if tipo == "audio":
            r = await asyncio.to_thread(ch._transcribe_file_sync, str(caminho), "pt")
            return f"[Mensagem de voz transcrita] {r.get('text') or '(sem fala reconhecida)'}"
        if tipo == "imagem":
            d = await ch.channel_describe_image(file_path=str(caminho))
            extra = f"Descricao da foto: {d.get('description', '')}"
        elif tipo == "video":
            partes = []
            quadro = await asyncio.to_thread(ch._video_frame, str(caminho))
            if quadro:
                d = await ch.channel_describe_image(file_path=quadro)
                partes.append(f"Quadro do video: {d.get('description', '')}")
            try:
                r = await asyncio.to_thread(ch._transcribe_file_sync, str(caminho), "pt")
                if r.get("text"):
                    partes.append(f"Fala no video: {r['text']}")
            except Exception:  # noqa: BLE001 - video sem audio
                pass
            extra = " ".join(partes) or "(nao consegui extrair imagem nem fala do video)"
        elif tipo == "documento":
            trecho = await asyncio.to_thread(_trecho_documento, caminho)
            if trecho:
                corte = trecho[:MAX_TRECHO]
                extra = f"Conteudo: {corte}" + (" [...cortado: use read_document para o resto]" if len(trecho) > MAX_TRECHO else "")
    except Exception as exc:  # noqa: BLE001
        extra = f"(nao consegui entender o arquivo: {type(exc).__name__})"
    return " ".join(x for x in (cab, legenda.strip(), extra) if x)


# ---------------------------------------------------------------------------------------------- voz de saida
def _limpar_para_voz(texto: str) -> str:
    t = re.sub(r"```[a-zA-Z]*\n?|`|\*{1,3}|^#{1,6}\s*", "", texto or "", flags=re.M)
    return re.sub(r"\s+", " ", t).strip()[:MAX_VOZ_CARACTERES] or "Pronto."


def _sapi_para_wav(texto: str, wav: str) -> None:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        voz = win32com.client.Dispatch("SAPI.SpVoice")
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Open(wav, 3)  # SSFMCreateForWrite
        voz.AudioOutputStream = stream
        voz.Speak(texto)
        stream.Close()
    finally:
        pythoncom.CoUninitialize()


def sintetizar_ogg(texto: str) -> Optional[Path]:
    """Texto -> mensagem de voz (.ogg opus). None se nao houver ffmpeg ou a sintese falhar."""
    ff = shutil.which("ffmpeg")
    if not ff:
        return None
    MIDIA_DIR.mkdir(parents=True, exist_ok=True)
    saida = MIDIA_DIR / f"resposta-{int(time.time() * 1000)}.ogg"
    with tempfile.TemporaryDirectory() as tmp:
        wav = str(Path(tmp) / "voz.wav")
        try:
            _sapi_para_wav(_limpar_para_voz(texto), wav)
            subprocess.run([ff, "-y", "-loglevel", "error", "-i", wav, "-c:a", "libopus", "-b:a", "32k", str(saida)],
                           check=True, timeout=60, capture_output=True)
        except Exception:  # noqa: BLE001
            return None
    return saida if saida.is_file() else None


def limpar_antigos(dias: int = 7) -> None:
    """Apaga midia de canais com mais de `dias` dias (so desta pasta)."""
    limite = time.time() - dias * 86400
    if MIDIA_DIR.is_dir():
        for f in MIDIA_DIR.iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < limite:
                    f.unlink()
            except OSError:
                pass
