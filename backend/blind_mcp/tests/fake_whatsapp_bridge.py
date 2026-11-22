"""Conector WhatsApp FALSO para testes: mesmo protocolo HTTP do bridge.js, sem rede e sem WhatsApp."""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.environ.get("BLIND_WA_TOKEN", "")
STATE = {"status": "idle", "phone": "", "code": "", "inbox": []}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silencioso
        pass

    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _auth(self):
        if TOKEN and self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self._send(401, {"ok": False, "error": "nao autorizado"})
            return False
        return True

    def do_GET(self):
        if not self._auth():
            return
        if self.path == "/health":
            return self._send(200, {"ok": True, "pid": os.getpid()})
        if self.path == "/status":
            return self._send(200, {"ok": True, "status": STATE["status"], "phone": STATE["phone"], "registered": STATE["status"] == "connected",
                                    "error": "", "pairing_code": STATE["code"] if STATE["status"] == "waiting_link" else ""})
        if self.path.startswith("/messages"):
            return self._send(200, {"ok": True, "total": 1, "mensagens": [{"de": "5511999990000", "texto": "oi", "tipo": "texto"}]})
        self._send(404, {"ok": False, "error": "rota desconhecida"})

    def do_POST(self):
        if not self._auth():
            return
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/pair":
            phone = "".join(c for c in str(body.get("phone", "")) if c.isdigit())
            if len(phone) < 10:
                return self._send(400, {"ok": False, "error": "Numero invalido: informe DDI, DDD e numero."})
            STATE.update(status="waiting_link", phone=phone, code="ABCD1234")
            return self._send(200, {"ok": True, "status": "waiting_link", "phone": phone, "code": "ABCD1234"})
        if self.path == "/connect-now":  # so no teste: simula o usuario digitando o codigo no celular
            STATE.update(status="connected")
            return self._send(200, {"ok": True})
        if self.path == "/logout":
            STATE.update(status="logged_out", code="")
            return self._send(200, {"ok": True})
        self._send(404, {"ok": False, "error": "rota desconhecida"})


if __name__ == "__main__":
    srv = HTTPServer(("127.0.0.1", 0), H)
    print(json.dumps({"event": "listening", "port": srv.server_address[1]}), flush=True)
    srv.serve_forever()
