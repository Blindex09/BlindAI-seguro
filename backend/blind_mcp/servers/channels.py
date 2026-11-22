"""Servidor MCP: canais de mensageria acessiveis (WhatsApp por codigo de pareamento e Telegram,
com audiodescricao de fotos recebidas e transcricao local de audios/mensagens de voz).

telegram_connect recebe o token do bot. Ele fica no mcp.json em modelHiddenTools: a interface
chama a ferramenta, mas o token nunca e oferecido ao modelo de IA.
"""

from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from ._common import BACKEND_DIR, run_blocking

from config.settings import config  # noqa: E402
from core.channels.telegram_manager import telegram_manager  # noqa: E402
from core.channels.whatsapp_manager import whatsapp_manager  # noqa: E402
from core.vision.smart_vision_router import smart_vision_router  # noqa: E402

mcp = FastMCP("blind-channels")


@mcp.tool()
async def whatsapp_pair(phone: str) -> Dict[str, Any]:
    """Pareia o WhatsApp da pessoa pelo conector real (Baileys): devolve o codigo de 8 caracteres que o PROPRIO WhatsApp gerou
    (vale poucos minutos) e como digita-lo no celular (Aparelhos Conectados > Conectar com numero de telefone). So chame se a
    pessoa pedir e der o numero com DDD. Se o conector nao estiver instalado, devolve erro e NAO gera codigo."""
    return await run_blocking(whatsapp_manager.start_pairing, phone)


@mcp.tool()
async def whatsapp_status(phone: str = "") -> Dict[str, Any]:
    """Consulta o estado da conexao do WhatsApp. Sem `phone`, lista todos os numeros conectados ou em pareamento
    (sem mostrar codigos). Com `phone`, mostra o estado desse numero."""
    if (phone or "").strip():
        return await run_blocking(whatsapp_manager.get_status, phone)
    return await run_blocking(_whatsapp_list)


def _video_frame(path: str) -> Optional[str]:
    """Tira um quadro do video (ffmpeg, se existir) para descrever. Devolve o caminho do .jpg ou None."""
    import shutil
    import subprocess

    ff = shutil.which("ffmpeg")
    if not ff:
        return None
    out = path + ".quadro.jpg"
    try:
        subprocess.run([ff, "-y", "-loglevel", "error", "-ss", "1", "-i", path, "-frames:v", "1", out],
                       check=True, timeout=30, capture_output=True)
        if not os.path.isfile(out):  # video de menos de 1 s: tenta do inicio
            subprocess.run([ff, "-y", "-loglevel", "error", "-i", path, "-frames:v", "1", out],
                           check=True, timeout=30, capture_output=True)
    except Exception:  # noqa: BLE001
        return None
    return out if os.path.isfile(out) else None


@mcp.tool()
async def whatsapp_messages(limit: int = 20, entender_midias: bool = True, max_midias: int = 6) -> Dict[str, Any]:
    """Lista as mensagens de WhatsApp recebidas desde que o conector ligou (mais novas primeiro): de quem, nome, texto, tipo
    (texto, audio, imagem, video, documento) e o arquivo baixado. Para a pessoa cega entender a conversa, por padrao as
    midias mais recentes (ate max_midias) ja voltam entendidas: audio e video com `transcricao` (o que foi falado), foto e
    video com `descricao` (audiodescricao). Midia alem do limite volta sem isso: diga que ha mais e ofereca. Use
    entender_midias=false so se a pessoa pedir so os textos. So le; nao responde nem marca como lida. Nao traz mensagens
    antigas, so as que chegam depois do conector ligar. Exige o WhatsApp pareado."""
    data = await run_blocking(whatsapp_manager.messages, limit)
    if not entender_midias:
        return data
    feitas, puladas = 0, 0
    for m in data.get("mensagens", []):  # mais novas primeiro
        arq = m.get("arquivo") or ""
        tipo = m.get("tipo")
        if tipo not in ("audio", "imagem", "video") or not arq or not os.path.isfile(arq):
            continue
        if feitas >= max(0, int(max_midias)):
            puladas += 1
            m["nao_processada"] = "Limite de midias por leitura; peca para eu entender esta."
            continue
        feitas += 1
        try:
            if tipo in ("audio", "video"):
                res = await run_blocking(_transcribe_file_sync, arq, "pt")
                m["transcricao"] = res["text"] or "(sem fala reconhecida)"
            if tipo in ("imagem", "video"):
                alvo = arq if tipo == "imagem" else await run_blocking(_video_frame, arq)
                if alvo:
                    res = await channel_describe_image(file_path=alvo)
                    m["descricao"] = res["description"]
                elif tipo == "video":
                    m["descricao"] = "(nao consegui extrair um quadro do video para descrever)"
        except Exception as exc:  # noqa: BLE001 - uma midia com erro nao derruba a lista
            m["erro_midia"] = f"Nao consegui processar: {type(exc).__name__}: {exc}"[:200]
    if puladas:
        data["midias_nao_processadas"] = puladas
    return data


def _whatsapp_list() -> Dict[str, Any]:
    import sqlite3

    with sqlite3.connect(whatsapp_manager.db_path) as conn:
        rows = conn.execute("SELECT phone, status, last_active FROM whatsapp_sessions ORDER BY last_active DESC").fetchall()
    sessions = [{"phone": r[0], "status": r[1], "last_active": r[2]} for r in rows]
    return {"count": len(sessions), "sessions": sessions}


@mcp.tool()
async def telegram_connect(bot_token: str) -> Dict[str, Any]:
    """Valida o token do BotFather e conecta o bot ao Telegram."""
    return await telegram_manager.connect_bot(bot_token)


@mcp.tool()
async def telegram_status() -> List[Dict[str, Any]]:
    """Lista os bots do Telegram conectados."""
    return telegram_manager.get_connected_bots()


@mcp.tool()
async def telegram_messages(
    chat_id: Optional[str] = None,
    direction: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Lista as mensagens recentes recebidas ou enviadas no Telegram (incluindo fotos e audios com file_id)."""
    cid = int(chat_id) if chat_id and str(chat_id).lstrip("-").isdigit() else chat_id
    return await run_blocking(
        telegram_manager.get_messages,
        None,
        cid,
        direction,
        max(1, min(int(limit or 20), 100)),
    )


@mcp.tool()
async def canais_vincular_telegram() -> Dict[str, Any]:
    """Gera o codigo de 6 digitos para a pessoa vincular o chat dela ao bot do Telegram (vale 10 min, uso unico). Ela envia
    `/vincular CODIGO` ao bot e, a partir dai, o Blind responde so a ela naquele chat. So chame se a pessoa pedir."""
    from core.channels import blind_bridge

    return blind_bridge.gerar_codigo_vinculo()


@mcp.tool()
async def google_pedir(pedido: str, canal: str, destino: str) -> Dict[str, Any]:
    """Passa um pedido de Calendar, Drive ou Gmail a sessao do Google (o Blind nao tem esses conectores). A resposta chega depois,
    sozinha, pelo canal de origem. `canal` e 'telegram' ou 'whatsapp' e `destino` o que a mensagem de contexto informou. Descreva o
    pedido completo e sem segredos. Enviar e-mail ou convite so com o sim da pessoa."""
    from core.channels import blind_bridge

    if (canal or "").lower() not in ("telegram", "whatsapp"):
        return {"ok": False, "erro": "canal deve ser telegram ou whatsapp."}
    return blind_bridge.google_pedir(pedido, canal.lower(), destino)


@mcp.tool()
async def google_fila_proxima() -> Dict[str, Any]:
    """Para a SESSAO DO CLAUDE: proximo pedido de Calendar/Drive/Gmail vindo do celular pelo modelo local (ou vazio)."""
    from core.channels import blind_bridge

    return blind_bridge.google_proxima() or {"vazio": True}


@mcp.tool()
async def google_fila_responder(id: str, resposta: str) -> Dict[str, Any]:
    """Para a SESSAO DO CLAUDE: entrega a resposta curta (texto simples) de um pedido do Google ao canal de origem."""
    from core.channels import blind_bridge

    return await blind_bridge.google_responder(id, resposta)


@mcp.tool()
async def canal_proxima() -> Dict[str, Any]:
    """Para a SESSAO DO CLAUDE dos canais: pega o proximo pedido da pessoa vindo do Telegram/WhatsApp (ja com audio transcrito,
    foto descrita, video e documentos entendidos; os arquivos ficam no caminho indicado). Devolve id, canal, pedido e se veio em
    voz; ou {vazio: true}. Responda SEMPRE com canal_responder usando o mesmo id."""
    from core.channels import blind_bridge

    return blind_bridge.proxima() or {"vazio": True}


@mcp.tool()
async def canal_responder(id: str, resposta: str, audio: Optional[bool] = None) -> Dict[str, Any]:
    """Para a SESSAO DO CLAUDE dos canais: entrega a resposta ao canal de origem do pedido `id`. Texto simples, curto, sem markdown
    (a pessoa e cega). `audio` omitido = responde em voz quando a pessoa mandou voz; true forca voz; false forca texto."""
    from core.channels import blind_bridge

    return await blind_bridge.responder(id, resposta, audio)


@mcp.tool()
async def canal_enviar_arquivo(id: str, caminho: str, legenda: str = "") -> Dict[str, Any]:
    """Para a SESSAO DO CLAUDE dos canais: envia um arquivo do computador (ate 45 MB) a pessoa, no canal do pedido `id`. So vai para
    a propria pessoa, nunca para outro destino. Depois chame canal_responder para fechar o pedido."""
    from core.channels import blind_bridge

    return await blind_bridge.enviar_arquivo_do_pedido(id, caminho, legenda)


@mcp.tool()
async def canais_configurar(cerebro: str = "", voz_espelho: Optional[bool] = None) -> Dict[str, Any]:
    """Ajusta os canais do celular. cerebro: 'claude' (sessao trancada do Claude, com reserva local) ou 'local' (so o modelo do
    backend). voz_espelho: responder em voz quando a pessoa mandar voz. Sem argumentos, mostra o estado."""
    from core.channels import blind_bridge as bb

    cfg = bb.config()
    if cerebro in ("claude", "local"):
        cfg["cerebro"] = cerebro
    if voz_espelho is not None:
        cfg["voz_espelho"] = bool(voz_espelho)
    bb.salvar_config(cfg)
    return bb.estado()


DATA_DIR = Path(os.environ.get("BLIND_DATA_DIR") or (BACKEND_DIR / "data"))
CONTACTS_FILE = DATA_DIR / "contatos_telegram.json"
_PENDING: Dict[str, Dict[str, Any]] = {}  # codigo -> rascunho aguardando o "sim" da pessoa
_PENDING_TTL = 600.0


def _contacts_file(app: str = "telegram") -> Path:
    return DATA_DIR / ("contatos_whatsapp.json" if (app or "").lower() == "whatsapp" else "contatos_telegram.json")


def _load_contacts(app: str = "telegram") -> Dict[str, str]:
    import json

    try:
        return {str(k): str(v) for k, v in json.loads(_contacts_file(app).read_text(encoding="utf-8")).items()}
    except Exception:  # noqa: BLE001
        return {}


def _save_contacts(data: Dict[str, str], app: str = "telegram") -> None:
    import json

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _contacts_file(app).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_contact(ref: str, app: str = "telegram") -> tuple:
    """Aceita o chat_id numerico ou um apelido salvo (sem acento/caixa). Devolve (chat_id, apelido ou None)."""
    r = (ref or "").strip()
    if r.lstrip("-").isdigit():
        for nick, cid in _load_contacts(app).items():
            if cid == r:
                return r, nick
        return r, None
    folded = _fold_nick(r)
    for nick, cid in _load_contacts(app).items():
        if _fold_nick(nick) == folded:
            return cid, nick
    raise ValueError(f"Nao ha contato com o apelido '{r}' no {app}. Use contato_listar ou informe o numero.")


def _fold_nick(s: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn").strip()


@mcp.tool()
async def contato_salvar(apelido: str, chat_id: str, app: str = "telegram") -> Dict[str, Any]:
    """Guarda um apelido para depois mandar mensagem dizendo so o apelido. app='telegram': chat_id numerico (ex: apelido 'mae',
    chat_id '123456'). app='whatsapp': chat_id e o telefone com DDD OU o nome de um contato do celular (ex: apelido
    'minha mulher', chat_id 'Mozao'). Use para parentesco: quando a pessoa disser 'mozao e minha mulher', guarde assim."""
    nick, cid = (apelido or "").strip(), (chat_id or "").strip()
    app = (app or "telegram").lower()
    if app == "whatsapp":
        if any(ch.isalpha() for ch in cid) and "@" not in cid:  # um nome da agenda: guarda o telefone dele
            fone, jid, _ = await run_blocking(_wa_resolve, cid)
            cid = fone or jid
        elif "@" not in cid:
            cid = "".join(c for c in cid if c.isdigit())
        if "@" not in cid and len(cid) < 10:
            raise ValueError("Informe o telefone com DDD ou o nome de um contato do WhatsApp.")
    if not nick or not (cid.lstrip("-").isdigit() or (app == "whatsapp" and "@" in cid)):
        raise ValueError("Informe um apelido e um chat_id numerico.")
    data = _load_contacts(app)
    data[nick] = cid
    _save_contacts(data, app)
    return {"ok": True, "app": app, "apelido": nick, "chat_id": cid}


@mcp.tool()
async def contato_listar(app: str = "telegram") -> Dict[str, Any]:
    """Lista os apelidos de contatos salvos (app='telegram' ou 'whatsapp')."""
    data = _load_contacts(app)
    return {"ok": True, "app": app, "total": len(data), "contatos": [{"apelido": k, "chat_id": v} for k, v in data.items()]}


@mcp.tool()
async def contato_remover(apelido: str, app: str = "telegram") -> Dict[str, Any]:
    """Remove um apelido de contato salvo (app='telegram' ou 'whatsapp')."""
    data = _load_contacts(app)
    folded = _fold_nick(apelido)
    alvo = next((k for k in data if _fold_nick(k) == folded), None)
    if alvo is None:
        return {"ok": True, "removido": False, "erro": f"Nao ha contato '{apelido}'."}
    del data[alvo]
    _save_contacts(data, app)
    return {"ok": True, "removido": True, "apelido": alvo}


def _aviso_sensivel(texto: str) -> Optional[str]:
    """Se a mensagem leva dado sensivel (senha, chave, cartao, CPF...), avisa a pessoa antes de enviar."""
    from blind_mcp import cofre

    tipos = cofre.detectar(texto)
    if not tipos:
        return None
    return (f"A mensagem parece conter {', '.join(tipos)}. Diga isso a pessoa e confirme que é mesmo para enviar esse dado "
            "a esse destinatário, que vê tudo e pode guardar.")


def _wa_find_in_agenda(ref: str) -> List[Dict[str, Any]]:
    """Procura na agenda do WhatsApp (nomes salvos no celular) por nome, sem acento nem caixa. Exato primeiro, depois parcial."""
    alvo = _fold_nick(ref)
    if not alvo:
        return []
    cont = whatsapp_manager.contacts()

    def nomes(c: Dict[str, Any]) -> List[str]:
        return [_fold_nick(c.get("nome", "")), _fold_nick(c.get("nome_publico", ""))]

    exatos = [c for c in cont if alvo in nomes(c)]
    if exatos:
        return exatos
    palavras = alvo.split()
    return [c for c in cont if any(all(w in n for w in palavras) for n in nomes(c) if n)]


def _wa_label(c: Dict[str, Any]) -> str:
    fim = (c.get("telefone") or "")[-4:]
    return f"{c.get('nome') or c.get('nome_publico')}" + (f" (final {fim})" if fim else "")


def _wa_resolve(ref: str) -> tuple:
    """Quem e `ref` no WhatsApp? Devolve (telefone, jid, nome para falar). Ordem: telefone, jid, apelido salvo, agenda do celular."""
    ref = (ref or "").strip()
    if "@" in ref:
        return "", ref, None
    if ref and not any(ch.isalpha() for ch in ref):
        phone = whatsapp_manager.normalize_phone(ref)
        nick = next((n for n, num in _load_contacts("whatsapp").items() if whatsapp_manager.normalize_phone(num) == phone), None)
        return phone, "", nick
    try:  # 1) apelido que a pessoa ou o Blind guardou (ex.: "mulher" -> Mozao)
        valor, nick = _resolve_contact(ref, "whatsapp")
        if "@" in valor:
            return "", valor, nick
        return whatsapp_manager.normalize_phone(valor), "", nick
    except ValueError:
        pass
    achados = _wa_find_in_agenda(ref)  # 2) nome salvo no celular
    if len(achados) == 1:
        c = achados[0]
        return (whatsapp_manager.normalize_phone(c["telefone"]) if c.get("telefone") else ""), \
            ("" if c.get("telefone") else c["jid"]), (c.get("nome") or c.get("nome_publico"))
    if len(achados) > 1:
        raise ValueError("Mais de um contato com esse nome: " + "; ".join(_wa_label(c) for c in achados[:6]) +
                         ". Pergunte qual a pessoa quer e use o nome completo.")
    raise ValueError(f"Nao achei '{ref}' nos contatos do WhatsApp nem entre os apelidos. Use whatsapp_contatos para procurar "
                     "ou peca o telefone com DDD.")


@mcp.tool()
async def whatsapp_contatos(busca: str = "") -> Dict[str, Any]:
    """Procura nos contatos do WhatsApp da pessoa (os nomes que ela salvou no celular: mae, pai, mozao...). Sem `busca`, lista
    alguns. Devolve nome e final do telefone, para a pessoa confirmar quem e. A agenda fica so neste computador. Se vier
    vazia, o WhatsApp ainda nao entregou a lista: tente de novo em um minuto."""
    if (busca or "").strip():
        achados = await run_blocking(_wa_find_in_agenda, busca)
    else:
        achados = await run_blocking(whatsapp_manager.contacts)
    achados = [c for c in achados if c.get("nome") or c.get("nome_publico")]
    return {"ok": True, "total": len(achados), "contatos": [
        {"nome": c.get("nome") or c.get("nome_publico"), "final_telefone": (c.get("telefone") or "")[-4:]} for c in achados[:30]]}


@mcp.tool()
async def whatsapp_send(para: str, text: str, codigo_confirmacao: Optional[str] = None) -> Dict[str, Any]:
    """Envia mensagem de WhatsApp, em DUAS etapas. `para` aceita o NOME como esta salvo no celular da pessoa (mae, mozao, pai...),
    um apelido (contato_salvar app='whatsapp'), o telefone com DDD ou o `jid` de uma mensagem recebida (para responder).
    Se houver mais de um contato com o nome, volta erro listando as opcoes: pergunte qual.
    1) Chame sem `codigo_confirmacao`: NADA e enviado; volta o rascunho e um codigo. Leia em voz alta o destinatario e o texto
       e pergunte 'Posso enviar?'.
    2) So depois do 'sim' da pessoa, chame de novo com os mesmos para e text e o `codigo_confirmacao` (vale por 10 minutos).
       Se a pessoa mudar o texto, comece de novo. Confirme ao final se foi enviado, sem inventar."""
    import secrets
    import time

    for k in [k for k, v in _PENDING.items() if time.time() - v["criado"] > _PENDING_TTL]:
        del _PENDING[k]
    ref = (para or "").strip()
    body = (text or "").strip()
    if not body:
        raise ValueError("A mensagem esta vazia.")
    phone, jid, nick = await run_blocking(_wa_resolve, ref)
    alvo = jid or phone
    destino = f"{nick} ({alvo})" if nick else alvo

    if not codigo_confirmacao:
        code = secrets.token_hex(2)
        _PENDING[code] = {"canal": "whatsapp", "para": alvo, "text": body, "criado": time.time()}
        return {"ok": True, "enviado": False, "codigo_confirmacao": code, "destinatario": destino, "texto": body,
                "aviso_sensivel": _aviso_sensivel(body),
                "instrucao": "Leia o destinatario e o texto para a pessoa e pergunte 'Posso enviar?'. So reenvie com o codigo apos o sim."}
    draft = _PENDING.get(codigo_confirmacao.strip())
    if not draft or draft.get("canal") != "whatsapp" or draft["para"] != alvo or draft["text"] != body:
        raise ValueError("Codigo invalido, vencido, ou o destinatario/texto mudou. Comece de novo sem o codigo.")
    del _PENDING[codigo_confirmacao.strip()]
    res = await run_blocking(whatsapp_manager.send_text, body, phone, jid)
    return {"ok": True, "enviado": True, "destinatario": destino, "id": res.get("id")}


@mcp.tool()
async def telegram_send(
    chat_id: str, text: str, bot_id: Optional[int] = None, codigo_confirmacao: Optional[str] = None
) -> Dict[str, Any]:
    """Envia mensagem pelo bot do Telegram, em DUAS etapas. `chat_id` aceita o numero ou um apelido salvo.
    1) Chame sem `codigo_confirmacao`: NADA e enviado; volta o rascunho e um codigo. Leia em voz alta o destinatario e o texto
       e pergunte 'Posso enviar?'.
    2) So depois do 'sim' da pessoa, chame de novo com os mesmos chat_id e text e o `codigo_confirmacao` recebido
       (vale por 10 minutos). Se a pessoa mudar o texto, comece de novo."""
    import secrets
    import time

    for k in [k for k, v in _PENDING.items() if time.time() - v["criado"] > _PENDING_TTL]:
        del _PENDING[k]
    real_id, nick = _resolve_contact(chat_id)
    body = (text or "").strip()
    if not body:
        raise ValueError("A mensagem esta vazia.")
    destino = f"{nick} ({real_id})" if nick else real_id

    if not codigo_confirmacao:
        code = secrets.token_hex(2)
        _PENDING[code] = {"chat_id": real_id, "text": body, "bot_id": bot_id, "criado": time.time()}
        return {"ok": True, "enviado": False, "codigo_confirmacao": code, "destinatario": destino, "texto": body,
                "aviso_sensivel": _aviso_sensivel(body),
                "instrucao": "Leia o destinatario e o texto para a pessoa e pergunte 'Posso enviar?'. So reenvie com o codigo apos o sim."}

    pend = _PENDING.get(codigo_confirmacao.strip())
    if not pend or pend.get("chat_id") != real_id or pend["text"] != body or pend["bot_id"] != bot_id:
        raise ValueError("Codigo de confirmacao invalido, vencido ou o texto/destinatario mudou. Prepare o rascunho de novo "
                         "(chame sem codigo) e peca o sim outra vez.")
    del _PENDING[codigo_confirmacao.strip()]
    token = await run_blocking(telegram_manager.get_default_token, bot_id)
    result = await telegram_manager.send_message(token, real_id, body)
    return {"ok": True, "enviado": True, "destinatario": destino, "resultado": result}


@mcp.tool()
async def channel_describe_image(
    file_path: Optional[str] = None,
    telegram_file_id: Optional[str] = None,
    prompt: Optional[str] = None,
    bot_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Gera a audiodescricao completa de uma foto/imagem recebida no Telegram (via telegram_file_id)
    ou no WhatsApp/disco local (via file_path) para leitura por pessoas cegas."""
    b64_img: Optional[str] = None
    source_label = file_path or telegram_file_id or ""

    if telegram_file_id:
        raw_bytes, remote_path = await telegram_manager.download_file_bytes(telegram_file_id, bot_id=bot_id)
        b64_img = base64.b64encode(raw_bytes).decode("ascii")
        source_label = f"telegram:{remote_path}"
    elif not file_path or not os.path.isfile(file_path):
        raise FileNotFoundError("Informe um file_path existente ou um telegram_file_id valido.")

    api_key = (
        getattr(config, "gemini_api_key", "")
        or os.getenv("GEMINI_API_KEY", "")
        or getattr(config, "openai_api_key", "")
        or os.getenv("OPENAI_API_KEY", "")
    )
    description = await smart_vision_router.describe_multimodal(
        image_base64=b64_img,
        file_path=file_path if not b64_img else None,
        provider="auto",
        api_key=api_key,
        prompt_override=prompt
        or (
            "Descreva detalhadamente esta imagem recebida por mensagem para uma pessoa cega: "
            "texto visivel, comprovantes, valores, pessoas, objetos e contexto."
        ),
    )
    return {"ok": True, "source": source_label, "description": description}


_WHISPER: Dict[str, Any] = {}


def _whisper_model() -> Any:
    """Carrega o Whisper uma vez por processo. Usa o modelo local sem rede; so baixa se ainda nao existir."""
    if "model" in _WHISPER:
        return _WHISPER["model"]
    from faster_whisper import WhisperModel

    model_name = os.environ.get("BLIND_STT_MODEL", "base")
    model_dir = Path(os.environ.get("BLIND_DATA_DIR") or (BACKEND_DIR / "data")) / "models" / "whisper"
    model_dir.mkdir(parents=True, exist_ok=True)
    try:
        model = WhisperModel(model_name, device="auto", compute_type="int8", download_root=str(model_dir), local_files_only=True)
    except Exception:  # noqa: BLE001 - ainda nao baixado: baixa uma vez (pode levar minutos na primeira vez)
        model = WhisperModel(model_name, device="auto", compute_type="int8", download_root=str(model_dir))
    _WHISPER["model"] = model
    return model


def _transcribe_file_sync(path: str, language: str = "pt") -> Dict[str, Any]:
    model = _whisper_model()
    segments, info = model.transcribe(path, language=language or None, beam_size=5, vad_filter=True)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return {
        "ok": True,
        "text": text,
        "language": info.language,
        "duration_seconds": round(float(info.duration), 2),
    }


@mcp.tool()
async def channel_transcribe_audio(
    file_path: Optional[str] = None,
    telegram_file_id: Optional[str] = None,
    language: str = "pt",
    bot_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Transcreve em texto uma mensagem de voz ou audio recebida no Telegram (via telegram_file_id)
    ou no WhatsApp/disco local (via file_path, ex: .ogg, .opus, .mp3, .wav, .m4a)."""
    if telegram_file_id:
        raw_bytes, remote_path = await telegram_manager.download_file_bytes(telegram_file_id, bot_id=bot_id)
        suffix = Path(remote_path).suffix or ".ogg"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw_bytes)
            tmp_path = tmp.name
        try:
            res = await run_blocking(_transcribe_file_sync, tmp_path, language)
            res["source"] = f"telegram:{remote_path}"
            return res
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if not file_path or not os.path.isfile(file_path):
        raise FileNotFoundError("Informe um file_path existente ou um telegram_file_id valido.")
    res = await run_blocking(_transcribe_file_sync, file_path, language)
    res["source"] = file_path
    return res


if __name__ == "__main__":
    from . import _audit

    _audit.install_audit(mcp, "blind-channels")
    mcp.run()
