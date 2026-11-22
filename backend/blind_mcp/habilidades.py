"""Habilidades do Blind: regras de comportamento para uma pessoa cega, em arquivos de texto (pasta `habilidades/`).

Cada arquivo tem um cabecalho (nome, quando, palavras) e o texto. Ficam no projeto, e nao so no Claude, para valerem
tambem no app Electron. O `comecar` entrega o jeito de falar sempre e as habilidades que combinam com o pedido.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List

PASTA = Path(__file__).with_name("habilidades")
SEMPRE = "jeito-de-falar"
MAX_POR_PEDIDO = 3


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def carregar() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for arq in sorted(PASTA.glob("*.md")):
        bruto = arq.read_text(encoding="utf-8")
        m = re.match(r"---\n(.*?)\n---\n(.*)", bruto, re.S)
        if not m:
            continue
        meta = {}
        for linha in m.group(1).splitlines():
            if ":" in linha:
                k, v = linha.split(":", 1)
                meta[k.strip()] = v.strip()
        nome = meta.get("nome") or arq.stem
        out[nome] = {
            "nome": nome,
            "quando": meta.get("quando", ""),
            "palavras": [_sem_acento(p.strip()) for p in meta.get("palavras", "").split(",") if p.strip()],
            "texto": m.group(2).strip(),
        }
    return out


def indice() -> List[Dict[str, str]]:
    return [{"nome": h["nome"], "quando": h["quando"]} for h in carregar().values()]


def texto(nome: str) -> str:
    h = carregar().get((nome or "").strip().lower())
    return h["texto"] if h else ""


def para_pedido(pedido: str) -> List[Dict[str, str]]:
    """Habilidades (menos o jeito de falar, que vai sempre) cujas palavras aparecem no pedido, as mais citadas primeiro."""
    alvo = set(re.findall(r"\w+", _sem_acento(pedido or "")))
    pontos = []
    for h in carregar().values():
        if h["nome"] == SEMPRE:
            continue
        n = sum(1 for p in h["palavras"] if p in alvo)
        if n:
            pontos.append((n, h))
    pontos.sort(key=lambda x: -x[0])
    return [{"nome": h["nome"], "texto": h["texto"]} for _, h in pontos[:MAX_POR_PEDIDO]]


def _sem_marcacao(txt: str) -> str:
    """Tira asteriscos, cerquilhas e crases: leitores de tela soletram esses simbolos."""
    txt = re.sub(r"[*`]", "", txt)
    txt = re.sub(r"^#+\s*", "", txt, flags=re.M)
    return txt.strip()


def bloco_para(pedido: str, max_chars: int = 7500) -> str:
    """Texto para o prompt dos modelos do app (Ollama etc.): jeito de falar sempre, mais as habilidades do pedido, ate o limite
    (modelos menores se perdem com prompt grande). Sem marcacao de markdown."""
    partes = [("jeito de falar", texto(SEMPRE))]
    partes += [(h["nome"].replace("-", " "), h["texto"]) for h in para_pedido(pedido)]
    saida = "\n\nREGRAS PARA FALAR E AGIR COM UMA PESSOA CEGA (siga sempre):"
    for nome, corpo in partes:
        if not corpo:
            continue
        trecho = f"\n\n[{nome}]\n{_sem_marcacao(corpo)}"
        if len(saida) + len(trecho) > max_chars:
            continue  # esta nao cabe; tenta a proxima, menor
        saida += trecho
    return saida if len(saida) > 80 else ""
