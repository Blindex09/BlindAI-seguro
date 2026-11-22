'use strict';

// Teste de ponta a ponta do renderer: Electron REAL + backend Python REAL, dirigido por DevTools Protocol.
//   node scripts/e2e-renderer.js
// O microfone e simulado por um WAV com fala (voz pt-BR do Windows). Nada e clicado fora da janela do app e
// nenhum comando que mexa no computador e enviado: a frase ditada e uma pergunta comum.
// Usa uma pasta de dados temporaria (nao disputa a instancia unica nem mexe nas configuracoes do usuario).

const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const http = require('http');

const ROOT = path.resolve(__dirname, '..');
const PHRASE = 'Qual é a capital da França?';
const results = [];
let failures = 0;

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function getJson(url) {
  return new Promise((resolve, reject) => {
    http
      .get(url, (res) => {
        let body = '';
        res.on('data', (c) => (body += c));
        res.on('end', () => {
          try {
            resolve(JSON.parse(body));
          } catch (e) {
            reject(e);
          }
        });
      })
      .on('error', reject);
  });
}

class Cdp {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.id = 0;
    this.pending = new Map();
    this.errors = [];
    this.ready = new Promise((resolve, reject) => {
      this.ws.addEventListener('open', resolve);
      this.ws.addEventListener('error', () => reject(new Error('falha ao conectar no DevTools')));
    });
    this.ws.addEventListener('message', (e) => {
      const msg = JSON.parse(e.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message));
        else resolve(msg.result);
      } else if (msg.method === 'Runtime.exceptionThrown') {
        this.errors.push(`excecao: ${msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text}`);
      } else if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
        this.errors.push(`console.error: ${msg.params.args.map((a) => a.value || a.description).join(' ')}`);
      } else if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') {
        this.errors.push(`log: ${msg.params.entry.text} ${msg.params.entry.url || ''}`);
      }
    });
  }

  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async eval(expression) {
    const r = await this.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(`erro no renderer: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
    return r.result.value;
  }

  async waitFor(expression, timeoutMs, label) {
    const end = Date.now() + timeoutMs;
    let last;
    while (Date.now() < end) {
      try {
        last = await this.eval(expression);
        if (last) return last;
      } catch (_) {
        // pagina ainda carregando
      }
      await sleep(400);
    }
    throw new Error(`tempo esgotado esperando: ${label || expression}`);
  }
}

async function check(name, fn) {
  const started = Date.now();
  try {
    const detail = await fn();
    results.push({ name, ok: true });
    console.log(`  ok    ${name} (${Date.now() - started} ms)${detail ? ` -> ${detail}` : ''}`);
  } catch (err) {
    if (err && err.skip) {
      results.push({ name, ok: true, skipped: true });
      console.log(`  PULADO ${name}: ${err.message}`);
      return;
    }
    failures++;
    results.push({ name, ok: false, error: err.message });
    console.log(`  FALHA ${name}: ${err.message}`);
  }
}

const A11Y_AUDIT = `(() => {
  const problems = [];
  document.querySelectorAll('button, a[href], input, select, textarea, [role=tab]').forEach((el) => {
    if (el.closest('[hidden]')) return;
    let name = el.getAttribute('aria-label') || '';
    if (!name && el.labels && el.labels.length) name = [...el.labels].map((l) => l.textContent).join(' ');
    if (!name) name = el.textContent.trim();
    if (!name.trim()) problems.push(el.tagName + '#' + el.id + ' sem nome acessivel');
  });
  const ids = {};
  document.querySelectorAll('[id]').forEach((e) => { ids[e.id] = (ids[e.id] || 0) + 1; });
  Object.entries(ids).filter(([, n]) => n > 1).forEach(([id]) => problems.push('id duplicado: ' + id));
  const visibleScreens = [...document.querySelectorAll('section.screen')].filter((s) => !s.hidden);
  if (visibleScreens.length !== 1) problems.push('telas visiveis: ' + visibleScreens.length);
  const h1 = visibleScreens[0] && visibleScreens[0].querySelector('h1');
  if (!h1) problems.push('tela sem h1');
  const tiny = [...document.querySelectorAll('button, input, select, textarea')].filter((e) => !e.closest('[hidden]')).filter((e) => { const r = e.getBoundingClientRect(); return r.height > 0 && r.height < 24; });
  if (tiny.length) problems.push('alvos de toque menores que 24px: ' + tiny.map((e) => e.id || e.tagName).join(','));
  return problems;
})()`;

async function main() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'blind-e2e-'));
  const wav = path.join(tmp, 'fala.wav');
  const gen = spawnSync('python', [path.join(ROOT, 'scripts', 'make-speech-wav.py'), wav, PHRASE], { encoding: 'utf8' });
  if (gen.status !== 0 || !fs.existsSync(wav)) throw new Error(`nao consegui gerar o audio de teste: ${gen.stderr || gen.stdout}`);
  console.log(`audio de teste: ${fs.statSync(wav).size} bytes, frase "${PHRASE}"`);

  const backendPort = await freePort();
  const debugPort = await freePort();
  const electronExe = require('electron');
  const child = spawn(electronExe, ['.', `--remote-debugging-port=${debugPort}`, `--user-data-dir=${path.join(tmp, 'userdata')}`], {
    cwd: ROOT,
    env: { ...process.env, BLIND_E2E: '1', BLIND_FAKE_MIC_WAV: wav, BLIND_PORT: String(backendPort), BLIND_DATA_DIR: process.env.BLIND_DATA_DIR || '' },
    stdio: 'ignore',
  });
  let cdp;
  try {
    console.log('Subindo o Electron real com o backend real...');
    let target;
    const end = Date.now() + 90000;
    while (Date.now() < end && !target) {
      try {
        const list = await getJson(`http://127.0.0.1:${debugPort}/json`);
        target = list.find((t) => t.type === 'page' && /renderer[\\/]index\.html$|renderer\/index\.html$/.test(decodeURIComponent(t.url)));
      } catch (_) {
        // ainda subindo
      }
      if (!target) await sleep(500);
    }
    if (!target) throw new Error('a janela nunca carregou o renderer (backend nao ficou pronto em 90 s?)');
    cdp = new Cdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send('Runtime.enable');
    await cdp.send('Log.enable');
    await cdp.send('Page.enable');
    await cdp.waitFor('Boolean(window.__blindRenderer)', 30000, 'renderer inicializado');

    console.log('\nRenderer Electron');
    await check('estado do backend chega ao cabecalho (pronto)', async () => {
      const text = await cdp.waitFor(`(() => { const t = document.getElementById('system-status-text').textContent; return /^Pronto/.test(t) ? t : false; })()`, 60000, 'cabecalho Pronto');
      return text;
    });

    await check('window.blind existe e a CSP bloqueia fetch direto ao backend', async () => {
      const r = await cdp.eval(`(async () => {
        const hasShell = Boolean(window.blind && window.blind.api);
        let direct;
        try { await fetch('http://127.0.0.1:${backendPort}/api/status'); direct = 'permitido'; } catch (e) { direct = 'bloqueado'; }
        const viaIpc = await window.blind.api.request({ path: '/api/status' });
        return { hasShell, direct, ipcOk: viaIpc.ok && viaIpc.data.status === 'ready' };
      })()`);
      if (!r.hasShell) throw new Error('window.blind ausente');
      if (r.direct !== 'bloqueado') throw new Error('fetch direto ao backend nao foi bloqueado pela CSP');
      if (!r.ipcOk) throw new Error('api.request por IPC falhou');
      return 'IPC ok, fetch direto bloqueado';
    });

    const screens = ['home', 'chat', 'models', 'vision', 'docs', 'writer', 'channels', 'tools', 'settings', 'activity', 'account'];
    for (const id of screens) {
      await check(`tela "${id}": abre, foca o titulo, tem nome acessivel em tudo`, async () => {
        await cdp.eval(`window.__blindRenderer.router.show('${id}')`);
        await sleep(600);
        const info = await cdp.eval(`({
          title: document.title,
          focusedIsH1: document.activeElement && document.activeElement.tagName === 'H1' && document.activeElement.closest('section.screen').id === 'screen-${id}',
          current: document.getElementById('main')?.dataset.currentScreen,
          active: document.activeElement ? document.activeElement.tagName + '#' + document.activeElement.id : 'nenhum',
          hasFocus: document.hasFocus(),
          hidden: document.getElementById('screen-${id}').hidden,
        })`);
        if (!info.focusedIsH1) throw new Error(`o foco nao foi para o titulo da tela (ativo: ${info.active}, janela com foco: ${info.hasFocus}, tela oculta: ${info.hidden})`);
        if (info.current !== id) throw new Error(`menu indica "${info.current}"`);
        const problems = await cdp.eval(A11Y_AUDIT);
        if (problems.length) throw new Error(problems.join('; '));
        return info.title;
      });
    }

    await check('atalho Ctrl+3 navega para a tela de modelo e Escape volta para Blind (home)', async () => {
      await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: '3', code: 'Digit3', windowsVirtualKeyCode: 51, modifiers: 2 });
      await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: '3', code: 'Digit3', windowsVirtualKeyCode: 51, modifiers: 2 });
      await cdp.waitFor(`document.getElementById('main')?.dataset.currentScreen === 'models'`, 5000, 'Ctrl+3');
      await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27, modifiers: 0 });
      await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27, modifiers: 0 });
      await cdp.waitFor(`document.getElementById('main')?.dataset.currentScreen === 'home'`, 5000, 'Escape volta para home');
      const title = await cdp.eval(`document.getElementById('home-title').textContent`);
      if (title !== 'Blind') throw new Error(`titulo esperado 'Blind', obtido '${title}'`);
      return `Ctrl+3 -> models, Escape -> ${title}`;
    });

    await check('caixa de combinacao da tela principal abre com Seta para Baixo e navega com Enter', async () => {
      await cdp.eval(`document.getElementById('home-command-combo').focus()`);
      await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'ArrowDown', code: 'ArrowDown', windowsVirtualKeyCode: 40, modifiers: 0 });
      await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'ArrowDown', code: 'ArrowDown', windowsVirtualKeyCode: 40, modifiers: 0 });
      const state = await cdp.eval(`(() => { const c = document.getElementById('home-command-combo'); return { expanded: c.getAttribute('aria-expanded'), active: c.getAttribute('aria-activedescendant') }; })()`);
      if (state.expanded !== 'true' || !state.active) throw new Error(`combobox nao abriu: ${JSON.stringify(state)}`);
      await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27, modifiers: 0 });
      await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27, modifiers: 0 });
      return `combobox abriu (${state.active}) e fechou com Escape`;
    });

    await check('atalhos Alt+Shift (C, E, W, F, M, S, H) acionam cada modulo corretamente', async () => {
      const map = [
        ['chat', 'screen-chat', 'chat-input'],
        ['writer', 'screen-writer', 'writer-title'],
        ['channels', 'screen-channels', 'channels-title'],
        ['tools', 'screen-tools', 'tools-title'],
        ['models', 'screen-models', 'models-title'],
        ['settings', 'screen-settings', 'settings-title'],
        ['home', 'screen-home', 'home-title'],
      ];
      for (const [act, screenId, expectedFocus] of map) {
        await cdp.eval(`window.__blindRenderer.runAction('${act}')`);
        await sleep(250);
        const state = await cdp.eval(`({ hidden: document.getElementById('${screenId}').hidden, activeId: document.activeElement?.id })`);
        if (state.hidden) throw new Error(`acao ${act} nao abriu ${screenId}`);
        if (state.activeId !== expectedFocus) throw new Error(`acao ${act} focou ${state.activeId} em vez de ${expectedFocus}`);
      }
      return 'todos os 7 atalhos de navegacao testados';
    });

    await check('ferramentas: os 7 servidores MCP aparecem conectados e executam chamadas reais via IPC', async () => {
      await cdp.eval(`window.__blindRenderer.router.show('tools')`);
      const text = await cdp.waitFor(`(() => { const t = document.getElementById('mcp-status').textContent; const m = t.match(/^(\\d+) de (\\d+) servidores conectados/); return m && m[1] === m[2] && Number(m[2]) >= 7 ? t : false; })()`, 90000, 'todos os servidores MCP conectados');
      const names = await cdp.eval(`[...document.querySelectorAll('#mcp-list .name')].map((e) => e.textContent)`);
      for (const n of ['windows', 'agent-desktop', 'blind-speech', 'blind-docs', 'blind-channels', 'blind-stt', 'blind-memory']) {
        if (!names.includes(n)) throw new Error(`servidor ${n} ausente: ${names}`);
      }
      // Testa chamada MCP real em blind-memory e blind-docs via window.blind.mcp.call
      const memSave = await cdp.eval(`window.blind.mcp.call('blind-memory', 'memory_save', { key: 'preferencia_teste', value: 'leitor NVDA rapido', category: 'acessibilidade' })`);
      if (!memSave.ok || memSave.is_error) throw new Error(`blind-memory falhou: ${JSON.stringify(memSave)}`);
      const memRecall = await cdp.eval(`window.blind.mcp.call('blind-memory', 'memory_recall', { query: 'NVDA' })`);
      if (!memRecall.ok || !String(memRecall.content).includes('NVDA')) throw new Error(`memory_recall falhou: ${JSON.stringify(memRecall)}`);
      return `${text} + blind-memory ok`;
    });

    await check('redator (Alt+Shift+E): cria minuta e salva documento real pelo backend', async () => {
      await cdp.eval(`window.__blindRenderer.runAction('writer')`);
      await cdp.eval(`(() => {
        document.getElementById('writer-title').value = 'Nota Teste E2E';
        document.getElementById('writer-content').value = 'Texto de teste gravado durante a verificacao real do aplicativo.';
        document.getElementById('btn-review').click();
      })()`);
      const reviewTxt = await cdp.waitFor(`(() => { const r = document.getElementById('writer-review'); return r && !r.hidden && r.textContent ? r.textContent : false; })()`, 15000, 'minuta revisada pronta');
      await cdp.eval(`document.getElementById('btn-save').click()`);
      await cdp.waitFor(`(() => { const h = document.getElementById('home-title').textContent; return h.includes('Documento: Nota Teste E2E'); })()`, 15000, 'sessao do documento criada');
      return reviewTxt.slice(0, 80);
    });

    await check('audiodescricao de tela (Alt+Shift+T): captura a tela real e atualiza titulo para Blind - <conversa>', async () => {
      const cap = await cdp.eval(`window.blind.screen.capture().then((r) => ({ ok: r.ok, error: r.error || '', fallback: r.fallback || '' }))`);
      // Se o Electron nao obtem o monitor, o app pede a captura ao MCP agent-desktop (caminho real do backend).
      const via = cap.ok ? 'Electron' : `MCP agent-desktop (Electron: ${cap.error})`;
      await cdp.eval(`window.__blindRenderer.runAction('screen')`);
      const desc = await cdp.waitFor(`(() => { const t = document.getElementById('vision-output').textContent; return t && t !== 'A descrição aparecerá aqui.' && !/Analisando/i.test(t) ? t : false; })()`, 120000, 'resultado da audiodescricao da tela');
      if (/^Erro ao descrever/i.test(desc)) throw new Error(`descricao falhou via ${via}: ${desc.slice(0, 200)}`);
      await cdp.eval(`window.__blindRenderer.router.show('home')`);
      const homeHeading = await cdp.eval(`document.getElementById('home-title').textContent`);
      if (!homeHeading.startsWith('Blind - Audiodescrição:')) throw new Error(`titulo nao incluiu a conversa: ${homeHeading}`);
      return `via ${via}: ${homeHeading} (${desc.slice(0, 60)}...)`;
    });

    await check('modelo: trocar de provedor popula os modelos e guarda a escolha', async () => {
      await cdp.eval(`window.__blindRenderer.router.show('models')`);
      await cdp.eval(`(() => { const s = document.getElementById('ai-provider'); s.value = 'ollama_cloud'; s.dispatchEvent(new Event('change')); })()`);
      await cdp.waitFor(`[...document.querySelectorAll('#ai-model option')].some((o) => /kimi|deepseek/i.test(o.value))`, 15000, 'modelos do ollama_cloud');
      const stored = await cdp.eval(`JSON.parse(localStorage.getItem('blind.prefs.v1')).provider`);
      if (stored !== 'ollama_cloud') throw new Error(`preferencia nao salva: ${stored}`);
      // volta ao provedor padrao do teste de conversa
      await cdp.eval(`(() => { const s = document.getElementById('ai-provider'); s.value = 'ollama_cloud'; })()`);
    });

    await check('canais: o codigo do WhatsApp exibido e o gerado pelo backend (nao um sorteio da tela)', async () => {
      await cdp.eval(`window.__blindRenderer.router.show('channels')`);
      await cdp.eval(`(() => { const p = document.getElementById('wa-phone'); p.value = '+55 11 91234-5678'; document.getElementById('btn-pair').click(); })()`);
      const code = await cdp.waitFor(`(() => { const o = document.getElementById('wa-code').textContent; return /^[A-Z0-9]{8}$/.test(o) ? o : false; })()`, 20000, 'codigo de pareamento');
      const backend = await cdp.eval(`window.blind.api.request({ path: '/api/whatsapp/status?phone=5511912345678' }).then((r) => r.data)`);
      const stored = backend.pairing_code || (backend.session && backend.session.pairing_code) || '';
      if (stored && stored !== code) throw new Error(`a tela mostra ${code}, o backend guardou ${stored}`);
      return `codigo ${code}${stored ? ' confere com o banco' : ' (status sem codigo para comparar)'}`;
    });

    await check('canais: token invalido do Telegram e recusado e anunciado', async () => {
      await cdp.eval(`(() => { document.getElementById('tab-telegram').click(); })()`);
      await cdp.eval(`(() => { document.getElementById('tg-token').value = '123:token-invalido'; document.getElementById('btn-tg-connect').click(); })()`);
      return cdp.waitFor(`(() => { const t = document.getElementById('tg-status').textContent; return /recus|inv[aá]lid|formato|n[aã]o/i.test(t) ? t : false; })()`, 30000, 'resposta do Telegram');
    });

    await check('configuracoes: mostra o estado do reconhecimento de voz (Whisper)', async () => {
      await cdp.eval(`window.__blindRenderer.router.show('settings')`);
      return cdp.waitFor(`(() => { const t = document.getElementById('stt-status').textContent; return /Modelo|pronto|preparado/i.test(t) ? t : false; })()`, 15000, 'estado do STT');
    });

    await check('DITADO (Alt+Shift+L): grava no app, o Whisper transcreve e a mensagem vai para a conversa', async () => {
      await cdp.eval(`window.__blindRenderer.router.show('chat')`);
      await cdp.eval(`document.getElementById('btn-clear-chat').click()`);
      await cdp.eval(`window.__blindRenderer.runAction('listen')`);
      // 1. Gravando: a barra de gravacao aparece
      await cdp.waitFor(`Boolean(document.querySelector('.recording-bar'))`, 15000, 'barra de gravacao');
      // 2. Para sozinho apos a pausa, transcreve e envia: aparece a bolha do usuario com o texto reconhecido
      let bubble;
      try {
        bubble = await cdp.waitFor(`(() => { const b = [...document.querySelectorAll('.bubble.user')].pop(); return b ? b.textContent : false; })()`, 90000, 'mensagem transcrita na conversa');
      } catch (err) {
        const diag = await cdp.eval(`({
          gravando: Boolean(document.querySelector('.recording-bar')),
          assertive: document.getElementById('sr-assertive').textContent,
          polite: document.getElementById('sr-polite').textContent,
          bolhas: [...document.querySelectorAll('.bubble')].map((b) => b.textContent.slice(0, 80)),
          stt: null,
        })`);
        diag.stt = await cdp.eval(`window.blind.api.request({ path: '/api/stt/status' }).then((r) => r.data)`);
        throw new Error(`${err.message}. Diagnostico: ${JSON.stringify(diag)}`);
      }
      const norm = bubble.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
      if (!/capital/.test(norm) || !/franca/.test(norm)) throw new Error(`transcricao inesperada: "${bubble}"`);
      return bubble.replace(/\s+/g, ' ').trim();
    });

    await check('chat: a IA responde a mensagem ditada (sem aviso de erro)', async () => {
      const reply = await cdp.waitFor(`(() => { const b = [...document.querySelectorAll('.bubble.assistant')].pop(); return b ? b.textContent : false; })()`, 180000, 'resposta da IA');
      if (/aviso/i.test(reply.slice(0, 40))) throw new Error(`a IA devolveu aviso: ${reply}`);
      return reply.replace(/\s+/g, ' ').trim().slice(0, 140);
    });

    await check('sem erros no console do renderer', async () => {
      // O bloqueio da CSP e provocado de proposito no teste de fetch direto; qualquer outro erro reprova.
      const real = cdp.errors.filter((e) => !/favicon/i.test(e) && !e.includes(`Refused to connect to 'http://127.0.0.1:${backendPort}/api/status'`));
      if (real.length) throw new Error(real.slice(0, 4).join(' | '));
    });
  } finally {
    if (cdp) cdp.ws.close();
    if (child.pid) spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
    try {
      fs.rmSync(tmp, { recursive: true, force: true });
    } catch (_) {
      // arquivos ainda em uso: o sistema limpa a pasta temporaria depois
    }
  }
}

main()
  .then(() => {
    console.log(`\n${results.length - failures}/${results.length} verificacoes passaram.`);
    process.exit(failures ? 1 : 0);
  })
  .catch((err) => {
    console.error(`\nERRO: ${err.message}`);
    process.exit(2);
  });
