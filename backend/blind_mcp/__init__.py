"""Camada MCP do Blind AI: cliente que conecta servidores MCP externos e proprios."""

from .config import ServerSpec, load_specs
from .manager import MCPManager

__all__ = ["MCPManager", "ServerSpec", "load_specs"]
