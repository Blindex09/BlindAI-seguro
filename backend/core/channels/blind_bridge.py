"""Canais do Blind: a pessoa conversa com o Blind pelo Telegram (bot) e pelo WhatsApp (conversa "voce mesmo").

Regras de seguranca:
- So o DONO e atendido. Telegram: o chat vinculado com o codigo (`/vincular CODIGO`, vale 10 min, uso unico, gerado no
  computador). WhatsApp: so a conversa da pessoa consigo mesma (o conector ignora o resto e so envia midia para ela).
- Qualquer outro remetente e ignorado em silencio (so vai para o log).
- Mensagem a terceiros so sai com o "sim" da pessoa (as ferramentas ja exigem as duas etapas).
- Um dono por vez (trava `canais-blind`): Claude e Electron juntos nao respondem duas vezes.

Cerebro: por padrao o CLAUDE. O pedido entra numa fila (`canal_fila.json`) e a sessao trancada do Claude (pasta `canal-claude/`:
so ferramentas do Blind + Calendar/Drive/Gmail) responde com `canal_responder`. Se a sessao nao esta viva (batimento em
`canal_claude_vivo.json`) ou nao pega o pedido a tempo, o modelo local do backend responde (reserva). Entrada de midia:
voz, foto, video e documentos sao entendidos antes (core.channels.midia_canais). Saida: texto, voz (se a pessoa mandou voz) e arquivos.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("blind.canais")

DATA_DIR = Path(os.environ.get("BLIND_DATA_DIR") or (Path(__file__).resolve().parents[2] / "data"))
CONFIG = DATA_DIR / "canais_blind.json"
CODIGO = DATA_DIR / "canais_codigo.json"
FILA = DATA_DIR / "google_fila.json"  # nome historico: hoje guarda pedidos de canal e de Google
VIVO = DATA_DIR / "canal_claude_vivo.json"
CODIGO_TTL = 600.0
MAX_ANTIGA_S = 600  # nao responde mensagem com mais de 10 min (ex.: acumulada com o app fechado)
LIMITE_TELEGRAM = 3900
VIVO_TTL = 20.0  # batimento da sessao do Claude: mais velho que isso = sessao fora
ESPERA_PEGAR_S = 45.0  # a sessao tem esse tempo para pegar o pedido; depois responde o modelo local
ESPERA_RESPONDER_S = 300.0

Chat = Callable[[str, str], Awaitable[str]]  # (session_key, texto) -> resposta


# ----------------------------------------------------------------------------- arquivos
def _ler(path: Path, padrao: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return padrao


def _gravar(path: Path, data: Any) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


@contextlib.contextmanager
def _trava_fila():
    """Trava simples entre processos (backend e servidor MCP mexem na mesma fila)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock = FILA.with_suffix(".lock")
    fim = time.time() + 5
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 10:  # trava velha de processo morto
                    lock.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.time() > fim:
                break  # segue sem a trava em vez de travar o canal
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def config() -> Dict[str, Any]:
    cfg = _ler(CONFIG, {})
    cfg.setdefault("ativo", True)
    cfg.setdefault("telegram_donos", [])
    cfg.setdefault("telegram_ultimo_id", None)
    cfg.setdefault("whatsapp_vistos", [])
    cfg.setdefault("provider", "auto")
    cfg.setdefault("model", None)
    cfg.setdefault("cerebro", "claude")  # "claude" (sessao trancada, com reserva local) ou "local"
    cfg.setdefault("voz_espelho", True)  # respondeu voz quando a pessoa mandou voz
    return cfg


def salvar_config(cfg: Dict[str, Any]) -> None:
    _gravar(CONFIG, cfg)


# ----------------------------------------------------------------------------- vinculo do Telegram
def gerar_codigo_vinculo() -> Dict[str, Any]:
    """Gera o codigo que a pessoa manda ao bot (`/vincular 123456`) para provar que o chat e dela."""
    codigo = f"{secrets.randbelow(10**6):06d}"
    _gravar(CODIGO, {"codigo": codigo, "expira": time.time() + CODIGO_TTL})
    return {"codigo": codigo, "valido_minutos": int(CODIGO_TTL // 60),
            "como_usar": f"No Telegram, abra o bot e envie: /vincular {codigo}"}


def _consumir_codigo(texto: str) -> bool:
    partes = (texto or "").strip().split()
    if len(partes) != 2 or partes[0].lower() != "/vincular":
        return False
    atual = _ler(CODIGO, {})
    ok = bool(atual) and time.time() < float(atual.get("expira", 0)) and secrets.compare_digest(str(atual.get("codigo", "")), partes[1])
    if ok:
        CODIGO.unlink(missing_ok=True)  # uso unico
    return ok


def estado() -> Dict[str, Any]:
    cfg = config()
    fila = _ler(FILA, [])
    return {
        "ativo": cfg["ativo"],
        "telegram_donos": len(cfg["telegram_donos"]),
        "cerebro": cfg["cerebro"],
        "voz_espelho": bool(cfg.get("voz_espelho", True)),
        "claude_vivo": claude_vivo(),
        "provider_reserva": cfg["provider"],
        "fila_aberta": sum(1 for i in fila if i.get("estado") == "aberto"),
    }


# ----------------------------------------------------------------------------- fila (canal e Google)
def claude_vivo() -> bool:
    return time.time() - float(_ler(VIVO, {}).get("ts", 0)) < VIVO_TTL


def _enfileirar(tipo: str, pedido: str, canal: str, destino: str, audio: bool = False) -> Dict[str, Any]:
    with _trava_fila():
        fila: List[Dict[str, Any]] = _ler(FILA, [])
        item = {"id": secrets.token_hex(4), "tipo": tipo, "pedido": pedido.strip()[:12000], "canal": canal,
                "destino": str(destino), "audio": bool(audio), "estado": "aberto", "criado": time.time()}
        fila.append(item)
        _gravar(FILA, fila[-50:])
    return item


def google_pedir(pedido: str, canal: str, destino: str) -> Dict[str, Any]:
    item = _enfileirar("google", pedido, canal, destino)
    return {"id": item["id"], "aviso": "Pedido enviado a sessao do Google. A resposta chega neste mesmo canal."}


def canal_pedir(pedido: str, canal: str, destino: str, audio: bool = False) -> Dict[str, Any]:
    return _enfileirar("canal", pedido, canal, destino, audio)


def proxima(tipos: Tuple[str, ...] = ("canal", "google")) -> Optional[Dict[str, Any]]:
    with _trava_fila():
        fila: List[Dict[str, Any]] = _ler(FILA, [])
        for item in fila:
            if item.get("estado") == "aberto" and item.get("tipo", "google") in tipos and time.time() - item["criado"] < 3600:
                item["estado"] = "em_andamento"
                item["pegou"] = time.time()
                _gravar(FILA, fila)
                return {"id": item["id"], "tipo": item.get("tipo", "google"), "canal": item["canal"],
                        "pedido": item["pedido"], "audio": item.get("audio", False)}
    return None


def google_proxima() -> Optional[Dict[str, Any]]:
    return proxima(("google",))


def _achar(item_id: str) -> Optional[Dict[str, Any]]:
    for i in _ler(FILA, []):
        if i["id"] == item_id:
            return i
    return None


def _marcar(item_id: str, de: Tuple[str, ...], para: str) -> bool:
    """Muda o estado so se ainda estiver em um dos estados `de` (evita responder duas vezes)."""
    with _trava_fila():
        fila: List[Dict[str, Any]] = _ler(FILA, [])
        for item in fila:
            if item["id"] == item_id and item.get("estado") in de:
                item["estado"] = para
                _gravar(FILA, fila)
                return True
    return False


async def responder(item_id: str, texto: str, audio: Optional[bool] = None) -> Dict[str, Any]:
    item = _achar(item_id)
    if not item or item.get("estado") not in ("aberto", "em_andamento"):
        return {"ok": False, "erro": "Pedido nao encontrado, expirado ou ja respondido."}
    if not _marcar(item_id, ("aberto", "em_andamento"), "respondido"):
        return {"ok": False, "erro": "Pedido ja respondido."}
    por_voz = bool(item.get("audio")) and config()["voz_espelho"] if audio is None else bool(audio)
    await enviar(item["canal"], item["destino"], texto, audio=por_voz)
    return {"ok": True}


async def google_responder(item_id: str, texto: str) -> Dict[str, Any]:
    return await responder(item_id, texto)


async def enviar_arquivo_do_pedido(item_id: str, caminho: str, legenda: str = "") -> Dict[str, Any]:
    """Para a sessao do Claude: manda um arquivo do computador para o dono, no canal do pedido (nunca para outro destino)."""
    item = _achar(item_id)
    if not item or item.get("estado") not in ("aberto", "em_andamento"):
        return {"ok": False, "erro": "Pedido nao encontrado ou ja respondido."}
    p = Path(caminho)
    if not p.is_file():
        return {"ok": False, "erro": "Arquivo nao encontrado."}
    if p.stat().st_size > 45 * 1024 * 1024:
        return {"ok": False, "erro": "Arquivo grande demais para enviar (limite 45 MB)."}
    await enviar_arquivo(item["canal"], item["destino"], str(p), legenda)
    return {"ok": True, "enviado": p.name}


# ----------------------------------------------------------------------------- envio
def _partir(texto: str, tam: int = LIMITE_TELEGRAM) -> List[str]:
    texto = (texto or "").strip() or "Pronto."
    return [texto[i:i + tam] for i in range(0, len(texto), tam)]


async def enviar(canal: str, destino: str, texto: str, audio: bool = False) -> None:
    from core.channels import midia_canais as mc
    from core.channels.telegram_manager import telegram_manager
    from core.channels.whatsapp_manager import whatsapp_manager

    if audio and len(texto or "") <= mc.MAX_VOZ_CARACTERES:
        ogg = await asyncio.to_thread(mc.sintetizar_ogg, texto)
        if ogg:
            try:
                if canal == "telegram":
                    await telegram_manager.send_file(telegram_manager.get_default_token(), int(destino), str(ogg), "voice")
                else:
                    r = await asyncio.to_thread(whatsapp_manager.send_media, destino, str(ogg), "audio")
                    if not r.get("ok", True):
                        raise RuntimeError(r.get("error", "falha"))
                return
            except Exception:  # noqa: BLE001 - voz falhou: cai para texto
                logger.exception("Falha ao enviar voz; enviando texto")
    for pedaco in _partir(texto):
        if canal == "telegram":
            await telegram_manager.send_message(telegram_manager.get_default_token(), int(destino), html.escape(pedaco))
        else:
            await asyncio.to_thread(whatsapp_manager.send_text, "Blind: " + pedaco, "", destino)


async def enviar_arquivo(canal: str, destino: str, caminho: str, legenda: str = "") -> None:
    from core.channels.telegram_manager import telegram_manager
    from core.channels.whatsapp_manager import whatsapp_manager

    if canal == "telegram":
        await telegram_manager.send_file(telegram_manager.get_default_token(), int(destino), caminho, "document", legenda)
    else:
        r = await asyncio.to_thread(whatsapp_manager.send_media, destino, caminho, "document", legenda)
        if not r.get("ok", True):
            raise RuntimeError(r.get("error", "falha ao enviar arquivo"))


# ----------------------------------------------------------------------------- entender o que chegou
_TIPO_TELEGRAM = {"voice": "audio", "audio": "audio", "photo": "imagem", "video": "video", "document": "documento"}
_TIPO_WHATSAPP = {"audio": "audio", "imagem": "imagem", "video": "video", "documento": "documento"}


async def _entender_telegram(msg: Dict[str, Any]) -> Tuple[str, bool]:
    """Devolve (texto para o Blind, veio_em_voz)."""
    from core.channels import midia_canais as mc

    texto = msg.get("text") or ""
    tipo, fid = _TIPO_TELEGRAM.get(msg.get("media_type") or ""), msg.get("file_id")
    if not tipo or not fid:
        return texto, False
    nome = ""
    if tipo == "documento" and texto.startswith("[Documento:"):
        nome = texto[len("[Documento:"):].rstrip("]").strip()
    caminho = await mc.baixar_telegram(fid, nome or ("audio.ogg" if tipo == "audio" else "foto.jpg" if tipo == "imagem" else "video.mp4"))
    legenda = "" if texto.startswith("[") else texto
    return await mc.entender_arquivo(caminho, tipo, legenda), tipo == "audio"


async def _entender_whatsapp(m: Dict[str, Any]) -> Tuple[str, bool]:
    from core.channels import midia_canais as mc

    texto, tipo, arq = m.get("texto") or "", _TIPO_WHATSAPP.get(m.get("tipo") or ""), m.get("arquivo") or ""
    if not tipo or not arq or not os.path.isfile(arq):
        return texto, False
    return await mc.entender_arquivo(Path(arq), tipo, texto), tipo == "audio"


CONTEXTO = ("[Canal: {canal}. A pessoa e cega e fala com voce de longe, pelo celular. Responda curto, em texto simples, sem markdown. "
            "Calendario, Drive e Gmail NAO sao suas: para isso use a ferramenta google_pedir (canal={canal}, destino={destino}) "
            "e avise que a resposta chega em instantes. Enviar e-mail, criar ou apagar evento e compartilhar arquivo: peca o sim da pessoa "
            "primeiro; so depois do sim chame google_pedir de novo, comecando o pedido com CONFIRMADO PELA PESSOA. "
            "Antes de enviar mensagem a terceiros, mostre o rascunho e espere o sim.]\n")


# ----------------------------------------------------------------------------- laco principal
class Ponte:
    def __init__(self, chat: Chat):
        self.chat = chat  # modelo local (reserva)
        self._tarefa: Optional[asyncio.Task] = None
        self._vigias: set = set()

    def iniciar(self) -> None:
        if self._tarefa is None or self._tarefa.done():
            self._tarefa = asyncio.create_task(self._laco())

    def parar(self) -> None:
        if self._tarefa:
            self._tarefa.cancel()

    async def _laco(self) -> None:
        from core.leader import leader_for

        dono = leader_for("canais-blind")
        ultima_limpeza = 0.0
        while True:
            try:
                if config()["ativo"] and dono.try_acquire():
                    await self._ciclo()
                    if time.time() - ultima_limpeza > 3600:
                        ultima_limpeza = time.time()
                        from core.channels import midia_canais

                        await asyncio.to_thread(midia_canais.limpar_antigos)
                    await asyncio.sleep(2)
                else:
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("Erro no ciclo dos canais do Blind")
                await asyncio.sleep(5)

    async def _ciclo(self) -> None:
        await self._telegram()
        await self._whatsapp()

    # -- Telegram
    async def _telegram(self) -> None:
        from core.channels.telegram_manager import telegram_manager

        bots = telegram_manager.get_connected_bots()
        if not bots:
            return
        for b in bots:  # o polling morre quando o app fecha: religa para os bots conectados
            try:
                token = telegram_manager.get_default_token(b["bot_id"])
            except Exception:  # noqa: BLE001
                continue
            if token not in telegram_manager._polling_tasks:
                telegram_manager.start_polling(token, b["bot_id"])
        cfg = config()
        msgs = [m for m in telegram_manager.get_messages(None, None, "inbound", 50)]
        msgs.sort(key=lambda m: m["message_id"])
        if cfg["telegram_ultimo_id"] is None:  # primeira vez: nao responde ao que ja estava la
            cfg["telegram_ultimo_id"] = msgs[-1]["message_id"] if msgs else 0
            salvar_config(cfg)
            # ...mas um /vincular recente ainda vale
            novas = [m for m in msgs if (m.get("text") or "").startswith("/vincular") and time.time() - m["created_at"] < CODIGO_TTL]
        else:
            novas = [m for m in msgs if m["message_id"] > cfg["telegram_ultimo_id"]]
        for m in novas:
            cfg["telegram_ultimo_id"] = max(cfg["telegram_ultimo_id"] or 0, m["message_id"])
            salvar_config(cfg)
            await self._telegram_uma(m, cfg)

    async def _telegram_uma(self, m: Dict[str, Any], cfg: Dict[str, Any]) -> None:
        chat_id = int(m["chat_id"])
        texto = (m.get("text") or "").strip()
        if _consumir_codigo(texto):
            if chat_id not in cfg["telegram_donos"]:
                cfg["telegram_donos"].append(chat_id)
                salvar_config(cfg)
            await enviar("telegram", str(chat_id), "Vinculado. Agora eu respondo so a voce, aqui. Pode pedir.")
            return
        if chat_id not in cfg["telegram_donos"]:
            logger.info("Telegram: mensagem de chat nao vinculado ignorada (%s)", chat_id)
            return
        if time.time() - float(m["created_at"]) > MAX_ANTIGA_S:
            return
        await self._atender("telegram", str(chat_id), lambda: _entender_telegram(m))

    # -- WhatsApp
    async def _whatsapp(self) -> None:
        from core.channels.whatsapp_manager import whatsapp_manager

        try:
            data = await asyncio.to_thread(whatsapp_manager.messages, 30)
        except Exception:  # noqa: BLE001 - conector desligado ou nao pareado: segue
            return
        msgs = [x for x in reversed(data.get("mensagens", [])) if x.get("proprio")]  # mais antigas primeiro
        cfg = config()
        vistos = list(cfg["whatsapp_vistos"])
        if "whatsapp_iniciado" not in cfg:
            cfg["whatsapp_iniciado"] = True
            cfg["whatsapp_vistos"] = [x["id"] for x in msgs]
            salvar_config(cfg)
            return
        for x in msgs:
            if x["id"] in vistos:
                continue
            vistos.append(x["id"])
            cfg["whatsapp_vistos"] = vistos[-200:]
            salvar_config(cfg)
            quando = _epoch(x.get("quando"))
            if quando and time.time() - quando > MAX_ANTIGA_S:
                continue
            if (x.get("texto") or "").startswith("Blind:"):
                continue
            await self._atender("whatsapp", x["jid"], lambda x=x: _entender_whatsapp(x))

    # -- resposta
    async def _atender(self, canal: str, destino: str, entender: Callable[[], Awaitable[Tuple[str, bool]]]) -> None:
        cfg = config()
        por_voz = False
        try:
            texto, por_voz = await entender()
            texto = (texto or "").strip()
            if not texto:
                return
            if texto.lower() in ("/ajuda", "ajuda"):
                await enviar(canal, destino, "Fale ou escreva o que precisa: lembretes, documentos, arquivos, memoria, "
                                              "calendario, Drive e Gmail. Posso receber audio, foto, video e documentos. "
                                              "Mensagens a outras pessoas so saem com o seu sim.")
                return
            if cfg["cerebro"] == "claude" and claude_vivo():
                item = canal_pedir(texto, canal, destino, por_voz)
                self._vigiar(item["id"], canal, destino, texto, por_voz)
                return
            resposta = await self._local(canal, destino, texto)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha ao atender %s", canal)
            resposta = f"Nao consegui agora: {type(exc).__name__}. Tente de novo em instantes."
        await enviar(canal, destino, resposta, audio=por_voz and cfg["voz_espelho"])

    async def _local(self, canal: str, destino: str, texto: str) -> str:
        return await self.chat(f"canal-{canal}", CONTEXTO.format(canal=canal, destino=destino) + texto)

    def _vigiar(self, item_id: str, canal: str, destino: str, texto: str, por_voz: bool) -> None:
        tarefa = asyncio.create_task(self._reserva(item_id, canal, destino, texto, por_voz))
        self._vigias.add(tarefa)
        tarefa.add_done_callback(self._vigias.discard)

    async def _reserva(self, item_id: str, canal: str, destino: str, texto: str, por_voz: bool) -> None:
        """Se a sessao do Claude nao pegar ou nao responder a tempo, o modelo local responde (uma vez so)."""
        inicio = time.time()
        while True:
            await asyncio.sleep(2)
            item = _achar(item_id)
            if not item or item.get("estado") in ("respondido", "local"):
                return
            esperou = time.time() - inicio
            pegou = item.get("estado") == "em_andamento"
            if (not pegou and esperou > ESPERA_PEGAR_S) or esperou > ESPERA_RESPONDER_S:
                break
        if not _marcar(item_id, ("aberto", "em_andamento"), "local"):
            return
        try:
            resposta = await self._local(canal, destino, texto)
        except Exception as exc:  # noqa: BLE001
            resposta = f"Nao consegui agora: {type(exc).__name__}. Tente de novo em instantes."
        await enviar(canal, destino, resposta, audio=por_voz and config()["voz_espelho"])


def _epoch(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    from datetime import datetime

    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
