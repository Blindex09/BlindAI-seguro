"""
Base Compartilhada para Oráculos Modulares - Blind AI
Utilizada por todos os oráculos específicos em tests/<modulo>/oracle_<modulo>.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

SERVER_URL = os.environ.get("BLIND_SERVER_URL", "http://127.0.0.1:8765")
DEFAULT_TIMEOUT = 90.0


class OracleAssertionError(Exception):
    """Exceção levantada quando um contrato de módulo falha."""
    pass


def ensure_mandatory_cloners(oracle_name: Optional[str] = None) -> Dict[str, Any]:
    """Compatibilidade legada para oráculos modulares."""
    return {"oracle": oracle_name or "oracle", "status": "ok"}


def log(prefix: str, msg: str):
    print(f"[{prefix}] {msg}", flush=True)


def request_json(
    endpoint: str,
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    url = f"{SERVER_URL}{endpoint}"
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    body_bytes = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content) if content.strip() else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise OracleAssertionError(
            f"HTTP {e.code} em {method} {endpoint}.\nDetalhe: {err_body}"
        ) from e
    except Exception as e:
        raise OracleAssertionError(f"Falha de conexão em {method} {endpoint}: {e}") from e

