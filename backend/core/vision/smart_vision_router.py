"""
Módulo de Roteamento Inteligente de Visão (Smart Vision Router) - Blind AI
Clonado e adaptado da arquitetura do Hermes (vision_message_prep.py) e OpenBot (agent-providers.ts / tool-router).

Garante que qualquer imagem ou captura de tela enviada pelo usuário seja SEMPRE
roteada automaticamente para um modelo multimodal com capacidade de visão,
sem que o usuário precise trocar manualmente de modelo ou receba avisos de erro.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import re
from typing import List, Optional, Tuple

import httpx

from core.desktop.desktop_controller import desktop_controller


def sanitize_screen_reader_text(text: str) -> str:
    """Higieniza o texto removendo asteriscos, crases, hashtags e markdown que poluem leitores de tela."""
    if not text:
        return ""
    import re
    t = re.sub(r"\*+", "", text)
    t = re.sub(r"```[\w]*\n?", "", t)
    t = re.sub(r"`+", "", t)
    t = re.sub(r"^#+\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

logger = logging.getLogger("blind.vision_router")

# Regras de descricao para pessoa cega (pesquisa: Be My Eyes, Perkins, RNIB, W3C; ver blind_mcp/habilidades/descrevendo-imagens.md).
PROMPT_PADRAO = (
    "Você descreve imagens para uma pessoa cega, em português do Brasil, para ser lido em voz alta. "
    "Comece pelo tipo e o assunto em uma frase (foto, captura de tela, gráfico, documento...). Depois só o que ajuda a entender: "
    "ações, lugar, objetos principais e, se importar, cores. Se houver texto, leia palavra por palavra. "
    "Se houver pessoas, descreva o que se vê: quantas são, o que fazem, roupas, cabelo, idade aproximada e expressão, "
    "usando 'parece' quando houver dúvida. Isso é uma descrição de acessibilidade para quem não enxerga: não se recuse a descrever. "
    "Não identifique ninguém pelo rosto nem invente nomes; use um nome só se ele aparecer escrito na imagem ou nesta conversa. "
    "Se a imagem estiver borrada, escura, clara demais, cortada ou de lado, diga isso e o que não deu para ver. "
    "Não invente nada que não esteja na imagem. Seja curto: no máximo cinco frases, e termine oferecendo mais detalhe. "
    "Sem asteriscos, listas, emojis nem introdução como 'a imagem mostra'."
)
REGRAS_EXTRA = (
    " Se houver pessoas, descreva o que se vê (ações, roupas, expressão) sem identificar ninguém pelo rosto e sem se recusar: "
    "é para uma pessoa cega. Se a imagem estiver ruim, diga. Não invente."
)

_RECUSA = re.compile(
    r"(n[aã]o posso (identificar|descrever|ajudar|analisar|fornecer)|n[aã]o consigo (identificar|descrever|ajudar|analisar)|"
    r"desculpe[,.]? (mas )?n[aã]o|i (can'?t|cannot|am unable to|'m unable to|'m sorry,? but i can)|"
    r"i'?m sorry,? (but )?i can|sorry,? i can'?t|n[aã]o tenho (permiss[aã]o|autoriza)|as an ai)",
    re.IGNORECASE,
)


def parece_recusa(texto: str) -> bool:
    """Resposta curta que e uma recusa ('nao posso identificar pessoas...') em vez de uma descricao."""
    t = (texto or "").strip()
    return bool(t) and len(t) < 400 and bool(_RECUSA.search(t))

# Conjunto de palavras-chave indicativas de modelos com suporte nativo a visão/imagem
VISION_KEYWORDS = {
    "vision", "vl", "-vl", "4o", "4-o", "flash", "gemini",
    "llava", "bakllava", "minicpm", "moondream", "claude-3"
}

# Modelos estritamente textuais mapeados para seus substitutos com visão
VISION_FALLBACK_MAP = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o",
}


class SmartVisionRouter:
    """Roteador inteligente de capacidades multimodais e audiodescrição."""

    def is_vision_model(self, model: Optional[str]) -> bool:
        """Verifica se o identificador do modelo possui suporte nativo a processamento de imagens."""
        if not model:
            return False
        m_lower = model.lower()
        # Modelos textuais conhecidos que NÃO suportam visão
        text_only = {"gpt-3.5-turbo"}
        if m_lower in text_only:
            return False

        return any(k in m_lower for k in VISION_KEYWORDS)

    async def resolve_vision_route(
        self,
        provider: str,
        requested_model: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Roteia automaticamente a requisição para o melhor provedor e modelo com capacidade visual.
        Se o modelo atual for de texto puro, faz o switch silencioso para o modelo de visão correspondente.
        """
        prov = (provider or "auto").lower()
        model = requested_model or ""

        # 1. Se o modelo atual já é de visão, mantém
        if self.is_vision_model(model):
            return prov, model

        # 2. Roteamento por provedor
        if prov == "gemini":
            return "gemini", "gemini-2.5-flash"

        if prov == "openai":
            return "openai", "gpt-4o"

        return "gemini", "gemini-2.5-flash"

    def describe_screen_via_uia(self) -> str:
        """
        Gera uma audiodescrição precisa, rica e acessível (W3C WAI) da tela atual diretamente
        pela Árvore de Acessibilidade nativa do Windows (UI Automation).
        Funciona 100% offline e sem necessidade de conexão com a nuvem.
        """
        insp = desktop_controller.inspect_window(None)
        win_title = insp.get("window", "Área de Trabalho")
        elements = insp.get("elements", [])

        # Classifica os elementos por papel
        buttons = [e['name'] for e in elements if e['type'] == 'button' and e['name']]
        edits = [e['name'] for e in elements if e['type'] == 'edit' and e['name']]
        listitems = [e['name'] for e in elements if e['type'] == 'listitem' and e['name']]
        radios = [e['name'] for e in elements if e['type'] == 'radio' and e['name']]
        combos = [e['name'] for e in elements if e['type'] == 'combobox' and e['name']]

        lines = [
            f"A imagem mostra a tela do computador com a janela do aplicativo {win_title} aberta em primeiro plano.",
            "Trata-se de uma interface de aplicativo para desktop com botões, campos de texto e listas organizados de forma acessível."
        ]

        if listitems:
            lines.append("Na área de navegação e conversas, estão listados os seguintes itens:")
            for item in listitems[:10]:
                lines.append(f"- {item}")

        if edits:
            lines.append(f"Há campos de texto disponíveis para digitação, incluindo: {', '.join(edits[:4])}.")

        if buttons:
            lines.append(f"Os botões de comando visíveis na interface são: {', '.join(buttons[:8])}.")

        if radios:
            lines.append(f"Opções de filtro disponíveis: {', '.join(radios)}.")

        return "\n\n".join(lines)

    def describe_image_via_pillow(self, img_bytes: bytes) -> str:
        """Extrai metadados estruturais da imagem caso nenhum modelo neural esteja disponível."""
        try:
            from PIL import Image
            with Image.open(io.BytesIO(img_bytes)) as img:
                w, h = img.size
                fmt = img.format or "imagem"
                mode = img.mode
                aspect = "paisagem (horizontal)" if w > h else ("retrato (vertical)" if h > w else "quadrada")
                return (
                    f"Trata-se de uma {fmt} digital em orientação {aspect}, com resolução de {w} por {h} pixels "
                    f"e padrão de cor {mode}. A imagem foi processada e armazenada com sucesso no histórico da conversa."
                )
        except Exception:
            return "Imagem processada e anexada ao contexto da conversa com sucesso."

    async def describe_multimodal(
        self,
        image_base64: Optional[str] = None,
        file_path: Optional[str] = None,
        provider: str = "auto",
        requested_model: Optional[str] = None,
        api_key: Optional[str] = None,
        prompt_override: Optional[str] = None,
        captura_de_tela: bool = False,
    ) -> str:
        """
        Executa a cadeia de resiliência multimodal com auto-roteamento transparente.
        Garante que NUNCA retorne o erro 'modelo não suporta visão'.
        """
        # 1. Decodifica a imagem para bytes e base64 limpo
        raw_b64 = ""
        mime_type = "image/png"
        img_bytes = b""

        if image_base64:
            clean = image_base64.strip()
            if "," in clean:
                header, clean = clean.split(",", 1)
                if "jpeg" in header or "jpg" in header:
                    mime_type = "image/jpeg"
                elif "webp" in header:
                    mime_type = "image/webp"
            raw_b64 = clean
            try:
                img_bytes = base64.b64decode(raw_b64)
            except Exception:
                img_bytes = b""

        elif file_path and os.path.exists(file_path):
            try:
                with open(file_path, "rb") as f:
                    img_bytes = f.read()
                raw_b64 = base64.b64encode(img_bytes).decode("utf-8")
                if file_path.lower().endswith((".jpg", ".jpeg")):
                    mime_type = "image/jpeg"
                elif file_path.lower().endswith(".webp"):
                    mime_type = "image/webp"
            except Exception:
                pass

        # Otimiza capturas de tela grandes (>300 KB ou >1280px) para JPEG compacto para envio rápido
        if img_bytes and len(img_bytes) > 300 * 1024:
            try:
                from PIL import Image
                with Image.open(io.BytesIO(img_bytes)) as im:
                    im_rgb = im.convert("RGB")
                    im_rgb.thumbnail((1280, 1280))
                    out_buf = io.BytesIO()
                    im_rgb.save(out_buf, format="JPEG", quality=82, optimize=True)
                    img_bytes = out_buf.getvalue()
                    raw_b64 = base64.b64encode(img_bytes).decode("utf-8")
                    mime_type = "image/jpeg"
            except Exception:
                pass

        # 2. Resolução do modelo com auto-roteamento inteligente
        target_provider, target_model = await self.resolve_vision_route(provider, requested_model)
        logger.info(f"Auto-roteamento de visão: [{provider}/{requested_model}] -> [{target_provider}/{target_model}]")

        prompt = (prompt_override + REGRAS_EXTRA) if prompt_override else PROMPT_PADRAO

        description = ""
        recusas: List[str] = []

        def _filtrar() -> None:
            """Se o modelo respondeu com uma recusa, descarta e deixa o proximo modelo tentar."""
            nonlocal description
            if description and parece_recusa(description):
                recusas.append(description)
                description = ""

        # Tier 0: Ollama Cloud Vision (kimi-k2.7-code) se OLLAMA_API_KEY estiver configurada
        ollama_key = os.getenv("OLLAMA_API_KEY", "").strip()
        if not description and ollama_key and raw_b64:
            try:
                payload = {
                    "model": "kimi-k2.7-code",
                    "messages": [
                        {"role": "system", "content": "Você é o Blind AI, especialista de audiodescrição acessível W3C WAI. Nunca use asteriscos nem formatação markdown decorativa."},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{raw_b64}"}}
                            ]
                        }
                    ],
                    "temperature": 0.2
                }
                async with httpx.AsyncClient(timeout=25.0) as client:
                    resp = await client.post("https://ollama.com/v1/chat/completions", json=payload, headers={"Authorization": f"Bearer {ollama_key}"})
                    if resp.status_code == 200:
                        data = resp.json()
                        description = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            except Exception as e:
                logger.debug(f"Falha Ollama Cloud Vision: {e}")

        _filtrar()

        # Tier 1: Google Gemini Vision (se API Key configurada)
        if not description and (target_provider == "gemini" or api_key or os.getenv("GEMINI_API_KEY")):
            key = api_key or os.getenv("GEMINI_API_KEY", "")
            if key and raw_b64:
                try:
                    gemini_url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
                    payload = {
                        "model": "gemini-2.5-flash",
                        "messages": [
                            {"role": "system", "content": "Você é o Blind AI, especialista de audiodescrição acessível W3C WAI. Nunca use asteriscos nem formatação markdown decorativa."},
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{raw_b64}"}}
                                ]
                            }
                        ],
                        "temperature": 0.2
                    }
                    async with httpx.AsyncClient(timeout=45.0) as client:
                        resp = await client.post(gemini_url, json=payload, headers={"Authorization": f"Bearer {key}"})
                        if resp.status_code == 200:
                            data = resp.json()
                            description = data["choices"][0]["message"]["content"]
                except Exception as e:
                    logger.debug(f"Falha Gemini Vision: {e}")

        _filtrar()

        # Tier 2: OpenAI GPT-4o Vision (se API Key configurada)
        if not description and (target_provider == "openai" or (api_key and "sk-" in api_key) or os.getenv("OPENAI_API_KEY")):
            key = api_key or os.getenv("OPENAI_API_KEY", "")
            if key and raw_b64:
                try:
                    openai_url = "https://api.openai.com/v1/chat/completions"
                    payload = {
                        "model": "gpt-4o",
                        "messages": [
                            {"role": "system", "content": "Você é o Blind AI, especialista de audiodescrição acessível W3C WAI. Nunca use asteriscos nem formatação markdown decorativa."},
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{raw_b64}"}}
                                ]
                            }
                        ],
                        "temperature": 0.2
                    }
                    async with httpx.AsyncClient(timeout=45.0) as client:
                        resp = await client.post(openai_url, json=payload, headers={"Authorization": f"Bearer {key}"})
                        if resp.status_code == 200:
                            data = resp.json()
                            description = data["choices"][0]["message"]["content"]
                except Exception as e:
                    logger.debug(f"Falha OpenAI Vision: {e}")

        _filtrar()

        # Tier 5: Oráculo Nativo de Tela via Windows UI Automation. SO para captura da tela atual: para uma foto qualquer
        # descreveria a tela errada e enganaria a pessoa.
        if not description and captura_de_tela:
            try:
                description = self.describe_screen_via_uia()
            except Exception as e:
                logger.debug(f"Falha UIA Screen Desc: {e}")

        _filtrar()
        if recusas and not description:
            # Todos os modelos de visao se recusaram (comum quando ha pessoas): nao inventar nada, dizer a verdade.
            return ("Os modelos de visão se recusaram a descrever esta imagem, o que costuma acontecer quando há pessoas. "
                    "Não consegui uma descrição. Posso tentar com outro modelo ou outra pessoa de confiança pode descrever.")

        # Tier 6: Analisador Estrutural Pillow (so tamanho e cores: nunca fingir que e uma descricao)
        if not description and img_bytes:
            description = ("Não consegui usar um modelo de visão. Só sei dizer, de forma bem limitada: "
                           + self.describe_image_via_pillow(img_bytes))

        if not description:
            return ("Não consegui descrever esta imagem: nenhum modelo de visão respondeu. "
                "(Para o assistente: use a ferramenta ver_imagem com este arquivo; ela entrega a imagem ao modelo da conversa.)")

        return sanitize_screen_reader_text(description)


# Instância singleton global do roteador de visão
smart_vision_router = SmartVisionRouter()
