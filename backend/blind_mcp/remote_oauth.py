"""Login do gateway remoto do Blind AI: OAuth 2.1 com o GitHub, so para UMA conta.

O Claude (celular, web) faz o login uma vez e depois manda um token em cada chamada. Quem nao tem token recebe 401.
O caminho com segredo na URL deixou de existir.

Fluxo (o formato que o conector personalizado do Claude espera):
  GET  /.well-known/oauth-protected-resource    RFC 9728: quem e o servidor de autorizacao
  GET  /.well-known/oauth-authorization-server  RFC 8414: os enderecos abaixo
  POST /oauth/register                          RFC 7591: o Claude se cadastra (so retorno do Claude ou loopback)
  GET  /oauth/authorize                         PKCE S256, depois manda a pessoa entrar no GitHub
  GET  /oauth/github/callback                   so a conta de BLIND_REMOTE_GITHUB_USER passa; as outras veem 403
  POST /oauth/token                             o codigo (uma vez) ou um refresh vira um token de acesso

Variaveis (nada disso vai para o repositorio):
  BLIND_REMOTE_PUBLIC_URL        o endereco publico do tunel, ex. https://blind.exemplo.net (sem barra no fim)
  BLIND_REMOTE_GITHUB_CLIENT_ID  e _SECRET   o OAuth App do GitHub (callback: <PUBLIC_URL>/oauth/github/callback)
  BLIND_REMOTE_GITHUB_USER       o login do GitHub que pode entrar, ex. Blindex09

Os tokens ficam em disco so como hash (sha256). Um codigo de autorizacao vale uma vez e 5 minutos.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response

ACCESS_TTL = 3600
REFRESH_TTL = 30 * 24 * 3600
CODE_TTL = 300
STATE_TTL = 600
MAX_CLIENTS = 50
CLAUDE_CALLBACKS = ("https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback")

# (code do GitHub, redirect_uri) -> login do GitHub, ou None. Trocavel nos testes.
IdP = Callable[[str, str], Awaitable[Optional[str]]]


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


@dataclass
class OAuthConfig:
    base_url: str
    github_client_id: str
    github_client_secret: str
    github_user: str
    state_path: Path

    @property
    def host(self) -> str:
        return urllib.parse.urlparse(self.base_url).netloc

    @classmethod
    def from_env(cls, data_dir: Path) -> "OAuthConfig":
        env = os.environ
        faltam = [k for k in ("BLIND_REMOTE_PUBLIC_URL", "BLIND_REMOTE_GITHUB_CLIENT_ID", "BLIND_REMOTE_GITHUB_CLIENT_SECRET", "BLIND_REMOTE_GITHUB_USER") if not env.get(k, "").strip()]
        if faltam:
            raise RuntimeError("Faltam variaveis do login do gateway remoto: " + ", ".join(faltam) + ". Veja REMOTO.md.")
        base = env["BLIND_REMOTE_PUBLIC_URL"].strip().rstrip("/")
        if not base.startswith("https://") and not base.startswith("http://127.0.0.1") and not base.startswith("http://localhost"):
            raise RuntimeError("BLIND_REMOTE_PUBLIC_URL precisa ser https:// (o endereco do tunel).")
        return cls(base, env["BLIND_REMOTE_GITHUB_CLIENT_ID"].strip(), env["BLIND_REMOTE_GITHUB_CLIENT_SECRET"].strip(),
                   env["BLIND_REMOTE_GITHUB_USER"].strip(), data_dir / "remote_oauth.json")


def redirect_ok(uri: str) -> bool:
    """Retorno aceito no cadastro: os do Claude na web ou um endereco local (Claude Code)."""
    if uri in CLAUDE_CALLBACKS:
        return True
    p = urllib.parse.urlparse(uri)
    return p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1") and not p.fragment


async def github_login(cfg: OAuthConfig, code: str, redirect_uri: str, client: Optional[httpx.AsyncClient] = None) -> Optional[str]:
    """Troca o code do GitHub pelo login da conta. None se algo falhar."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=15.0)
    try:
        tok = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={"client_id": cfg.github_client_id, "client_secret": cfg.github_client_secret, "code": code, "redirect_uri": redirect_uri},
        )
        access = (tok.json() or {}).get("access_token") if tok.status_code == 200 else None
        if not access:
            return None
        me = await client.get("https://api.github.com/user", headers={"Authorization": f"Bearer {access}", "Accept": "application/vnd.github+json"})
        return (me.json() or {}).get("login") if me.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None
    finally:
        if own:
            await client.aclose()


class OAuthServer:
    def __init__(self, cfg: OAuthConfig, idp: Optional[IdP] = None, now: Callable[[], float] = time.time) -> None:
        self.cfg = cfg
        self.now = now
        self.idp: IdP = idp or (lambda code, ru: github_login(cfg, code, ru))
        self.clients: Dict[str, Dict[str, Any]] = {}
        self.refresh: Dict[str, Dict[str, Any]] = {}  # sha(refresh) -> {client_id, exp}
        self.access: Dict[str, float] = {}  # sha(access) -> exp
        self.states: Dict[str, Dict[str, Any]] = {}
        self.codes: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ------------------------------------------------------------------ disco (so clientes e refresh, como hash)
    def _load(self) -> None:
        try:
            raw = json.loads(self.cfg.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.clients = dict(raw.get("clients") or {})
        self.refresh = {k: v for k, v in (raw.get("refresh") or {}).items() if v.get("exp", 0) > self.now()}

    def _save(self) -> None:
        try:
            self.cfg.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.cfg.state_path.write_text(json.dumps({"clients": self.clients, "refresh": self.refresh}), encoding="utf-8")
        except OSError:
            pass

    def _sweep(self) -> None:
        t = self.now()
        for table in (self.states, self.codes):
            for k in [k for k, v in table.items() if v["exp"] <= t]:
                del table[k]
        for k in [k for k, exp in self.access.items() if exp <= t]:
            del self.access[k]

    # ------------------------------------------------------------------ para o gateway
    def www_authenticate(self, error: str = "") -> str:
        extra = f', error="{error}"' if error else ""
        return f'Bearer resource_metadata="{self.cfg.base_url}/.well-known/oauth-protected-resource"{extra}'

    def valid_bearer(self, header: str) -> bool:
        if not header.lower().startswith("bearer "):
            return False
        self._sweep()
        exp = self.access.get(sha(header[7:].strip()))
        return bool(exp and exp > self.now())

    # ------------------------------------------------------------------ enderecos
    async def protected_resource(self, request: Request) -> Response:
        return JSONResponse({"resource": f"{self.cfg.base_url}/mcp", "authorization_servers": [self.cfg.base_url], "bearer_methods_supported": ["header"]})

    async def metadata(self, request: Request) -> Response:
        b = self.cfg.base_url
        return JSONResponse({
            "issuer": b, "authorization_endpoint": f"{b}/oauth/authorize", "token_endpoint": f"{b}/oauth/token",
            "registration_endpoint": f"{b}/oauth/register", "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"], "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
        })

    async def register(self, request: Request) -> Response:
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_client_metadata"}, status_code=400)
        uris = [str(u) for u in (body.get("redirect_uris") or [])] if isinstance(body, dict) else []
        if not uris or not all(redirect_ok(u) for u in uris):
            return JSONResponse({"error": "invalid_redirect_uri", "error_description": "so o retorno do Claude ou um endereco local"}, status_code=400)
        if len(self.clients) >= MAX_CLIENTS:
            return JSONResponse({"error": "invalid_client_metadata", "error_description": "clientes demais"}, status_code=400)
        cid = secrets.token_urlsafe(16)
        self.clients[cid] = {"redirect_uris": uris, "created": int(self.now())}
        self._save()
        return JSONResponse({"client_id": cid, "redirect_uris": uris, "grant_types": ["authorization_code", "refresh_token"],
                             "response_types": ["code"], "token_endpoint_auth_method": "none"}, status_code=201)

    async def authorize(self, request: Request) -> Response:
        q = request.query_params
        client = self.clients.get(q.get("client_id", ""))
        redirect = q.get("redirect_uri", "")
        if not client or redirect not in client["redirect_uris"]:
            return PlainTextResponse("cliente ou retorno nao cadastrado", status_code=400)
        if q.get("response_type") != "code" or q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
            return PlainTextResponse("PKCE S256 e obrigatorio", status_code=400)
        self._sweep()
        key = secrets.token_urlsafe(24)
        self.states[key] = {"client_id": q["client_id"], "redirect_uri": redirect, "challenge": q["code_challenge"], "state": q.get("state"), "exp": self.now() + STATE_TTL}
        gh = urllib.parse.urlencode({"client_id": self.cfg.github_client_id, "redirect_uri": f"{self.cfg.base_url}/oauth/github/callback", "state": key, "allow_signup": "false"})
        return RedirectResponse(f"https://github.com/login/oauth/authorize?{gh}", status_code=302)

    async def github_callback(self, request: Request) -> Response:
        q = request.query_params
        st = self.states.pop(q.get("state", ""), None)
        if not st or st["exp"] <= self.now():
            return PlainTextResponse("entrada expirada, tente de novo", status_code=400)
        login = await self.idp(q.get("code", ""), f"{self.cfg.base_url}/oauth/github/callback") if q.get("code") else None
        if not login or not hmac.compare_digest(login.lower(), self.cfg.github_user.lower()):
            return PlainTextResponse("Esta conta nao tem acesso ao Blind.", status_code=403)
        code = secrets.token_urlsafe(32)
        self.codes[sha(code)] = {**st, "exp": self.now() + CODE_TTL}
        out = {"code": code, **({"state": st["state"]} if st.get("state") is not None else {})}
        return RedirectResponse(f"{st['redirect_uri']}{'&' if '?' in st['redirect_uri'] else '?'}{urllib.parse.urlencode(out)}", status_code=302)

    def _issue(self, client_id: str) -> Dict[str, Any]:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.access[sha(access)] = self.now() + ACCESS_TTL
        self.refresh[sha(refresh)] = {"client_id": client_id, "exp": self.now() + REFRESH_TTL}
        self._save()
        return {"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_TTL, "refresh_token": refresh}

    async def token(self, request: Request) -> Response:
        raw = (await request.body())[:8192].decode("utf-8", "replace")
        form = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
        self._sweep()
        grant = form.get("grant_type")
        if grant == "authorization_code":
            row = self.codes.pop(sha(form.get("code", "")), None)  # uma vez so
            if not row or row["exp"] <= self.now() or row["client_id"] != form.get("client_id") or row["redirect_uri"] != form.get("redirect_uri"):
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            if not form.get("code_verifier") or not hmac.compare_digest(s256(form["code_verifier"]), row["challenge"]):
                return JSONResponse({"error": "invalid_grant", "error_description": "PKCE nao confere"}, status_code=400)
            return JSONResponse(self._issue(row["client_id"]), headers={"Cache-Control": "no-store"})
        if grant == "refresh_token":
            row = self.refresh.pop(sha(form.get("refresh_token", "")), None)  # troca a cada uso
            if not row or row["exp"] <= self.now() or row["client_id"] != form.get("client_id"):
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            return JSONResponse(self._issue(row["client_id"]), headers={"Cache-Control": "no-store"})
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
