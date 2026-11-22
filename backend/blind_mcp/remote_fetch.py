"""Baixa um arquivo publico da web para o gateway remoto (PDF ou imagem), sem tocar em rede interna.

O gateway nunca abre um caminho do computador. Para ler algo da web, ele mesmo baixa o link e passa os bytes adiante.
Regras: so http/https, sem usuario e senha no link, sem localhost, sem endereco privado (nem depois de redirecionar),
sem DNS que nao resolve, ate 5 redirecionamentos e ate `max_bytes`.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

MAX_URL_CHARS = 2048
MAX_REDIRECTS = 5


def validar(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("Link vazio.")
    if len(raw) > MAX_URL_CHARS:
        raise ValueError("Link longo demais.")
    p = urlparse(raw)
    if p.scheme not in ("http", "https"):
        raise ValueError("Apenas links http:// ou https:// sao aceitos.")
    if p.username or p.password:
        raise ValueError("Links com usuario e senha nao sao aceitos.")
    host = (p.hostname or "").strip().lower()
    if not host or host in ("localhost", "0.0.0.0") or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("Acesso a enderecos locais ou internos nao e permitido.")
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ValueError("Nao consegui resolver o endereco do link.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError("Endereco privado ou interno bloqueado por seguranca.")
    return raw


async def baixar(url: str, max_bytes: int, client: Optional[httpx.AsyncClient] = None) -> bytes:
    """Os bytes do arquivo. Cada redirecionamento passa pela mesma validacao do primeiro link."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False, headers={"User-Agent": "Mozilla/5.0 BlindAI"})
    try:
        atual = validar(url)
        for _ in range(MAX_REDIRECTS + 1):
            async with client.stream("GET", atual) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                    atual = validar(urljoin(atual, resp.headers["location"]))
                    continue
                if resp.status_code != 200:
                    raise ValueError(f"O link respondeu {resp.status_code}.")
                declared = int(resp.headers.get("content-length") or 0)
                if declared > max_bytes:
                    raise ValueError("O arquivo e grande demais.")
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise ValueError("O arquivo e grande demais.")
                return bytes(buf)
        raise ValueError("Redirecionamentos demais.")
    finally:
        if own:
            await client.aclose()
