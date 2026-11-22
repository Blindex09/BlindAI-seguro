"""
Gerenciador de Sessões e Histórico de Conversas - Blind AI
Clonado e adaptado da arquitetura do Hermes Agent (hermes_state_sessions.py)
e OpenHands (conversation-local-storage).
Permite criar sessões temáticas, alternar entre conversas com histórico no SQLite
e herdar o contexto do que cada ferramenta (visão, fatura, documento, whatsapp) gerou.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("blind.sessions")


class SessionManager:
    """Gerencia conversas e mensagens com histórico persistente no SQLite."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path(os.getcwd()) / "blind_sessions.db"
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    text TEXT NOT NULL,
                    is_user INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
                )
                """
            )
            conn.commit()

    def create_session(self, title: str, source: str = "chat") -> Dict[str, Any]:
        session_id = f"sess_{uuid.uuid4().hex[:10]}"
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (id, title, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, title, source, now, now),
            )
            conn.commit()
        logger.info(f"Nova sessão criada: {session_id} - '{title}' (origem: {source})")
        return {"id": session_id, "title": title, "source": source, "created_at": now}

    def list_sessions(self, limit: int = 30) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT s.id, s.title, s.source, s.created_at, s.updated_at, COUNT(h.id) as msg_count
                FROM chat_sessions s
                LEFT JOIN chat_history h ON s.id = h.session_id
                GROUP BY s.id
                ORDER BY s.updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [
                {
                    "id": row[0],
                    "title": row[1],
                    "source": row[2],
                    "created_at": row[3],
                    "updated_at": row[4],
                    "message_count": row[5],
                }
                for row in cursor.fetchall()
            ]

    def add_message(self, session_id: str, sender: str, text: str, is_user: bool = False) -> None:
        try:
            from blind_mcp import cofre

            text = cofre.mascarar(text)  # historico guardado nao pode ficar com senha, chave, cartao ou CPF em texto
        except Exception:  # noqa: BLE001
            pass
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            # Garante que a sessão exista
            conn.execute(
                """
                INSERT OR IGNORE INTO chat_sessions (id, title, source, created_at, updated_at)
                VALUES (?, ?, 'auto', ?, ?)
                """,
                (session_id, text[:40].replace("\n", " ") or "Nova Conversa", now, now),
            )
            conn.execute(
                """
                INSERT INTO chat_history (session_id, sender, text, is_user, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, sender, text, 1 if is_user else 0, now),
            )
            conn.execute("UPDATE chat_sessions SET updated_at = ? WHERE id = ?", (now, session_id))
            conn.commit()

    def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, sender, text, is_user, created_at
                FROM chat_history
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            )
            return [
                {
                    "id": row[0],
                    "sender": row[1],
                    "text": row[2],
                    "is_user": bool(row[3]),
                    "created_at": row[4],
                }
                for row in cursor.fetchall()
            ]

    def delete_session(self, session_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
            conn.execute("DELETE FROM chat_history WHERE session_id = ?", (session_id,))
            conn.commit()
            return True


session_manager = SessionManager()
