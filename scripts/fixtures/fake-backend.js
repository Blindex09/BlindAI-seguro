'use strict';

// Backend falso para testes do supervisor e do Electron (scripts/smoke.js).
// Rotas de mentira: /api/status, /api/echo, /api/text, /api/slow e /api/mcp/*. Nao serve a UI ("/" = 404).
//
// Variaveis:
//   BLIND_PORT         porta (obrigatoria, exportada pelo supervisor)
//   FAKE_MODE          ok (padrao) | exit-immediately | never-listen | die-after
//   FAKE_DIE_MS        com die-after: encerra o processo N ms depois de ouvir (padrao 300)
//   FAKE_DIE_ONCE_FILE com die-after: so morre na primeira vez (cria este arquivo marcador)
//   FAKE_MCP           1 (padrao) responde /api/mcp/*; 0 devolve 404 (backend sem MCP)
//   FAKE_MCP_ERRORS    1: reiniciar servidor devolve {ok:false}
//   FAKE_MCP_STARTING_MS  servidor "windows-desktop" fica "starting" por N ms depois de subir

const fs = require('fs');
const http = require('http');

const mode = process.env.FAKE_MODE || 'ok';
const port = Number(process.env.BLIND_PORT);
const mcpEnabled = process.env.FAKE_MCP !== '0';

if (mode === 'exit-immediately') {
  console.error('fake-backend: ModuleNotFoundError: No module named "aiohttp"');
  process.exit(3);
}

if (mode === 'never-listen') {
  console.log('fake-backend: nunca vai ouvir');
  setInterval(() => {}, 1000);
} else {
  // FAKE_MCP_STARTING_MS: servidores aparecem como "starting" nos primeiros N ms (testa o polling do painel)
  const startedAt = Date.now();
  const startingMs = Number(process.env.FAKE_MCP_STARTING_MS) || 0;
  const starting = () => Date.now() - startedAt < startingMs;
  const getServers = () => [
    { name: 'windows-desktop', status: starting() ? 'starting' : 'connected', tool_count: starting() ? 0 : 2, error: null },
    { name: 'whatsapp', status: 'error', tool_count: 0, error: 'processo encerrou com codigo 1' },
  ];
  const tools = [
    { server: 'windows-desktop', name: 'Click', description: 'Clica em coordenadas' },
    { server: 'windows-desktop', name: 'Type', description: 'Digita texto' },
  ];

  const send = (res, status, body, type = 'application/json') => {
    res.writeHead(status, { 'Content-Type': `${type}; charset=utf-8` });
    res.end(typeof body === 'string' ? body : JSON.stringify(body));
  };

  const readBody = (req) =>
    new Promise((resolve) => {
      let raw = '';
      req.on('data', (c) => {
        raw += c;
      });
      req.on('end', () => {
        try {
          resolve(raw ? JSON.parse(raw) : {});
        } catch (_) {
          resolve({});
        }
      });
    });

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://x');
    const p = url.pathname;

    // O backend real nao serve mais a UI: "/" devolve 404 (cai no 404 final).
    if (p === '/api/status') return send(res, 200, { status: 'ok', pid: process.pid, port });
    if (p === '/api/echo') return send(res, 200, { method: req.method, echo: await readBody(req) });
    if (p === '/api/text') return send(res, 200, 'texto simples, nao JSON', 'text/plain');
    if (p === '/api/slow') return setTimeout(() => send(res, 200, { slow: true }), 5000);

    if (p.startsWith('/api/mcp/')) {
      if (!mcpEnabled) return send(res, 404, { detail: 'Not Found' });
      if (req.method === 'GET' && p === '/api/mcp/servers') return send(res, 200, getServers());
      if (req.method === 'GET' && p === '/api/mcp/tools') return send(res, 200, tools);
      const restart = p.match(/^\/api\/mcp\/servers\/([^/]+)\/restart$/);
      if (req.method === 'POST' && restart) {
        await readBody(req);
        if (process.env.FAKE_MCP_ERRORS === '1') return send(res, 200, { ok: false, error: 'nao foi possivel reiniciar' });
        return send(res, 200, { ok: true });
      }
      if (req.method === 'POST' && p === '/api/mcp/call') {
        const body = await readBody(req);
        return send(res, 200, { ok: true, content: [{ type: 'text', text: `echo ${JSON.stringify(body.arguments)}` }], is_error: false });
      }
    }
    return send(res, 404, { detail: 'Not Found' });
  });

  server.listen(port, '127.0.0.1', () => {
    console.log(`fake-backend: ouvindo em ${port} (pid ${process.pid}, modo ${mode})`);
    if (mode === 'die-after') {
      const marker = process.env.FAKE_DIE_ONCE_FILE;
      if (marker && fs.existsSync(marker)) return; // ja morreu uma vez: fica de pe
      if (marker) fs.writeFileSync(marker, 'died');
      setTimeout(() => process.exit(1), Number(process.env.FAKE_DIE_MS) || 300);
    }
  });
}
