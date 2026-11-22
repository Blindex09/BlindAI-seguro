'use strict';

// Verificacao do lado Electron.
//   node scripts/smoke.js              sintaxe + supervisor + cliente da API (sem Electron)
//   node scripts/smoke.js --electron   alem disso, sobe o Electron real contra um backend falso
//                                      (3 cenarios) e sonda window.blind / painel MCP / tela de erro
//   node scripts/smoke.js --packaged   igual, mas usando o app empacotado em dist/win-unpacked
//
// Nao usa o backend Python real. Nao mata processos por nome: so os que ele proprio iniciou.

const assert = require('assert');
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const net = require('net');
const os = require('os');
const path = require('path');

const { BackendSupervisor, findFreePort, isPortFree, httpStatus, killProcessTree } = require('../src/supervisor');
const { createApi } = require('../src/api');
const { checkSyntax } = require('./check-syntax');

const ROOT = path.join(__dirname, '..');
const FAKE = path.join(__dirname, 'fixtures', 'fake-backend.js');
const PACKAGED = process.argv.includes('--packaged');
const WITH_ELECTRON = process.argv.includes('--electron') || PACKAGED;

const results = [];
async function test(name, fn) {
  const started = Date.now();
  try {
    await fn();
    results.push({ name, ok: true, ms: Date.now() - started });
    console.log(`  ok    ${name} (${Date.now() - started} ms)`);
  } catch (err) {
    results.push({ name, ok: false, ms: Date.now() - started, error: err });
    console.log(`  FALHA ${name}\n        ${String(err && err.message ? err.message : err).split('\n').join('\n        ')}`);
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function isAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (_) {
    return false;
  }
}

async function waitDead(pid, ms = 4000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (!isAlive(pid)) return true;
    await sleep(100);
  }
  return !isAlive(pid);
}

function listen(port, host) {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once('error', reject);
    srv.listen({ port, host }, () => resolve(srv));
  });
}
const closeServer = (srv) => new Promise((r) => srv.close(() => r()));

async function getJson(port, urlPath) {
  return new Promise((resolve, reject) => {
    http
      .get({ host: '127.0.0.1', port, path: urlPath, agent: false }, (res) => {
        let raw = '';
        res.on('data', (c) => {
          raw += c;
        });
        res.on('end', () => resolve(JSON.parse(raw)));
      })
      .on('error', reject);
  });
}

function makeSupervisor(env = {}, extra = {}) {
  return new BackendSupervisor({
    command: process.execPath,
    args: [FAKE],
    cwd: ROOT,
    env,
    healthTimeoutMs: 8000,
    healthIntervalMs: 100,
    backoffMs: [50, 100],
    maxRestarts: 2,
    stableMs: 60000,
    stopTimeoutMs: 3000,
    ...extra,
  });
}

function recordStates(sup) {
  const states = [];
  sup.on('state', (s) => states.push(s.state));
  return states;
}

async function waitForState(sup, wanted, ms = 10000) {
  if (sup.state === wanted) return;
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      sup.off('state', onState);
      reject(new Error(`estado "${wanted}" nao ocorreu em ${ms} ms (atual: ${sup.state})`));
    }, ms);
    function onState(s) {
      if (s.state === wanted) {
        clearTimeout(timer);
        sup.off('state', onState);
        resolve();
      }
    }
    sup.on('state', onState);
  });
}

// ---------------------------------------------------------------- 1. sintaxe

function checkSyntaxOrThrow() {
  const { count, errors } = checkSyntax();
  assert.strictEqual(errors.length, 0, `erro de sintaxe:\n${errors.join('\n')}`);
  return count;
}

// ---------------------------------------------------------------- 2. supervisor

async function supervisorTests() {
  await test('findFreePort devolve a porta pedida quando ela esta livre', async () => {
    const base = await findFreePort(0);
    assert.strictEqual(await findFreePort(base), base);
  });

  await test('porta ocupada em 0.0.0.0 (como o backend antigo) e detectada', async () => {
    const base = await findFreePort(0);
    const srv = await listen(base, '0.0.0.0');
    try {
      assert.strictEqual(await isPortFree(base), false);
      assert.notStrictEqual(await findFreePort(base), base);
    } finally {
      await closeServer(srv);
    }
  });

  await test('porta ocupada em 127.0.0.1 e detectada', async () => {
    const base = await findFreePort(0);
    const srv = await listen(base, '127.0.0.1');
    try {
      assert.strictEqual(await isPortFree(base), false);
    } finally {
      await closeServer(srv);
    }
  });

  await test('inicia o backend, exporta BLIND_PORT, responde e stop() mata o processo', async () => {
    const sup = makeSupervisor({}, { preferredPort: await findFreePort(0) });
    const { port } = await sup.start();
    const status = await getJson(port, '/api/status');
    assert.strictEqual(status.port, port, 'BLIND_PORT no filho difere da porta do supervisor');
    assert.strictEqual(sup.state, 'ready');
    await sup.stop();
    assert.strictEqual(sup.state, 'stopped');
    assert.strictEqual(await httpStatus(port, '/api/status', 500), null, 'porta ainda responde');
    assert.ok(await waitDead(status.pid), 'processo do backend continua vivo');
  });

  await test('porta preferida ocupada: usa outra porta e a exporta no filho', async () => {
    const base = await findFreePort(0);
    const blocker = await listen(base, '0.0.0.0');
    const sup = makeSupervisor({}, { preferredPort: base });
    try {
      const { port } = await sup.start();
      assert.notStrictEqual(port, base);
      const status = await getJson(port, '/api/status');
      assert.strictEqual(status.port, port);
    } finally {
      await sup.stop();
      await closeServer(blocker);
    }
  });

  await test('backend que sai na hora: falha clara, sem reinicio, saida capturada', async () => {
    const sup = makeSupervisor({ FAKE_MODE: 'exit-immediately' }, { preferredPort: await findFreePort(0) });
    const states = recordStates(sup);
    await assert.rejects(() => sup.start(), /encerrou antes de ficar pronto/);
    assert.strictEqual(sup.state, 'failed');
    assert.strictEqual(states.filter((s) => s === 'starting').length, 1, `estados: ${states.join(',')}`);
    assert.match(sup.recentOutput(), /ModuleNotFoundError/);
  });

  await test('comando inexistente: mensagem orienta a definir BLIND_PYTHON', async () => {
    const sup = makeSupervisor({}, { command: 'comando-que-nao-existe-blind', preferredPort: await findFreePort(0) });
    await assert.rejects(() => sup.start(), /BLIND_PYTHON/);
    assert.strictEqual(sup.state, 'failed');
  });

  await test('backend que nunca ouve: timeout do health check e processo encerrado', async () => {
    const sup = makeSupervisor({ FAKE_MODE: 'never-listen' }, { preferredPort: await findFreePort(0), healthTimeoutMs: 1500 });
    let pid = null;
    sup.on('state', (s) => {
      if (s.state === 'starting') setImmediate(() => (pid = sup.child && sup.child.pid));
    });
    await assert.rejects(() => sup.start(), /nao respondeu/);
    assert.strictEqual(sup.state, 'failed');
    assert.ok(pid, 'nao capturou o pid');
    assert.ok(await waitDead(pid), 'processo do backend sem resposta nao foi encerrado');
  });

  await test('backend cai uma vez depois de pronto: reinicia sozinho e volta a ficar pronto', async () => {
    const marker = path.join(os.tmpdir(), `blind-die-once-${process.pid}-${Date.now()}`);
    const sup = makeSupervisor({ FAKE_MODE: 'die-after', FAKE_DIE_MS: '300', FAKE_DIE_ONCE_FILE: marker }, { preferredPort: await findFreePort(0) });
    const states = recordStates(sup);
    try {
      const first = await sup.start();
      const pid1 = (await getJson(first.port, '/api/status')).pid;
      await waitForState(sup, 'restarting');
      await waitForState(sup, 'ready');
      const pid2 = (await getJson(sup.port, '/api/status')).pid;
      assert.notStrictEqual(pid1, pid2, 'o pid deveria mudar apos o reinicio');
      assert.strictEqual(sup.restarts, 1);
      assert.deepStrictEqual(states.filter((s) => s === 'restarting' || s === 'failed'), ['restarting']);
    } finally {
      await sup.stop();
      fs.rmSync(marker, { force: true });
    }
  });

  await test('backend que cai sempre: reinicios esgotam (maxRestarts=2) e fica em failed', async () => {
    const sup = makeSupervisor({ FAKE_MODE: 'die-after', FAKE_DIE_MS: '150' }, { preferredPort: await findFreePort(0) });
    const states = recordStates(sup);
    try {
      await sup.start();
      await waitForState(sup, 'failed', 15000);
      assert.strictEqual(states.filter((s) => s === 'restarting').length, 2, `estados: ${states.join(',')}`);
      assert.match(sup.error, /esgotados/);
    } finally {
      await sup.stop();
    }
  });

  await test('stop() durante o backoff cancela o reinicio e nao sobe outro processo', async () => {
    const sup = makeSupervisor({ FAKE_MODE: 'die-after', FAKE_DIE_MS: '150' }, { preferredPort: await findFreePort(0), backoffMs: [5000] });
    const states = recordStates(sup);
    await sup.start();
    await waitForState(sup, 'restarting');
    const t0 = Date.now();
    await sup.stop();
    assert.ok(Date.now() - t0 < 2000, 'stop() deveria interromper a espera do backoff');
    assert.strictEqual(sup.state, 'stopped');
    await sleep(300);
    assert.strictEqual(states.filter((s) => s === 'starting').length, 1, `estados: ${states.join(',')}`);
  });

  await test('restart() manual troca o processo', async () => {
    const sup = makeSupervisor({}, { preferredPort: await findFreePort(0) });
    try {
      const a = await sup.start();
      const pid1 = (await getJson(a.port, '/api/status')).pid;
      const b = await sup.restart();
      const pid2 = (await getJson(b.port, '/api/status')).pid;
      assert.notStrictEqual(pid1, pid2);
      assert.ok(await waitDead(pid1), 'processo antigo continua vivo');
    } finally {
      await sup.stop();
    }
  });
}

// ---------------------------------------------------------------- 3. cliente da API

async function apiTests() {
  function fakeServer(handler) {
    return new Promise((resolve) => {
      const srv = http.createServer(handler);
      srv.listen(0, '127.0.0.1', () => resolve({ srv, base: `http://127.0.0.1:${srv.address().port}` }));
    });
  }

  await test('api: rota /api/mcp/* ausente (404) vira available:false com mensagem', async () => {
    const { srv, base } = await fakeServer((req, res) => {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end('{"detail":"Not Found"}');
    });
    try {
      const api = createApi({ getBaseUrl: () => base });
      const servers = await api.mcpServers();
      assert.strictEqual(servers.available, false);
      assert.match(servers.error, /MCP/);
      assert.deepStrictEqual((await api.mcpTools()).tools, []);
      assert.strictEqual((await api.mcpRestart('x')).ok, false);
      assert.strictEqual((await api.mcpCall('a', 'b', {})).is_error, true);
    } finally {
      await closeServer(srv);
    }
  });

  await test('api: normaliza listas, aceita {servers:[...]} e repassa restart/call', async () => {
    const { srv, base } = await fakeServer((req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      if (req.url === '/api/mcp/servers') return res.end(JSON.stringify({ servers: [{ name: 'a', status: 'connected', tool_count: '3' }, { name: 'b' }] }));
      if (req.url === '/api/mcp/tools') return res.end(JSON.stringify([{ server: 'a', name: 't' }]));
      if (req.url === '/api/mcp/servers/a%20b/restart') return res.end('{"ok":false,"error":"boom"}');
      return res.end('{"ok":true,"content":[1],"is_error":false}');
    });
    try {
      const api = createApi({ getBaseUrl: () => base });
      const servers = await api.mcpServers();
      assert.deepStrictEqual(servers.servers[0], { name: 'a', status: 'connected', tool_count: 3, error: null });
      assert.deepStrictEqual(servers.servers[1], { name: 'b', status: 'error', tool_count: 0, error: null });
      assert.deepStrictEqual((await api.mcpTools()).tools, [{ server: 'a', name: 't', description: '' }]);
      assert.deepStrictEqual(await api.mcpRestart('a b'), { ok: false, error: 'boom' });
      assert.deepStrictEqual(await api.mcpCall('a', 't', { x: 1 }), { ok: true, content: [1], is_error: false });
    } finally {
      await closeServer(srv);
    }
  });

  await test('api: backend fora do ar (sem URL ou porta fechada) nao rejeita', async () => {
    const none = createApi({ getBaseUrl: () => '' });
    assert.strictEqual((await none.mcpServers()).available, false);
    const port = await findFreePort(0);
    const closed = createApi({ getBaseUrl: () => `http://127.0.0.1:${port}`, timeoutMs: 1000 });
    assert.strictEqual((await closed.mcpServers()).available, false);
    assert.strictEqual((await closed.mcpCall('a', 'b', {})).ok, false);
  });
}

// ---------------------------------------------------------------- 4. Electron real

function runElectronScenario(label, env, check) {
  return test(`electron real: ${label}`, async () => {
    // --packaged: usa dist/win-unpacked/Blind AI.exe (gerado por "npm run pack") em vez do Electron de desenvolvimento.
    const packagedExe = path.join(ROOT, 'dist', 'win-unpacked', 'Blind AI.exe');
    const electronPath = PACKAGED ? packagedExe : require('electron');
    if (PACKAGED) assert.ok(fs.existsSync(packagedExe), `nao existe ${packagedExe}; rode "npm run pack"`);
    const out = path.join(os.tmpdir(), `blind-smoke-out-${process.pid}-${Date.now()}.json`);
    const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'blind-smoke-ud-'));
    const childEnv = {
      ...process.env,
      BLIND_SMOKE: '1',
      BLIND_SMOKE_USERDATA: userData,
      BLIND_SMOKE_OUT: out,
      BLIND_SMOKE_TIMEOUT_MS: '60000',
      BLIND_PYTHON: process.execPath,
      BLIND_BACKEND_SCRIPT: path.join('scripts', 'fixtures', 'fake-backend.js'),
      BLIND_BACKEND_DIR: ROOT,
      BLIND_PORT: String(await findFreePort(0)),
      ...env,
    };
    delete childEnv.ELECTRON_RUN_AS_NODE;
    try {
      const child = spawn(electronPath, PACKAGED ? [] : ['.'], { cwd: ROOT, env: childEnv, stdio: 'ignore', windowsHide: true });
      const exit = await new Promise((resolve) => {
        const timer = setTimeout(() => resolve('timeout'), 90000);
        child.once('exit', (code) => {
          clearTimeout(timer);
          resolve(code);
        });
      });
      if (exit === 'timeout') await killProcessTree(child);
      assert.notStrictEqual(exit, 'timeout', 'o Electron nao encerrou em 90 s');
      assert.ok(fs.existsSync(out), `o Electron saiu (codigo ${exit}) sem gravar o resultado`);
      const result = JSON.parse(fs.readFileSync(out, 'utf8'));
      assert.ok(!result.timeout, `timeout interno do smoke: ${JSON.stringify(result)}`);
      check(result);
    } finally {
      fs.rmSync(out, { force: true });
      // No Windows os processos do Electron podem segurar arquivos por instantes depois de sair:
      // limpeza do userData temporario e "melhor esforco" e nunca reprova o teste.
      for (let i = 0; i < 10; i += 1) {
        try {
          fs.rmSync(userData, { recursive: true, force: true });
          break;
        } catch (_) {
          await sleep(300);
        }
      }
    }
  });
}

async function electronTests() {
  // Arquivos para o stub de files.pick (BLIND_TEST_PICK_FILE, so no modo smoke).
  const fixtureDir = fs.mkdtempSync(path.join(os.tmpdir(), 'blind-smoke-files-'));
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64');
  const pngFile = path.join(fixtureDir, 'valid.png');
  const txtFile = path.join(fixtureDir, 'note.txt');
  const bigFile = path.join(fixtureDir, 'big.png');
  fs.writeFileSync(pngFile, png);
  fs.writeFileSync(txtFile, 'ola, blind!');
  fs.writeFileSync(bigFile, Buffer.alloc(26 * 1024 * 1024)); // acima do limite de 25 MB
  const picks = [pngFile, txtFile, bigFile, pngFile].join('|');

  try {
    await runElectronScenario('carrega o renderer por file:// e todo o contrato window.blind funciona', { FAKE_MCP: '1', BLIND_TEST_PICK_FILE: picks }, (r) => {
      assert.strictEqual(r.page, 'app', JSON.stringify(r));
      assert.match(r.href, /^file:\/\/\/.*src\/renderer\/index\.html$/i);
      assert.strictEqual(r.hasBlind, true);
      for (const key of ['api', 'app', 'backendUrl', 'files', 'mcp', 'platform', 'screen', 'settings', 'shell', 'shortcuts', 'version', 'window']) {
        assert.ok(r.keys.includes(key), `window.blind.${key} ausente (chaves: ${r.keys.join(',')})`);
      }
      assert.strictEqual(r.platform, process.platform);
      assert.match(r.version, /^\d+\.\d+\.\d+/);
      assert.match(r.backendUrl, /^http:\/\/127\.0\.0\.1:\d+$/);

      // api.request
      assert.strictEqual(r.status.ok, true);
      assert.strictEqual(r.status.status, 200);
      assert.strictEqual(r.status.data.status, 'ok');
      assert.deepStrictEqual(r.echo.data, { method: 'POST', echo: { a: 1, b: 'x' } });
      assert.strictEqual(r.text.ok, true);
      assert.strictEqual(r.text.data, 'texto simples, nao JSON');
      assert.deepStrictEqual([r.notFound.ok, r.notFound.status], [false, 404]);
      assert.strictEqual(r.notFound.data.detail, 'Not Found');
      for (const name of ['badPath', 'badTraversal', 'badHost', 'badMethod', 'noArgs']) {
        assert.deepStrictEqual([r[name].ok, r[name].status], [false, 0], `${name}: ${JSON.stringify(r[name])}`);
        assert.ok(r[name].error, `${name} sem mensagem de erro`);
      }
      assert.match(r.badMethod.error, /Metodo nao permitido/);
      assert.match(r.badPath.error, /Path invalido/);
      assert.deepStrictEqual([r.slowRequest.ok, r.slowRequest.status], [false, 0]);
      assert.match(r.slowRequest.error, /Tempo esgotado/);

      // mcp (ja existia)
      assert.strictEqual(r.servers.available, true);
      assert.strictEqual(r.servers.servers.length, 2);
      assert.strictEqual(r.tools.tools.length, 2);
      assert.strictEqual(r.call.ok, true);
      assert.strictEqual(r.restart.ok, true);

      // settings
      assert.deepStrictEqual(r.settings, { hotkey: 'Control+Alt+L', closeToTray: true, startHidden: false });
      assert.deepStrictEqual(r.settingsSet, { hotkey: 'Control+Alt+L', closeToTray: false, startHidden: true });

      // files.pick
      assert.strictEqual(r.pickImage.canceled, false, JSON.stringify(r.pickImage));
      assert.strictEqual(r.pickImage.name, 'valid.png');
      assert.strictEqual(r.pickImage.mime, 'image/png');
      assert.strictEqual(r.pickImage.size, png.length);
      assert.ok(r.pickImage.dataUrlPrefix.startsWith('data:image/png;base64,iVBORw0KGgo'));
      assert.strictEqual(r.pickImage.dataUrlLength, `data:image/png;base64,${png.toString('base64')}`.length);
      assert.deepStrictEqual([r.pickDoc.name, r.pickDoc.mime, r.pickDoc.size], ['note.txt', 'text/plain', 11]);
      assert.deepStrictEqual(r.pickBig, { canceled: false, error: 'arquivo grande demais' });
      assert.deepStrictEqual(r.pickWrongType, { canceled: false, error: 'tipo de arquivo não permitido' });
      assert.deepStrictEqual(r.pickCanceled, { canceled: true });
      assert.strictEqual(r.pickBadKind.canceled, false);
      assert.match(r.pickBadKind.error, /tipo invalido/);

      // screen.capture: PNG real da tela principal
      assert.strictEqual(r.capture.ok, true, JSON.stringify(r.capture));
      const prefix = 'data:image/png;base64,';
      assert.ok(r.capture.dataUrlPrefix.startsWith(prefix));
      const header = Buffer.from(r.capture.dataUrlPrefix.slice(prefix.length, prefix.length + 100), 'base64');
      assert.strictEqual(header.subarray(0, 8).toString('hex'), '89504e470d0a1a0a', 'assinatura PNG invalida');
      const width = header.readUInt32BE(16);
      const height = header.readUInt32BE(20);
      assert.ok(width >= 640 && height >= 480, `captura pequena demais: ${width}x${height}`);
      assert.ok(r.capture.dataUrlLength > 10000, 'captura suspeitosamente pequena');

      // permissoes
      assert.strictEqual(r.micState, 'granted', 'microfone deveria estar liberado para o file:// do app');
      assert.strictEqual(r.camState, 'denied', 'camera deveria ser negada');
      assert.strictEqual(r.httpPermission.state, 'denied', JSON.stringify(r.httpPermission));
      assert.strictEqual(r.httpPermission.gum, 'NotAllowedError');
      assert.match(r.httpPermission.origin, /^http:\/\/127\.0\.0\.1:\d+$/);

      // atalhos
      const ids = ['jarvis', 'listen', 'chat', 'screen', 'image', 'docs', 'writer', 'channels', 'tools', 'models', 'home', 'settings', 'activity', 'account'];
      const keys = { jarvis: 'J', listen: 'L', chat: 'C', screen: 'T', image: 'I', docs: 'D', writer: 'E', channels: 'W', tools: 'F', models: 'M', home: 'H', settings: 'S', activity: 'A', account: 'U' };
      for (const id of ids) assert.strictEqual(r.accelerators[id], `Alt+Shift+${keys[id]}`, `acelerador de ${id}`);
      assert.deepStrictEqual(r.shortcutsReceived, ids);
      assert.strictEqual(r.shortcutsAfterUnsubscribe, ids.length, 'recebeu evento depois de cancelar a inscricao');
    });

    await runElectronScenario('backend sem rotas MCP: api.request segue funcionando, mcp.* indisponivel', { FAKE_MCP: '0' }, (r) => {
      assert.strictEqual(r.page, 'app', JSON.stringify(r));
      assert.strictEqual(r.status.ok, true);
      assert.strictEqual(r.servers.available, false);
      assert.match(r.servers.error, /MCP/);
      assert.deepStrictEqual(r.tools.tools, []);
      assert.strictEqual(r.call.ok, false);
    });

    await runElectronScenario('backend que falha: mostra tela de erro com "Tentar novamente"', { FAKE_MODE: 'exit-immediately' }, (r) => {
      assert.strictEqual(r.page, 'error', JSON.stringify(r));
      assert.match(r.title, /Erro ao iniciar/);
      assert.match(r.reason, /encerrou antes de ficar pronto/);
      assert.strictEqual(r.hasRetry, true);
      assert.match(r.info.output, /ModuleNotFoundError/);
      assert.ok(r.info.logDir.endsWith('logs'));
    });
  } finally {
    fs.rmSync(fixtureDir, { recursive: true, force: true });
  }
}

// ---------------------------------------------------------------- main

(async () => {
  console.log('Sintaxe');
  await test('node --check em main.js, preload.js, src/** e scripts/**', async () => {
    const n = checkSyntaxOrThrow();
    assert.ok(n >= 8);
  });

  console.log('Supervisor do backend (backend falso)');
  await supervisorTests();

  console.log('Cliente da API (servidores HTTP falsos)');
  await apiTests();

  if (WITH_ELECTRON) {
    console.log('Electron real contra backend falso');
    await electronTests();
  } else {
    console.log('Electron real: pulado (use --electron)');
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} testes passaram${WITH_ELECTRON ? '' : ' (sem Electron real)'}.`);
  // Sem process.exit() imediato: no Node 24/Windows ele pode acionar um assert do libuv
  // enquanto handles de processos filhos ainda estao fechando. O timer forca a saida se algo ficar preso.
  process.exitCode = failed.length ? 1 : 0;
  setTimeout(() => process.exit(process.exitCode), 3000).unref();
})();
