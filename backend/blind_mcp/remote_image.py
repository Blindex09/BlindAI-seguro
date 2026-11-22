"""describe_image no gateway remoto: a imagem vai ao proprio Claude, que a descreve. Nenhuma chave de IA entra.

No Blind local, `describe_image` chama um modelo de visao com a chave guardada no computador. Atras de um conector MCP quem
descreve e o Claude da conversa (como em `ver_imagem`), entao o gateway so entrega a imagem, reduzida, junto com a nota.
"""

from __future__ import annotations

import base64
import binascii
import io
from typing import Any, List, Optional

import mcp.types as types

MAX_BYTES = 30 * 1024 * 1024
SCHEMA = {
    "type": "object",
    "properties": {
        "image_base64": {"type": "string", "description": "A imagem (PNG, JPEG, WebP...) em base64."},
        "url": {"type": "string", "description": "Link publico (http ou https) da imagem na web. Alternativa ao base64."},
        "prompt": {"type": "string", "description": "O que a pessoa quer saber sobre a imagem (opcional)."},
    },
}
DESCRICAO = (
    "Entrega uma imagem ao Claude para ele descrever para uma pessoa cega. Sem chave de IA. "
    "A imagem vai em base64 ou por link publico da web; caminho de arquivo nao e aceito."
)


def preparar(image_base64: str) -> bytes:
    """Decodifica, confere que e uma imagem e reduz para no maximo 1568 px, em JPEG."""
    from PIL import Image as PILImage

    raw = (image_base64 or "").strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("A imagem nao esta em base64 valido.") from exc
    if not data:
        raise ValueError("Nenhuma imagem foi enviada.")
    if len(data) > MAX_BYTES:
        raise ValueError("A imagem e grande demais (mais de 30 MB).")
    try:
        with PILImage.open(io.BytesIO(data)) as im:
            im = im.convert("RGB")
            im.thumbnail((1568, 1568))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=85)
            return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Nao consegui abrir como imagem: {type(exc).__name__}.") from exc


def entregar(image_base64: str, prompt: Optional[str] = None) -> List[Any]:
    jpeg = preparar(image_base64)
    nota = (
        "Imagem entregue para voce descrever para uma pessoa cega. "
        + (f"Pergunta da pessoa: {prompt}" if prompt else "Sem pergunta especifica: descreva na ordem do que importa.")
        + " Diga que a descricao e sua e pode errar; nao identifique ninguem pelo rosto."
    )
    return [
        types.TextContent(type="text", text=nota),
        types.ImageContent(type="image", data=base64.b64encode(jpeg).decode("ascii"), mimeType="image/jpeg"),
    ]
