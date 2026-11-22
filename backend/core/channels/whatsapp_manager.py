"""
Gerenciador de Canal WhatsApp - Blind AI
Clonado e adaptado da arquitetura do OpenBot (packages/whatsapp e src/backend/messaging/whatsapp).
Implementa o fluxo de pareamento por código de 8 dígitos (Baileys Signal Protocol)
sem exigência de leitura de QR Code visual, garantindo acessibilidade total a pessoas com deficiência visual.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("blind.channels.whatsapp")

# Caracteres padrão Base-32 Crockford utilizados pelo protocolo Baileys/WhatsApp para pairing codes
PAIRING_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


@dataclass
class WhatsAppSession:
    phone: str
    jid: str
    pairing_code: str
    status: str  # "waiting_link", "paired", "disconnected"
    created_at: float
    last_active: float


class WhatsAppManager:
    """Gerencia conexões e sessões de WhatsApp com foco em acessibilidade."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path(os.getcwd()) / "blind_channels.db"
        self._init_db()

    def _init_db(self) -> None:
        """Inicializa as tabelas de sessão no banco SQLite local."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS whatsapp_sessions (
                    phone TEXT PRIMARY KEY,
                    jid TEXT NOT NULL,
                    pairing_code TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_active REAL NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def normalize_phone(phone: str) -> str:
        """Normaliza o número de telefone para o padrão internacional E.164 (sem símbolos)."""
        clean = re.sub(r"[^\d]", "", phone.strip())
        # Se for número brasileiro sem DDI 55 (ex: 11999998888 ou 1188887777), adiciona 55
        if len(clean) in (10, 11) and not clean.startswith("55"):
            clean = "55" + clean
        return clean

    @staticmethod
    def to_jid(phone: str) -> str:
        """Converte número normalizado para o JID oficial do WhatsApp."""
        return f"{phone}@s.whatsapp.net"

    def generate_pairing_code(self, phone: str) -> str:
        """
        Gera um código de pareamento de 8 caracteres no padrão Baileys.
        Utiliza amostragem criptograficamente segura ou pseudoaleatória sobre o alfabeto Base-32.
        """
        import secrets

        return "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))

    # ------------------------------ conector real (Baileys, em Node) ------------------------------
    BRIDGE_DIR = Path(__file__).resolve().parent.parent.parent / "channels" / "whatsapp_bridge"

    @staticmethod
    def _data_dir() -> Path:
        return Path(os.environ.get("BLIND_DATA_DIR") or (Path(__file__).resolve().parent.parent.parent / "data")) / "whatsapp"

    def bridge_command(self) -> Optional[list]:
        """Comando que sobe o conector, ou None se nao der (Node ou dependencias ausentes)."""
        override = os.environ.get("BLIND_WHATSAPP_BRIDGE_CMD")  # testes: um servidor falso
        if override:
            return override.split("|")
        import shutil

        node = shutil.which("node")
        if node and (self.BRIDGE_DIR / "node_modules" / "@whiskeysockets" / "baileys").exists():
            return [node, str(self.BRIDGE_DIR / "bridge.js")]
        return None

    def _bridge_info(self) -> Optional[Dict[str, Any]]:
        """Porta e token do conector que ja esta rodando (de qualquer copia do Blind), se responder."""
        import httpx

        try:
            info = json.loads((self._data_dir() / "bridge.json").read_text(encoding="utf-8"))
            r = httpx.get(f"http://127.0.0.1:{info['port']}/health", headers={"Authorization": f"Bearer {info['token']}"}, timeout=2)
            return info if r.status_code == 200 else None
        except Exception:  # noqa: BLE001
            return None

    def _spawn_bridge(self) -> Dict[str, Any]:
        import secrets
        import subprocess
        import threading

        cmd = self.bridge_command()
        if not cmd:
            raise RuntimeError(
                "O conector do WhatsApp nao esta instalado. Precisa do Node e de: cd backend/channels/whatsapp_bridge && npm install. "
                "Nenhum codigo foi gerado."
            )
        data = self._data_dir()
        (data / "session").mkdir(parents=True, exist_ok=True)
        token = secrets.token_hex(16)
        env = dict(os.environ, BLIND_WA_TOKEN=token, BLIND_WA_PARENT_PID=str(os.getpid()))
        proc = subprocess.Popen(
            cmd + ["--session", str(data / "session"), "--port", "0"],
            cwd=str(self.BRIDGE_DIR), env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._bridge_proc = proc
        box: Dict[str, Any] = {}

        def reader() -> None:
            try:
                box["line"] = proc.stdout.readline()
            except Exception:  # noqa: BLE001
                pass

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(25)
        try:
            port = int(json.loads(box.get("line") or "{}")["port"])
        except Exception:  # noqa: BLE001
            proc.kill()
            raise RuntimeError("O conector do WhatsApp nao iniciou a tempo. Tente de novo.")
        info = {"port": port, "token": token, "pid": proc.pid}
        (data / "bridge.json").write_text(json.dumps(info), encoding="utf-8")
        return info

    def _ensure_bridge(self) -> Dict[str, Any]:
        """Usa o conector que ja roda (de qualquer copia) ou sobe um. So uma copia sobe por vez (trava de dono)."""
        info = self._bridge_info()
        if info:
            return info
        from core.leader import leader_for

        lock = leader_for("whatsapp-spawn")
        deadline = time.time() + 30
        while time.time() < deadline:
            if lock.try_acquire():
                try:
                    return self._bridge_info() or self._spawn_bridge()
                finally:
                    lock.release()
            time.sleep(1)  # outra copia esta subindo o conector: espera ele aparecer
            info = self._bridge_info()
            if info:
                return info
        raise RuntimeError("Outra copia do Blind esta iniciando o WhatsApp e nao terminou. Tente de novo em instantes.")

    def _bridge_call(self, method: str, path: str, body: Optional[dict] = None, timeout: float = 45.0) -> Dict[str, Any]:
        import httpx

        info = self._ensure_bridge()
        r = httpx.request(method, f"http://127.0.0.1:{info['port']}{path}", json=body,
                          headers={"Authorization": f"Bearer {info['token']}"}, timeout=timeout)
        try:
            data = r.json()
        except Exception:  # noqa: BLE001
            data = {"ok": False, "error": r.text[:200]}
        if r.status_code >= 400 or not data.get("ok", True):
            raise RuntimeError(data.get("error") or f"O conector do WhatsApp respondeu erro {r.status_code}.")
        return data

    def _save(self, phone: str, jid: str, code: str, status: str) -> None:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO whatsapp_sessions (phone, jid, pairing_code, status, created_at, last_active)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(phone) DO UPDATE SET pairing_code=excluded.pairing_code, status=excluded.status,
                    last_active=excluded.last_active
                """,
                (phone, jid, code, status, now, now),
            )
            conn.commit()

    def start_pairing(self, raw_phone: str) -> Dict[str, Any]:
        """
        Pareia o WhatsApp pelo conector REAL (Baileys): o codigo de 8 caracteres vem do proprio WhatsApp e vale por poucos
        minutos. Sem o conector instalado, devolve erro claro e NAO gera codigo.
        """
        phone = self.normalize_phone(raw_phone)
        if len(phone) < 10:
            raise ValueError("Número de telefone inválido. Informe o DDD e o número completo.")
        jid = self.to_jid(phone)

        if os.environ.get("BLIND_WHATSAPP_SIMULADO"):
            # Modo de teste: codigo ALEATORIO gerado aqui (o WhatsApp o recusa). Nunca usar com pessoas.
            code = self.generate_pairing_code(phone)
            self._save(phone, jid, code, "waiting_link")
            return {"status": "waiting_link", "phone": phone, "jid": jid, "code": code,
                    "spoken_instructions": "MODO DE TESTE: codigo falso.", "simulated": True}

        res = self._bridge_call("POST", "/pair", {"phone": phone}, timeout=45)
        if res.get("status") == "connected":
            self._save(phone, jid, "", "paired")
            return {"status": "paired", "phone": phone, "jid": jid, "code": "",
                    "spoken_instructions": "Este WhatsApp ja esta conectado ao Blind AI."}
        code = str(res.get("code") or "")
        self._save(phone, jid, code, "waiting_link")
        spelled = " ".join(list(code))
        return {
            "status": "waiting_link",
            "phone": phone,
            "jid": jid,
            "code": code,
            "spoken_instructions": (
                f"Seu código de pareamento do WhatsApp é: {spelled}. "
                "Abra o WhatsApp no celular, toque em Aparelhos Conectados, depois em Conectar aparelho, "
                "Conectar com número de telefone, e digite este código. Ele vale por poucos minutos."
            ),
        }

    def get_status(self, raw_phone: str) -> Dict[str, Any]:
        """Estado da sessao. Se o conector estiver rodando, pergunta a ele (verdade); senao, o ultimo estado guardado."""
        phone = self.normalize_phone(raw_phone)
        live: Optional[Dict[str, Any]] = None
        if self._bridge_info():
            try:
                live = self._bridge_call("GET", "/status", timeout=5)
            except Exception:  # noqa: BLE001
                live = None
        mapped = None
        if live:
            mapped = {"connected": "paired", "logged_out": "disconnected"}.get(live.get("status"), live.get("status"))
            if live.get("phone") in ("", phone) or live.get("status") != "connected":
                self._save(phone, self.to_jid(phone), live.get("pairing_code") or "", mapped or "waiting_link")
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT phone, jid, pairing_code, status, last_active FROM whatsapp_sessions WHERE phone = ?", (phone,)
            ).fetchone()
        if not row:
            return {"status": "not_found", "phone": phone}
        out = {"status": mapped or row[3], "phone": row[0], "jid": row[1], "pairing_code": row[2], "last_active": row[4]}
        if live:
            out["conector"] = {"estado": live.get("status"), "erro": live.get("error", "")}
        else:
            # Sem conector rodando nada e "ao vivo": um codigo guardado ja nao vale e "pareado" so sera confirmado ao religar.
            out["pairing_code"] = ""
            out["conector"] = {"estado": "desligado", "erro": ""}
            if out["status"] == "waiting_link":
                out["status"] = "expired"
        return out

    def messages(self, limit: int = 20) -> Dict[str, Any]:
        return self._bridge_call("GET", f"/messages?limit={int(limit)}", timeout=10)

    def contacts(self) -> list:
        """Agenda do WhatsApp da pessoa (nomes salvos no celular), guardada pelo conector neste computador."""
        return self._bridge_call("GET", "/contacts", timeout=10).get("contatos", [])

    def send_text(self, text: str, phone: str = "", jid: str = "") -> Dict[str, Any]:
        """Envia texto pelo conector real. Aceita o numero (DDI+DDD) ou o jid de quem escreveu (resposta)."""
        body: Dict[str, Any] = {"text": text}
        if jid:
            body["jid"] = jid
        else:
            body["phone"] = self.normalize_phone(phone)
        return self._bridge_call("POST", "/send", body, timeout=30)

    def send_media(self, jid: str, path: str, kind: str = "document", caption: str = "", filename: str = "") -> Dict[str, Any]:
        """Envia audio (kind='audio', .ogg opus) ou arquivo para a conversa da propria pessoa (o conector recusa outro destino)."""
        import mimetypes

        body = {"jid": jid, "path": path, "kind": kind, "caption": caption, "filename": filename or Path(path).name,
                "mimetype": mimetypes.guess_type(path)[0] or "application/octet-stream"}
        return self._bridge_call("POST", "/send_media", body, timeout=60)

    def logout(self) -> Dict[str, Any]:
        return self._bridge_call("POST", "/logout", {}, timeout=15)


whatsapp_manager = WhatsAppManager()
