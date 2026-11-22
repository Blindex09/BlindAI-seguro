"""
Testes unitários para o OpenCode ACP Bridge do Blind AI.
Verifica a detecção de binários do OpenCode, listagem de modelos free e chamadas mockadas.
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
from core.providers.opencode_acp_bridge import OpenCodeAcpBridge


@pytest.fixture
def bridge():
    return OpenCodeAcpBridge()


def test_find_opencode_executable(bridge):
    """Verifica se o executável do OpenCode instalado na máquina é localizado."""
    exe = bridge.find_executable()
    # O OpenCode está instalado no ambiente Windows
    if exe:
        assert "opencode" in exe.lower()
        assert bridge.is_available() is True


def test_known_free_models(bridge):
    """Verifica que a lista de modelos free do OpenCode contém os modelos esperados."""
    models = bridge.get_known_free_models()
    assert len(models) >= 5
    ids = [m["id"] for m in models]
    assert "opencode/deepseek-v4.1-flash-free" in ids
    assert "opencode/glm-5.3-flash-free" in ids


@pytest.mark.asyncio
async def test_prompt_missing_executable():
    """Verifica que quando o executável não existe, retorna erro claro."""
    bridge_missing = OpenCodeAcpBridge()
    with patch.object(bridge_missing, "find_executable", return_value=None):
        res = await bridge_missing.prompt("Olá")
        assert res["status"] == "error"
        assert "não foi localizado" in res["reply"]
