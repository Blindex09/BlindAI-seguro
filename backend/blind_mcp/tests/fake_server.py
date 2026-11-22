"""Servidor MCP falso para testar o cliente do Blind AI sem depender de apps reais."""

import os
import time

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fake")


@mcp.tool()
def echo(text: str) -> str:
    """Devolve o texto recebido."""
    return text


@mcp.tool()
def add(a: int, b: int) -> int:
    """Soma dois inteiros."""
    return a + b


@mcp.tool()
def fail() -> str:
    """Sempre falha."""
    raise RuntimeError("boom")


@mcp.tool()
def slow(seconds: float) -> str:
    """Demora o tempo informado."""
    time.sleep(seconds)
    return "done"


@mcp.tool()
def big(n: int) -> str:
    """Resultado grande."""
    return "x" * n


@mcp.tool()
def secret(token: str) -> str:
    """Recebe segredo (escondida do modelo)."""
    return f"stored:{len(token)}"


@mcp.tool()
def blocked_tool() -> str:
    """Desabilitada no mcp.json."""
    return "nunca deve executar"


@mcp.tool()
def crash() -> str:
    """Derruba o processo do servidor."""
    os._exit(1)


if __name__ == "__main__":
    mcp.run()
