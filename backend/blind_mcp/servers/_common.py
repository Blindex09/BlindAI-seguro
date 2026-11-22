"""Utilitarios compartilhados pelos servidores MCP proprios do Blind AI."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Callable, Dict

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

# Mesmo bootstrap de caminhos do server.py, para os modulos de core/ resolverem imports.
for _p in (BACKEND_DIR, BACKEND_DIR / "core", BACKEND_DIR / "core" / "utils"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _call_with_com(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """UI Automation e SAPI usam COM, que precisa ser inicializado em cada thread do pool."""
    try:
        import pythoncom

        pythoncom.CoInitialize()
    except Exception:  # noqa: BLE001 - sem pywin32 (ex.: testes): segue sem COM
        return fn(*args, **kwargs)
    try:
        return fn(*args, **kwargs)
    finally:
        pythoncom.CoUninitialize()


async def run_blocking(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Executa codigo bloqueante (CLI, UIA, COM) fora do loop para o servidor continuar respondendo."""
    return await asyncio.to_thread(_call_with_com, fn, *args, **kwargs)


def unwrap_bridge(result: Dict[str, Any]) -> Any:
    """agent-desktop devolve {ok, data|error}. Erro vira excecao, que o MCP marca como isError."""
    if result.get("ok"):
        return result.get("data", result)
    err = result.get("error") or {}
    raise RuntimeError(f"{err.get('code', 'ERROR')}: {err.get('message', 'falha desconhecida')}")
