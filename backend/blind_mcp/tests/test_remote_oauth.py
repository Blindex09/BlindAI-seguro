"""O login do gateway remoto: so a conta do dono entra, o /mcp sem token da 401, e o fluxo do Claude fecha de ponta a ponta."""

import urllib.parse

import pytest
from starlette.testclient import TestClient

from blind_mcp import remote_gateway
from blind_mcp.remote_oauth import OAuthConfig, redirect_ok, s256

BASE = "https://blind.exemplo.net"
CLAUDE = "https://claude.ai/api/mcp/auth_callback"
VERIFIER = "v" * 64
H = {"content-type": "application/json", "accept": "application/json, text/event-stream"}


def make(tmp_path, login="Blindex09"):
    cfg = OAuthConfig(BASE, "cid", "csecret", "Blindex09", tmp_path / "oauth.json")

    async def idp(code, redirect_uri):  # o GitHub de mentira: o code "ok" e o dono, "outro" e uma conta qualquer
        return {"ok": login, "outro": "intruso"}.get(code)

    app = remote_gateway.build_app(oauth_config=cfg, idp=idp, specs=[])
    return app, TestClient(app, base_url=BASE, follow_redirects=False)


def sign_in(c, code="ok", state="estado-do-claude"):
    reg = c.post("/oauth/register", json={"redirect_uris": [CLAUDE]})
    assert reg.status_code == 201
    cid = reg.json()["client_id"]
    q = {"response_type": "code", "client_id": cid, "redirect_uri": CLAUDE, "code_challenge": s256(VERIFIER), "code_challenge_method": "S256", "state": state}
    auth = c.get("/oauth/authorize?" + urllib.parse.urlencode(q))
    assert auth.status_code == 302 and auth.headers["location"].startswith("https://github.com/login/oauth/authorize?")
    key = urllib.parse.parse_qs(urllib.parse.urlparse(auth.headers["location"]).query)["state"][0]
    cb = c.get(f"/oauth/github/callback?code={code}&state={key}")
    return cid, cb


def token(c, cid, code, verifier=VERIFIER):
    return c.post("/oauth/token", content=urllib.parse.urlencode({"grant_type": "authorization_code", "code": code, "redirect_uri": CLAUDE, "client_id": cid, "code_verifier": verifier}),
                  headers={"content-type": "application/x-www-form-urlencoded"})


def test_mcp_without_a_token_is_401_and_says_where_to_sign_in(tmp_path):
    app, c = make(tmp_path)
    with c:
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=H)
        assert r.status_code == 401
        assert 'resource_metadata="https://blind.exemplo.net/.well-known/oauth-protected-resource"' in r.headers["www-authenticate"]
        assert c.post("/mcp", json={}, headers={**H, "authorization": "Bearer inventado"}).status_code == 401
        # o antigo caminho com segredo nao existe mais
        assert c.post("/qualquer-segredo/mcp", json={}, headers=H).status_code == 404


def test_discovery_documents(tmp_path):
    app, c = make(tmp_path)
    with c:
        pr = c.get("/.well-known/oauth-protected-resource").json()
        assert pr["resource"] == f"{BASE}/mcp" and pr["authorization_servers"] == [BASE]
        md = c.get("/.well-known/oauth-authorization-server").json()
        assert md["code_challenge_methods_supported"] == ["S256"] and md["token_endpoint"] == f"{BASE}/oauth/token"


def test_registration_accepts_only_the_claude_callback_or_a_local_one(tmp_path):
    app, c = make(tmp_path)
    with c:
        assert c.post("/oauth/register", json={"redirect_uris": ["https://evil.example/cb"]}).status_code == 400
        assert c.post("/oauth/register", json={"redirect_uris": [CLAUDE, "https://evil.example/cb"]}).status_code == 400
        assert c.post("/oauth/register", json={"redirect_uris": ["http://localhost:33418/callback"]}).status_code == 201
        assert c.post("/oauth/register", json={}).status_code == 400
    assert redirect_ok(CLAUDE) and not redirect_ok("http://evil.example/cb") and not redirect_ok("javascript:alert(1)")


def test_the_whole_sign_in_then_the_tools_answer(tmp_path):
    app, c = make(tmp_path)
    with c:
        cid, cb = sign_in(c)
        assert cb.status_code == 302 and cb.headers["location"].startswith(CLAUDE + "?")
        q = urllib.parse.parse_qs(urllib.parse.urlparse(cb.headers["location"]).query)
        assert q["state"] == ["estado-do-claude"]
        tk = token(c, cid, q["code"][0])
        assert tk.status_code == 200 and tk.json()["token_type"] == "Bearer"
        auth = {**H, "authorization": f"Bearer {tk.json()['access_token']}"}
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=auth)
        assert r.status_code == 200
        assert "comecar" in [t["name"] for t in r.json()["result"]["tools"]]


def test_another_github_account_is_refused(tmp_path):
    app, c = make(tmp_path, login="Blindex09")
    with c:
        cid, cb = sign_in(c, code="outro")
        assert cb.status_code == 403 and "location" not in cb.headers
        cid, cb = sign_in(c, code="invalido")
        assert cb.status_code == 403


def test_a_code_works_once_and_needs_the_right_pkce_verifier(tmp_path):
    app, c = make(tmp_path)
    with c:
        cid, cb = sign_in(c)
        code = urllib.parse.parse_qs(urllib.parse.urlparse(cb.headers["location"]).query)["code"][0]
        assert token(c, cid, code, verifier="errado" * 12).status_code == 400
        assert token(c, cid, code).status_code == 400  # o codigo foi gasto na tentativa errada
        cid, cb = sign_in(c)
        code = urllib.parse.parse_qs(urllib.parse.urlparse(cb.headers["location"]).query)["code"][0]
        assert token(c, cid, code).status_code == 200
        assert token(c, cid, code).status_code == 400  # segunda vez


def test_refresh_rotates_and_an_expired_token_stops_working(tmp_path):
    app, c = make(tmp_path)
    with c:
        cid, cb = sign_in(c)
        code = urllib.parse.parse_qs(urllib.parse.urlparse(cb.headers["location"]).query)["code"][0]
        tk = token(c, cid, code).json()
        refresh = lambda r: c.post("/oauth/token", content=urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": r, "client_id": cid}), headers={"content-type": "application/x-www-form-urlencoded"})
        new = refresh(tk["refresh_token"])
        assert new.status_code == 200 and new.json()["refresh_token"] != tk["refresh_token"]
        assert refresh(tk["refresh_token"]).status_code == 400  # o antigo foi trocado
        # o relogio anda 2 horas: o token de acesso vence
        real = app.oauth.now
        app.oauth.now = lambda: real() + 7200
        assert c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers={**H, "authorization": f"Bearer {tk['access_token']}"}).status_code == 401


def test_a_wrong_host_is_refused_even_with_a_good_token(tmp_path):
    app, c = make(tmp_path)
    with c:
        cid, cb = sign_in(c)
        code = urllib.parse.parse_qs(urllib.parse.urlparse(cb.headers["location"]).query)["code"][0]
        tk = token(c, cid, code).json()
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers={**H, "authorization": f"Bearer {tk['access_token']}", "host": "evil.example.com"})
        assert r.status_code == 421


def test_the_gateway_does_not_start_without_the_login_settings(monkeypatch, tmp_path):
    for k in ("BLIND_REMOTE_PUBLIC_URL", "BLIND_REMOTE_GITHUB_CLIENT_ID", "BLIND_REMOTE_GITHUB_CLIENT_SECRET", "BLIND_REMOTE_GITHUB_USER"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError, match="Faltam variaveis"):
        OAuthConfig.from_env(tmp_path)
    monkeypatch.setenv("BLIND_REMOTE_PUBLIC_URL", "http://exemplo.net")
    monkeypatch.setenv("BLIND_REMOTE_GITHUB_CLIENT_ID", "a")
    monkeypatch.setenv("BLIND_REMOTE_GITHUB_CLIENT_SECRET", "b")
    monkeypatch.setenv("BLIND_REMOTE_GITHUB_USER", "c")
    with pytest.raises(RuntimeError, match="https"):
        OAuthConfig.from_env(tmp_path)


def test_tokens_are_stored_only_as_hashes(tmp_path):
    app, c = make(tmp_path)
    with c:
        cid, cb = sign_in(c)
        code = urllib.parse.parse_qs(urllib.parse.urlparse(cb.headers["location"]).query)["code"][0]
        tk = token(c, cid, code).json()
    disco = (tmp_path / "oauth.json").read_text(encoding="utf-8")
    assert tk["refresh_token"] not in disco and tk["access_token"] not in disco


def test_login_state_can_live_outside_the_blind_data_folder(monkeypatch, tmp_path):
    for k, v in (("BLIND_REMOTE_PUBLIC_URL", "https://blind.exemplo.net"), ("BLIND_REMOTE_GITHUB_CLIENT_ID", "a"),
                 ("BLIND_REMOTE_GITHUB_CLIENT_SECRET", "b"), ("BLIND_REMOTE_GITHUB_USER", "c")):
        monkeypatch.setenv(k, v)
    dados, estado = tmp_path / "dados", tmp_path / "estado"
    monkeypatch.delenv("BLIND_REMOTE_STATE_DIR", raising=False)
    assert OAuthConfig.from_env(dados).state_path == dados / "remote_oauth.json"
    monkeypatch.setenv("BLIND_REMOTE_STATE_DIR", str(estado))
    assert OAuthConfig.from_env(dados).state_path == estado / "remote_oauth.json"


def test_a_registered_client_that_never_got_a_token_expires_but_one_with_a_token_stays(tmp_path):
    from blind_mcp.remote_oauth import UNUSED_CLIENT_TTL

    app, c = make(tmp_path)
    oauth = app.oauth
    with c:
        sem_token = c.post("/oauth/register", json={"redirect_uris": [CLAUDE]}).json()["client_id"]
        cid, cb = sign_in(c)
        code = urllib.parse.parse_qs(urllib.parse.urlparse(cb.headers["location"]).query)["code"][0]
        assert token(c, cid, code).status_code == 200  # este cliente recebeu token
        passou = oauth.now() + UNUSED_CLIENT_TTL + 5
        oauth.now = lambda: passou
        q = {"response_type": "code", "client_id": sem_token, "redirect_uri": CLAUDE, "code_challenge": s256(VERIFIER), "code_challenge_method": "S256"}
        assert c.get("/oauth/authorize?" + urllib.parse.urlencode(q)).status_code == 400  # sumiu: sem token e velho
        assert sem_token not in oauth.clients and cid in oauth.clients


def test_expired_unused_clients_free_room_and_are_dropped_from_the_saved_state(tmp_path):
    from blind_mcp.remote_oauth import MAX_CLIENTS, UNUSED_CLIENT_TTL, OAuthServer

    app, c = make(tmp_path)
    oauth = app.oauth
    with c:
        for _ in range(MAX_CLIENTS):
            assert c.post("/oauth/register", json={"redirect_uris": [CLAUDE]}).status_code == 201
        assert c.post("/oauth/register", json={"redirect_uris": [CLAUDE]}).status_code == 400  # cheio
        passou = oauth.now() + UNUSED_CLIENT_TTL + 5
        oauth.now = lambda: passou
        assert c.post("/oauth/register", json={"redirect_uris": [CLAUDE]}).status_code == 201  # os velhos sem token sairam
        assert len(oauth.clients) == 1
    recarregado = OAuthServer(oauth.cfg, now=lambda: passou)
    assert len(recarregado.clients) == 1  # o disco tambem perdeu os velhos
