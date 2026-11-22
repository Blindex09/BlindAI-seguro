"""
Gerenciador de Canal Telegram - Blind AI
Clonado e adaptado da arquitetura do Hermes Agent (hermes_cli/telegram_managed_bot.py e hermes_state_telegram.py).
Fornece conexão com bots do Telegram via BotFather, verificação getMe, persistência SQLite de sessões
e envio/recebimento de mensagens com acessibilidade para deficientes visuais.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("blind.channels.telegram")

# Expressão regular oficial do formato de token de bot do Telegram (clonado do Hermes)
TELEGRAM_BOT_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{30,}$")
TELEGRAM_API_BASE = "https://api.telegram.org"


@dataclass
class TelegramBotInfo:
    token: str
    bot_id: int
    username: str
    first_name: str
    connected_at: float
    status: str


class TelegramManager:
    """Gerenciador completo de bots do Telegram integrado ao Blind AI."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path(os.getcwd()) / "blind_channels.db"
        self._init_db()
        self._polling_tasks: Dict[str, asyncio.Task] = {}

    def _init_db(self) -> None:
        """Cria as tabelas de bots e mensagens no banco de dados SQLite."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_bots (
                    bot_id INTEGER PRIMARY KEY,
                    token TEXT NOT NULL,
                    username TEXT NOT NULL,
                    first_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    connected_at REAL NOT NULL,
                    last_active REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    direction TEXT NOT NULL,
                    text TEXT,
                    media_type TEXT,
                    file_id TEXT,
                    created_at REAL NOT NULL
                )
                """
            )
            # Garante colunas de midia em bancos ja existentes
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(telegram_messages)")
            cols = {row[1] for row in cur.fetchall()}
            if "media_type" not in cols:
                conn.execute("ALTER TABLE telegram_messages ADD COLUMN media_type TEXT")
            if "file_id" not in cols:
                conn.execute("ALTER TABLE telegram_messages ADD COLUMN file_id TEXT")
            conn.commit()

    @staticmethod
    def is_valid_token(token: str) -> bool:
        """Verifica se o token possui o formato estrito do Telegram."""
        return bool(TELEGRAM_BOT_TOKEN_RE.match(token.strip()))

    async def connect_bot(self, token: str) -> Dict[str, Any]:
        """
        Valida o token do bot através da chamada oficial getMe da API do Telegram.
        Salva as credenciais validadas no banco de dados.
        """
        token = token.strip()
        if not self.is_valid_token(token):
            raise ValueError("Token do Telegram com formato inválido. Deve ser no padrão ID:TOKEN_SECRETO gerado pelo @BotFather.")

        url = f"{TELEGRAM_API_BASE}/bot{token}/getMe"
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(url)
            except Exception as e:
                raise ConnectionError(f"Falha de rede ao conectar aos servidores do Telegram: {e}")

            if resp.status_code != 200:
                raise PermissionError("Token recusado pelo Telegram. Verifique se o bot está ativo no @BotFather.")

            data = resp.json()
            if not data.get("ok"):
                raise ValueError("Resposta inesperada da API do Telegram.")

            result = data.get("result", {})
            bot_id = result.get("id")
            username = result.get("username", "")
            first_name = result.get("first_name", "")
            now = time.time()

            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO telegram_bots (bot_id, token, username, first_name, status, connected_at, last_active)
                    VALUES (?, ?, ?, ?, 'connected', ?, ?)
                    ON CONFLICT(bot_id) DO UPDATE SET
                        token=excluded.token,
                        username=excluded.username,
                        first_name=excluded.first_name,
                        status='connected',
                        last_active=excluded.last_active
                    """,
                    (bot_id, token, username, first_name, now, now),
                )
                conn.commit()

            spoken_msg = f"Bot @{username} do Telegram conectado com sucesso!"
            logger.info(f"Bot Telegram @{username} (ID {bot_id}) conectado com sucesso.")

            # Inicia o polling automático de mensagens recebidas
            self.start_polling(token, bot_id)

            return {
                "status": "connected",
                "bot_id": bot_id,
                "username": username,
                "first_name": first_name,
                "spoken_message": spoken_msg,
            }

    def _get_bot_id_by_token(self, token: str) -> int | None:
        """Recupera o bot_id persistido para um token."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT bot_id FROM telegram_bots WHERE token = ?", (token,))
            row = cursor.fetchone()
            return row[0] if row else None

    async def send_message(self, token: str, chat_id: int | str, text: str) -> Dict[str, Any]:
        """Envia mensagem de texto via Telegram Bot API."""
        url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Erro ao enviar mensagem no Telegram: {resp.text}")

            bot_id = self._get_bot_id_by_token(token)
            if bot_id is not None:
                now = time.time()
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO telegram_messages (bot_id, chat_id, direction, text, created_at)
                        VALUES (?, ?, 'outbound', ?, ?)
                        """,
                        (bot_id, chat_id, text, now),
                    )
                    conn.commit()
            return resp.json()

    async def send_file(self, token: str, chat_id: int | str, path: str, kind: str = "document", caption: str = "") -> Dict[str, Any]:
        """Envia um arquivo ao chat: kind='voice' (mensagem de voz, .ogg opus) ou 'document'."""
        metodo, campo = ("sendVoice", "voice") if kind == "voice" else ("sendDocument", "document")
        url = f"{TELEGRAM_API_BASE}/bot{token}/{metodo}"
        data = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption[:1000]
        with open(path, "rb") as fh:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, data=data, files={campo: (Path(path).name, fh)})
        if resp.status_code != 200:
            raise RuntimeError(f"Erro ao enviar arquivo no Telegram: {resp.text[:200]}")
        bot_id = self._get_bot_id_by_token(token)
        if bot_id is not None:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO telegram_messages (bot_id, chat_id, direction, text, media_type, created_at) VALUES (?, ?, 'outbound', ?, ?, ?)",
                    (bot_id, chat_id, f"[{kind}] {Path(path).name}", kind, time.time()),
                )
                conn.commit()
        return resp.json()

    def get_connected_bots(self) -> List[Dict[str, Any]]:
        """Lista todos os bots configurados."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT bot_id, username, first_name, status, connected_at, last_active FROM telegram_bots")
            return [
                {
                    "bot_id": row[0],
                    "username": row[1],
                    "first_name": row[2],
                    "status": row[3],
                    "connected_at": row[4],
                    "last_active": row[5],
                }
                for row in cursor.fetchall()
            ]



    async def get_updates(self, token: str, offset: int | None = None) -> List[Dict[str, Any]]:
        """Busca atualizações pendentes do Telegram via long-polling."""
        url = f"{TELEGRAM_API_BASE}/bot{token}/getUpdates"
        params: Dict[str, Any] = {"limit": 100}
        if offset is not None:
            params["offset"] = offset
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                raise RuntimeError(f"Erro ao buscar atualizações do Telegram: {resp.text}")
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError("Resposta inesperada do Telegram ao buscar atualizações.")
            return data.get("result", [])

    def _store_update(self, bot_id: int, update: Dict[str, Any]) -> None:
        """Persiste uma mensagem recebida (texto, foto ou áudio/voz) no banco de dados."""
        message = update.get("message")
        if not message:
            return
        chat_id = message.get("chat", {}).get("id")
        if chat_id is None:
            return
        text = message.get("text") or message.get("caption")
        media_type: Optional[str] = None
        file_id: Optional[str] = None

        if message.get("photo"):
            photos = message["photo"]
            media_type = "photo"
            file_id = photos[-1].get("file_id") if isinstance(photos, list) and photos else None
            if not text:
                text = "[Foto recebida]"
        elif message.get("voice"):
            media_type = "voice"
            file_id = message["voice"].get("file_id")
            if not text:
                text = "[Áudio de voz recebido]"
        elif message.get("audio"):
            media_type = "audio"
            file_id = message["audio"].get("file_id")
            if not text:
                text = "[Arquivo de áudio recebido]"
        elif message.get("video") or message.get("video_note") or message.get("animation"):
            v = message.get("video") or message.get("video_note") or message.get("animation")
            media_type = "video"
            file_id = v.get("file_id")
            if not text:
                text = "[Video recebido]"
        elif message.get("document"):
            media_type = "document"
            file_id = message["document"].get("file_id")
            if not text:
                text = f"[Documento: {message['document'].get('file_name', 'arquivo')}]"

        if text is None and file_id is None:
            return
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO telegram_messages (bot_id, chat_id, direction, text, media_type, file_id, created_at)
                VALUES (?, ?, 'inbound', ?, ?, ?, ?)
                """,
                (bot_id, chat_id, text, media_type, file_id, now),
            )
            conn.commit()

    def get_default_token(self, bot_id: int | None = None) -> str:
        """Retorna o token do bot especificado ou do bot conectado mais recentemente."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if bot_id is not None:
                cursor.execute("SELECT token FROM telegram_bots WHERE bot_id = ?", (bot_id,))
            else:
                cursor.execute("SELECT token FROM telegram_bots ORDER BY last_active DESC LIMIT 1")
            row = cursor.fetchone()
            if not row or not row[0]:
                raise RuntimeError("Nenhum bot do Telegram conectado.")
            return row[0]

    async def download_file_bytes(self, file_id: str, bot_id: int | None = None) -> tuple[bytes, str]:
        """Baixa um arquivo (foto, voz, áudio ou documento) do Telegram pelo file_id."""
        token = self.get_default_token(bot_id)
        async with httpx.AsyncClient(timeout=20.0) as client:
            meta_resp = await client.get(f"{TELEGRAM_API_BASE}/bot{token}/getFile", params={"file_id": file_id})
            if meta_resp.status_code != 200:
                raise RuntimeError(f"Erro ao consultar arquivo no Telegram: {meta_resp.text}")
            file_path = (meta_resp.json().get("result") or {}).get("file_path")
            if not file_path:
                raise RuntimeError("Caminho do arquivo não retornado pelo Telegram.")
            dl_resp = await client.get(f"{TELEGRAM_API_BASE}/file/bot{token}/{file_path}")
            if dl_resp.status_code != 200:
                raise RuntimeError(f"Erro ao baixar mídia do Telegram: HTTP {dl_resp.status_code}")
            return dl_resp.content, file_path

    def handle_webhook_update(self, bot_id: int, update: Dict[str, Any]) -> None:
        """Processa uma atualização entregue via webhook pelo servidor."""
        self._store_update(bot_id, update)

    async def poll_once(self, token: str, bot_id: int, offset: int | None = None) -> int | None:
        """Executa um ciclo de polling e retorna o próximo offset."""
        updates = await self.get_updates(token, offset)
        for update in updates:
            self._store_update(bot_id, update)
        if updates:
            return max(u["update_id"] for u in updates) + 1
        return offset

    async def _polling_loop(self, token: str, bot_id: int) -> None:
        """Loop contínuo de long-polling para um bot."""
        from core.leader import leader_for

        leader = leader_for("telegram-polling")
        offset: int | None = None
        while True:
            try:
                # Um unico leitor por vez (Claude e Electron juntos brigariam pelas mesmas mensagens): so o dono le.
                if leader.try_acquire():
                    offset = await self.poll_once(token, bot_id, offset)
                else:
                    await asyncio.sleep(4)
            except Exception as e:
                logger.exception("Erro no polling do Telegram para bot %s: %s", bot_id, e)
            await asyncio.sleep(1)

    def start_polling(self, token: str, bot_id: int) -> None:
        """Inicia o polling de mensagens para um bot conectado."""
        self.stop_polling(token)
        task = asyncio.create_task(self._polling_loop(token, bot_id))
        self._polling_tasks[token] = task
        logger.info("Polling iniciado para bot Telegram %s", bot_id)

    def stop_polling(self, token: str) -> None:
        """Para o polling de mensagens para um bot."""
        task = self._polling_tasks.pop(token, None)
        if task and not task.done():
            task.cancel()

    def get_messages(
        self,
        bot_id: int | None = None,
        chat_id: int | str | None = None,
        direction: str | None = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Lista mensagens persistidas, opcionalmente filtradas por bot, chat ou direção."""
        query = "SELECT message_id, bot_id, chat_id, direction, text, media_type, file_id, created_at FROM telegram_messages WHERE 1=1"
        params: List[Any] = []
        if bot_id is not None:
            query += " AND bot_id = ?"
            params.append(bot_id)
        if chat_id is not None:
            query += " AND chat_id = ?"
            params.append(chat_id)
        if direction is not None:
            query += " AND direction = ?"
            params.append(direction)
        query += " ORDER BY message_id DESC LIMIT ?"
        params.append(limit)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [
                {
                    "message_id": row[0],
                    "bot_id": row[1],
                    "chat_id": row[2],
                    "direction": row[3],
                    "text": row[4],
                    "media_type": row[5],
                    "file_id": row[6],
                    "created_at": row[7],
                }
                for row in cursor.fetchall()
            ]


telegram_manager = TelegramManager()
