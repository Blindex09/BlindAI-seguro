"""Baixa um arquivo publico da web para o gateway remoto (PDF ou imagem), sem tocar em rede interna.

O gateway nunca abre um caminho do computador. Para ler algo da web, ele mesmo baixa o link e passa os bytes adiante.
Regras: so http/https, sem usuario e senha no link, sem localhost, sem endereco privado (nem depois de redirecionar),
sem DNS que nao resolve, ate 5 redirecionamentos e ate `max_bytes`.

IP fixo (sem DNS rebinding): o endereco e resolvido e conferido UMA vez, dentro da propria conexao (`_PinnedBackend`),
e o socket abre nesse IP ja conferido. Nao existe um segundo DNS entre a conferencia e a conexao. O TLS continua
usando o nome do site (SNI e certificado). Proxy do ambiente e ignorado, porque o proxy resolveria o nome por conta propria.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any, List, Optional
from urllib.parse import urljoin, urlparse

import anyio
import httpcore
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
    if _literal_ip(host) is not None:
        _checar_ip(host)
    else:
        for ip in _resolver(host, p.port or (443 if p.scheme == "https" else 80)):
            _checar_ip(ip)
    return raw


def _literal_ip(host: str) -> Optional[Any]:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def _checar_ip(texto: str) -> str:
    """Levanta ValueError se o IP for privado, local, reservado ou de nuvem; senao devolve o IP."""
    ip = ipaddress.ip_address(texto.split("%", 1)[0])
    if getattr(ip, "ipv4_mapped", None) is not None:  # ::ffff:127.0.0.1 e o mesmo que 127.0.0.1
        ip = ip.ipv4_mapped
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified or ip.is_global is False:
        raise ValueError("Endereco privado ou interno bloqueado por seguranca.")
    return str(ip)


def _resolver(host: str, port: int) -> List[str]:
    """Os IPs do nome (resolvidos agora). Falha se nao resolve."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Nao consegui resolver o endereco do link.") from exc
    ips = []
    for info in infos:
        if info[4][0] not in ips:
            ips.append(info[4][0])
    if not ips:
        raise ValueError("Nao consegui resolver o endereco do link.")
    return ips


class _PinnedBackend(httpcore.AnyIOBackend):
    """Resolve o nome UMA vez, confere TODOS os IPs e conecta so em IP conferido. Conferir e conectar sao o mesmo passo:
    um DNS que troca de resposta entre dois lookups nao tem como ser aproveitado."""

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):  # type: ignore[override]
        if _literal_ip(host) is not None:
            ips = [_checar_ip(host)]
        else:
            resolvidos = await anyio.to_thread.run_sync(_resolver, host, port)
            ips = [_checar_ip(ip) for ip in resolvidos]  # um IP ruim na lista recusa o link inteiro
        ultimo: Optional[Exception] = None
        for ip in ips:
            try:
                return await super().connect_tcp(ip, port, timeout=timeout, local_address=local_address, socket_options=socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                ultimo = exc
        raise ultimo or httpcore.ConnectError("sem endereco para conectar")


def novo_cliente() -> httpx.AsyncClient:
    """O cliente do gateway: IP fixo, sem redirecionamento automatico, sem proxy do ambiente."""
    transport = httpx.AsyncHTTPTransport()
    transport._pool._network_backend = _PinnedBackend()  # type: ignore[attr-defined]
    return httpx.AsyncClient(
        transport=transport, timeout=30.0, follow_redirects=False, trust_env=False, headers={"User-Agent": "Mozilla/5.0 BlindAI"}
    )


async def baixar(url: str, max_bytes: int, client: Optional[httpx.AsyncClient] = None) -> bytes:
    """Os bytes do arquivo. Cada redirecionamento passa pela mesma validacao do primeiro link."""
    return (await buscar(url, max_bytes, client=client))[0]


async def buscar(url: str, max_bytes: int, client: Optional[httpx.AsyncClient] = None, headers: Optional[dict] = None):
    """(bytes, link final, content-type). Redirecionamento manual: cada salto e conferido ANTES de ser pedido,
    e toda conexao passa pelo IP fixo de `_PinnedBackend`."""
    own = client is None
    client = client or novo_cliente()
    try:
        atual = validar(url)
        for _ in range(MAX_REDIRECTS + 1):
            async with client.stream("GET", atual, headers=headers) as resp:
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
                return bytes(buf), atual, (resp.headers.get("content-type") or "").lower()
        raise ValueError("Redirecionamentos demais.")
    finally:
        if own:
            await client.aclose()
