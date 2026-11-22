"""ver_imagem entrega a imagem ao modelo da conversa, sem depender de chave de visao."""

import asyncio

import pytest
from PIL import Image as PILImage

from blind_mcp.servers import docs


def test_ver_imagem_devolve_texto_e_imagem_reduzida(tmp_path):
    f = tmp_path / "foto.png"
    PILImage.new("RGB", (3000, 2000), (200, 50, 50)).save(f)
    r = asyncio.run(docs.ver_imagem(str(f), "quantas pessoas?"))
    assert "quantas pessoas?" in r[0].text and "rosto" in r[0].text
    assert r[1].type == "image" and r[1].mimeType == "image/jpeg"  # JPEG
    with pytest.raises(ValueError):
        asyncio.run(docs.ver_imagem(str(tmp_path / "nao-existe.png")))
