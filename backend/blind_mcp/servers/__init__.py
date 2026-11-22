"""Servidores MCP proprios do Blind AI (cada um roda como processo separado via stdio)."""


# Modelos de IA (e o proprio Claude) mandam numeros onde o parametro e texto (pages=2, text=42). O pydantic do FastMCP
# recusa int -> str por padrao; aqui ele passa a converter. Precisa rodar ANTES de qualquer @mcp.tool(), por isso fica no
# __init__ do pacote, que o Python carrega antes de cada servidor.
try:
    from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase

    ArgModelBase.model_config = {**ArgModelBase.model_config, "coerce_numbers_to_str": True}
except Exception:  # noqa: BLE001 - se o SDK mudar, so perde a tolerancia
    pass
