"""Base compartilhada de `blind-mail` e `blind-drive`: credencial Google, token e utilitarios.

Permissoes pedidas ao Google (e nada alem disso):
- gmail.readonly: ler e buscar e-mails, baixar anexos.
- gmail.send: enviar e-mail (nunca apaga, nunca altera caixa).
- drive.readonly: listar e baixar arquivos do Drive.
- drive.file: subir arquivos novos (so enxerga o que o Blind criou).
Enviar e-mail e subir arquivo exigem DUAS etapas: 1) prepara e devolve um codigo; 2) so apos o "sim" da pessoa, reenvia com o codigo.

Configuracao (uma vez): salve o arquivo de credencial OAuth ("app para computador") em
<BLIND_DATA_DIR>/google/client_secret.json e peca `google_conectar`. O token fica em <BLIND_DATA_DIR>/google/token.json.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Dict

from ._common import BACKEND_DIR

DATA_DIR = Path(os.environ.get("BLIND_DATA_DIR") or (BACKEND_DIR / "data"))
GOOGLE_DIR = DATA_DIR / "google"
CLIENT_FILE = GOOGLE_DIR / "client_secret.json"
TOKEN_FILE = GOOGLE_DIR / "token.json"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
]
MAX_ATTACH_BYTES = 20 * 1024 * 1024  # limite do Gmail e margem de seguranca
PENDING_TTL = 600.0
_PENDING: Dict[str, Dict[str, Any]] = {}
DOWNLOAD_DIR = Path(os.environ.get("BLIND_DOWNLOAD_DIR") or (Path.home() / "Downloads" / "Blind"))


class GoogleNaoConfigurado(RuntimeError):
    pass


def _credentials() -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not TOKEN_FILE.exists():
        raise GoogleNaoConfigurado(
            "Google ainda nao conectado. Peca para a pessoa autorizar com google_conectar"
            + ("" if CLIENT_FILE.exists() else f" (antes, salve client_secret.json em {GOOGLE_DIR})") + "."
        )
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    if not creds.valid:
        raise GoogleNaoConfigurado("A autorizacao do Google venceu. Peca para a pessoa refazer com google_conectar.")
    return creds


def _service(name: str, version: str) -> Any:
    from googleapiclient.discovery import build

    return build(name, version, credentials=_credentials(), cache_discovery=False)


def _prune() -> None:
    for k in [k for k, v in _PENDING.items() if time.time() - v["criado"] > PENDING_TTL]:
        del _PENDING[k]


def _safe_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name or "arquivo").strip(" .") or "arquivo"
    return cleaned[:150]


def _unique_path(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / _safe_name(name)
    n = 1
    while p.exists():  # nunca sobrescreve
        p = folder / f"{p.stem.split(' (')[0]} ({n}){p.suffix}"
        n += 1
    return p


def _status_sync() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": True,
        "credencial_presente": CLIENT_FILE.exists(),
        "autorizado": TOKEN_FILE.exists(),
        "pasta": str(GOOGLE_DIR),
        "permissoes": ["ler e enviar e-mail (nunca apaga)", "listar e baixar do Drive", "subir arquivos novos ao Drive"],
    }
    if TOKEN_FILE.exists():
        try:
            svc = _service("gmail", "v1")
            out["conta"] = svc.users().getProfile(userId="me").execute().get("emailAddress")
        except Exception as exc:  # noqa: BLE001
            out["aviso"] = f"Token existe mas nao funcionou: {exc}"
            out["autorizado"] = False
    if not out["credencial_presente"]:
        out["proximo_passo"] = ("Falta o arquivo client_secret.json em " + str(GOOGLE_DIR)
                                + ". Veja GOOGLE.md: crie a credencial no Google Cloud (tipo 'App para computador').")
    elif not out["autorizado"]:
        out["proximo_passo"] = "Peca google_conectar: abre o navegador para a pessoa autorizar."
    return out


def _connect_sync() -> Dict[str, Any]:
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CLIENT_FILE.exists():
        raise GoogleNaoConfigurado(f"Falta {CLIENT_FILE}. Veja GOOGLE.md para criar a credencial.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
    creds = flow.run_local_server(port=0, timeout_seconds=300, open_browser=True,
                                  authorization_prompt_message="", success_message="Blind autorizado. Pode fechar esta aba.")
    GOOGLE_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return _status_sync()
