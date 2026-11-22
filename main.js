'use strict';

// Blind AI - processo principal do Electron.
// Supervisiona o backend Python (server.py), mostra a interface em uma janela segura,
// e expoe IPC para a UI falar com o backend sem conhecer a porta.

const {
  app,
  BrowserWindow,
  Menu,
  Tray,
  globalShortcut,
  ipcMain,
  session,
  desktopCapturer,
  dialog,
  screen,
  shell,
} = require('electron');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { fileURLToPath } = require('url');

const { BackendSupervisor } = require('./src/supervisor');
const { createLogger } = require('./src/logger');
const { createSettings } = require('./src/settings');
const { createApi } = require('./src/api');
const { createIcon } = require('./src/icon');

const SMOKE = process.env.BLIND_SMOKE === '1';
const DEV = process.argv.includes('--dev') || process.env.BLIND_DEV === '1';

// Somente testes de ponta a ponta (BLIND_E2E=1): microfone simulado por um arquivo WAV, tocado uma vez.
// Nunca ativo no uso normal.
if (process.env.BLIND_E2E === '1' && process.env.BLIND_FAKE_MIC_WAV) {
  app.commandLine.appendSwitch('use-fake-device-for-media-stream');
  app.commandLine.appendSwitch('use-fake-ui-for-media-stream');
  app.commandLine.appendSwitch('use-file-for-fake-audio-capture', `${process.env.BLIND_FAKE_MIC_WAV}%noloop`);
}

const PAGES_DIR = path.join(__dirname, 'src', 'pages');
const RENDERER_DIR = path.join(__dirname, 'src', 'renderer');
const RENDERER_INDEX = path.join(RENDERER_DIR, 'index.html');
const MAX_PICK_BYTES = 25 * 1024 * 1024;

// Tipos aceitos por files.pick (extensao -> mime).
const PICK_KINDS = {
  image: { label: 'Imagens', types: { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif' } },
  document: {
    label: 'Documentos',
    types: {
      pdf: 'application/pdf',
      txt: 'text/plain',
      docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    },
  },
};

// Ids enviados em 'blind:shortcut' (aceleradores locais Alt+Shift+<letra> do menu).
const SHORTCUTS = [
  { id: 'jarvis', key: 'J', label: 'Modo Jarvis (voz contínua)' },
  { id: 'listen', key: 'L', label: 'Ouvir voz' },
  { id: 'chat', key: 'C', label: 'Conversar com a IA' },
  { id: 'screen', key: 'T', label: 'Descrever tela' },
  { id: 'image', key: 'I', label: 'Descrever imagem' },
  { id: 'docs', key: 'D', label: 'Ler fatura ou PDF' },
  { id: 'writer', key: 'E', label: 'Redigir ou ditar' },
  { id: 'channels', key: 'W', label: 'WhatsApp e Telegram' },
  { id: 'tools', key: 'F', label: 'Ferramentas (MCP)' },
  { id: 'models', key: 'M', label: 'Modelos de IA' },
  { id: 'home', key: 'H', label: 'Início' },
  { id: 'settings', key: 'S', label: 'Configurações' },
  { id: 'activity', key: 'A', label: 'Atividades (o que deu certo e errado)' },
  { id: 'account', key: 'U', label: 'Conta e Assinatura' },
];

// No smoke test o userData e temporario: nao disputa o lock de instancia unica
// com o app real do usuario nem mexe nos logs/configuracoes dele.
if (SMOKE) {
  app.setPath('userData', process.env.BLIND_SMOKE_USERDATA || fs.mkdtempSync(path.join(os.tmpdir(), 'blind-smoke-')));
}

if (process.platform === 'win32') app.setAppUserModelId('ai.blind.desktop');

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  bootstrap();
}

function bootstrap() {
  const userData = app.getPath('userData');
  const logDir = path.join(userData, 'logs');
  const mainLog = createLogger(logDir, 'main.log');
  const backendLog = createLogger(logDir, 'backend.log');
  const settings = createSettings(userData);

  let win = null;
  let tray = null;
  let quitting = false;
  let shownPage = null; // 'loading' | 'error' | 'app'
  let lastState = { state: 'stopped', attempt: 0, error: null, output: '' };

  process.on('uncaughtException', (err) => mainLog.error(`uncaughtException: ${err && err.stack ? err.stack : err}`));
  process.on('unhandledRejection', (err) => mainLog.error(`unhandledRejection: ${err && err.stack ? err.stack : err}`));
  mainLog.info(`Blind AI ${app.getVersion()} iniciando (electron ${process.versions.electron}, dev=${DEV}, smoke=${SMOKE})`);

  // ------------------------------------------------------------ backend

  const backendDir =
    process.env.BLIND_BACKEND_DIR ||
    (app.isPackaged ? path.join(process.resourcesPath, 'backend') : path.join(__dirname, 'backend'));

  const backendEnv = { PYTHONUTF8: '1', PYTHONUNBUFFERED: '1' };
  const mcpConfig = path.join(backendDir, 'mcp.json');
  if (!process.env.BLIND_MCP_CONFIG && fs.existsSync(mcpConfig)) backendEnv.BLIND_MCP_CONFIG = mcpConfig;
  // Instalado, a pasta do backend pode ser somente leitura: dados vao para userData.
  if (!process.env.BLIND_DATA_DIR && app.isPackaged) backendEnv.BLIND_DATA_DIR = path.join(userData, 'data');

  // Eventos do supervisor vao para main.log; a saida do processo do backend vai para backend.log.
  const supervisor = new BackendSupervisor({
    command: process.env.BLIND_PYTHON || 'python',
    args: [process.env.BLIND_BACKEND_SCRIPT || 'server.py'],
    cwd: backendDir,
    env: backendEnv,
    preferredPort: Number(process.env.BLIND_PORT) || 8765,
    healthTimeoutMs: Number(process.env.BLIND_HEALTH_TIMEOUT_MS) || 30000,
    logger: {
      info: (m) => mainLog.info(m),
      warn: (m) => mainLog.warn(m),
      error: (m) => mainLog.error(m),
      raw: (source, text) => backendLog.raw(source, text),
    },
  });

  const baseUrl = () => (supervisor.state === 'ready' && supervisor.port ? `http://127.0.0.1:${supervisor.port}` : '');
  const api = createApi({ getBaseUrl: baseUrl });

  // ------------------------------------------------------------ urls confiaveis

  // Confiavel = arquivo dentro de src/renderer ou src/pages. O backend nao serve mais a UI
  // e nenhuma origem http e confiavel: a UI so fala com o backend via IPC (window.blind.api).
  function isAllowedUrl(urlString) {
    try {
      const url = new URL(urlString);
      if (url.protocol !== 'file:') return false;
      const file = path.normalize(fileURLToPath(url));
      const lower = process.platform === 'win32';
      return [RENDERER_DIR, PAGES_DIR].some((base) => {
        const dir = base + path.sep;
        return lower ? file.toLowerCase().startsWith(dir.toLowerCase()) : file.startsWith(dir);
      });
    } catch (_) {
      return false;
    }
  }

  function openExternalSafely(urlString) {
    try {
      const { protocol } = new URL(urlString);
      if (protocol === 'http:' || protocol === 'https:' || protocol === 'mailto:') shell.openExternal(urlString);
    } catch (_) {
      // ignorado
    }
  }

  // ------------------------------------------------------------ janela

  function loadPage(name) {
    if (!win) return;
    shownPage = name === 'loading.html' ? 'loading' : 'error';
    win.loadFile(path.join(PAGES_DIR, name)).catch((err) => mainLog.error(`falha ao carregar ${name}: ${err.message}`));
  }

  // Backend pronto: carrega o renderer (file://.../src/renderer/index.html).
  function loadApp() {
    if (!win) return;
    if (!fs.existsSync(RENDERER_INDEX)) {
      mainLog.error(`interface nao encontrada: ${RENDERER_INDEX}`);
      lastState = { ...lastState, state: 'failed', error: `Interface não encontrada: ${RENDERER_INDEX}`, output: '' };
      loadPage('error.html');
      return;
    }
    shownPage = 'app';
    win.loadFile(RENDERER_INDEX).catch((err) => mainLog.error(`falha ao carregar a UI: ${err.message}`));
  }

  function createWindow() {
    win = new BrowserWindow({
      width: 1280,
      height: 860,
      minWidth: 720,
      minHeight: 520,
      show: false,
      title: 'Blind',
      backgroundColor: '#0f172a',
      icon: createIcon(32),
      autoHideMenuBar: true,
      webPreferences: {
        preload: path.join(__dirname, 'preload.js'),
        contextIsolation: true,
        sandbox: true,
        nodeIntegration: false,
        webSecurity: true,
        additionalArguments: [`--blind-version=${app.getVersion()}`],
      },
    });

    win.once('ready-to-show', () => {
      if (!SMOKE && !settings.get().startHidden) win.show();
    });

    win.on('close', (event) => {
      if (!quitting && !SMOKE && settings.get().closeToTray) {
        event.preventDefault();
        win.hide();
      }
    });
    win.on('closed', () => {
      win = null;
    });

    const wc = win.webContents;
    wc.setWindowOpenHandler(({ url }) => {
      openExternalSafely(url);
      return { action: 'deny' };
    });
    const guard = (event, url) => {
      if (!isAllowedUrl(url)) {
        event.preventDefault();
        openExternalSafely(url);
      }
    };
    wc.on('will-navigate', guard);
    wc.on('will-redirect', guard);
    wc.on('render-process-gone', (_event, details) => {
      mainLog.error(`renderer caiu: ${details.reason}`);
      if (!quitting && details.reason !== 'clean-exit') wc.reload();
    });
    wc.on('did-finish-load', () => onPageLoaded());
    if (DEV) wc.on('did-finish-load', () => !wc.isDevToolsOpened() && shownPage === 'app' && wc.openDevTools({ mode: 'detach' }));

    loadPage('loading.html');
  }

  function showWindow() {
    if (!win) createWindow();
    if (win.isMinimized()) win.restore();
    win.show();
    if (process.platform === 'win32') {
      win.setAlwaysOnTop(true);
      win.focus();
      win.setAlwaysOnTop(false);
    } else {
      win.focus();
    }
  }

  function hideWindow() {
    if (win) win.hide();
  }

  // ------------------------------------------------------------ estado do backend

  function publicState(s) {
    return {
      state: s.state,
      attempt: s.attempt || 0,
      error: s.error || null,
      output: s.output || '',
    };
  }

  supervisor.on('state', (s) => {
    lastState = { ...lastState, ...publicState(s) };
    if (s.state !== 'failed') lastState.output = '';
    mainLog.info(`estado do backend: ${s.state}${s.port ? ` (porta ${s.port})` : ''}${s.error ? ` - ${s.error}` : ''}`);
    if (win && !win.isDestroyed()) win.webContents.send('blind:backend-state', lastState);
    updateTray();

    if (s.state === 'failed') {
      loadPage('error.html');
    } else if (s.state === 'starting' && shownPage === 'error') {
      loadPage('loading.html');
    } else if (s.state === 'ready') {
      // O renderer fala com o backend so por IPC (a porta e resolvida a cada chamada):
      // reinicio do backend ou mudanca de porta nao exigem recarregar a UI.
      if (shownPage !== 'app') loadApp();
    }
  });

  function startBackend() {
    supervisor.start().catch((err) => {
      if (err.code !== 'ECANCELLED') mainLog.error(`start falhou: ${err.message}`);
    });
  }

  function restartBackend() {
    supervisor.restart().catch((err) => {
      if (err.code !== 'ECANCELLED') mainLog.error(`restart falhou: ${err.message}`);
    });
  }

  // ------------------------------------------------------------ tray, menu, atalho

  function updateTray() {
    if (!tray) return;
    const labels = {
      starting: 'iniciando',
      ready: 'pronto',
      restarting: 'reiniciando o serviço',
      failed: 'erro ao iniciar',
      stopped: 'parado',
    };
    tray.setToolTip(`Blind AI - ${labels[lastState.state] || lastState.state}`);
  }

  function createTray() {
    tray = new Tray(createIcon(32));
    tray.setContextMenu(
      Menu.buildFromTemplate([
        { label: 'Mostrar Blind AI', click: showWindow },
        { label: 'Ocultar Blind AI', click: hideWindow },
        { type: 'separator' },
        { label: 'Reiniciar serviço', click: restartBackend },
        { label: 'Abrir pasta de logs', click: () => shell.openPath(logDir) },
        { type: 'separator' },
        { label: 'Sair', click: quitApp },
      ]),
    );
    tray.on('click', showWindow);
    updateTray();
  }

  function createMenu() {
    const view = [
      { role: 'reload', label: 'Recarregar' },
      { role: 'resetZoom', label: 'Zoom padrão' },
      { role: 'zoomIn', label: 'Aumentar zoom' },
      { role: 'zoomOut', label: 'Diminuir zoom' },
      { role: 'togglefullscreen', label: 'Tela cheia' },
    ];
    if (DEV) view.push({ type: 'separator' }, { role: 'toggleDevTools', label: 'Ferramentas do desenvolvedor' });
    Menu.setApplicationMenu(
      Menu.buildFromTemplate([
        {
          label: 'Blind AI',
          submenu: [
            { label: 'Mostrar', click: showWindow },
            { label: 'Ocultar', click: hideWindow },
            { label: 'Reiniciar serviço', click: restartBackend },
            { label: 'Abrir pasta de logs', click: () => shell.openPath(logDir) },
            { type: 'separator' },
            { label: 'Sair', accelerator: 'CommandOrControl+Q', click: quitApp },
          ],
        },
        {
          // Aceleradores locais: so funcionam com a janela em foco. A barra fica oculta
          // (autoHideMenuBar), mas os atalhos continuam ativos; Alt mostra a barra.
          label: 'Atalhos',
          submenu: SHORTCUTS.map(({ id, key, label }) => ({
            id: `shortcut-${id}`,
            label,
            accelerator: `Alt+Shift+${key}`,
            click: () => sendShortcut(id),
          })),
        },
        { label: 'Exibir', submenu: view },
      ]),
    );
  }

  function sendShortcut(id) {
    if (win && !win.isDestroyed() && shownPage === 'app') win.webContents.send('blind:shortcut', id);
  }

  function registerHotkey(accelerator) {
    globalShortcut.unregisterAll();
    if (!accelerator) return { ok: true };
    try {
      if (!globalShortcut.register(accelerator, showWindow)) {
        return { ok: false, error: 'Atalho já está em uso por outro programa.' };
      }
      return { ok: true };
    } catch (_) {
      return { ok: false, error: 'Atalho inválido. Exemplo: Control+Alt+L.' };
    }
  }

  function quitApp() {
    quitting = true;
    app.quit();
  }

  // ------------------------------------------------------------ IPC

  function isTrustedSender(event) {
    if (!win || event.sender !== win.webContents) return false;
    const url = (event.senderFrame && event.senderFrame.url) || event.sender.getURL();
    return isAllowedUrl(url);
  }

  function handle(channel, fn) {
    ipcMain.handle(channel, (event, ...args) => {
      if (!isTrustedSender(event)) throw new Error('Remetente não autorizado.');
      return fn(...args);
    });
  }

  const validName = (v) => typeof v === 'string' && v.length > 0 && v.length <= 200;

  handle('blind:app:backend-url', () => baseUrl());
  handle('blind:app:info', () => ({
    version: app.getVersion(),
    platform: process.platform,
    logDir,
    ...lastState,
  }));
  handle('blind:app:retry', () => {
    startBackend();
    return { ok: true };
  });

  handle('blind:mcp:servers', () => api.mcpServers());
  handle('blind:mcp:tools', () => api.mcpTools());
  handle('blind:mcp:restart', (name) => {
    if (!validName(name)) return { ok: false, error: 'Nome de servidor inválido.' };
    return api.mcpRestart(name);
  });
  handle('blind:mcp:call', (server, tool, args) => {
    if (!validName(server) || !validName(tool)) return { ok: false, content: null, is_error: true, error: 'Servidor ou ferramenta inválidos.' };
    const safeArgs = args && typeof args === 'object' && !Array.isArray(args) ? args : {};
    return api.mcpCall(server, tool, safeArgs);
  });

  // Proxy HTTP para o backend (a UI nao faz fetch): so /api/ e /v1/, validado em src/api.js.
  handle('blind:api:request', (options) => api.proxy(options));

  // Seletor de arquivo: le no main e devolve data URL (limite 25 MB). Em modo smoke,
  // BLIND_TEST_PICK_FILE substitui o dialogo (nunca fora do smoke).
  const smokePicks = SMOKE && process.env.BLIND_TEST_PICK_FILE ? process.env.BLIND_TEST_PICK_FILE.split('|') : [];
  handle('blind:files:pick', async (options) => {
    const kind = options && options.kind;
    const spec = PICK_KINDS[kind];
    if (!spec) return { canceled: false, error: 'tipo invalido: use "image" ou "document"' };
    let file = null;
    if (SMOKE) {
      // No smoke nunca abre o dialogo real. Stub (BLIND_TEST_PICK_FILE): lista separada por "|",
      // uma entrada por chamada; sem variavel, lista esgotada ou entrada vazia = usuario cancelou.
      file = smokePicks.shift() || null;
      if (!file) return { canceled: true };
    }
    if (!file) {
      const result = await dialog.showOpenDialog(win, {
        title: kind === 'image' ? 'Escolher imagem' : 'Escolher documento',
        properties: ['openFile'],
        filters: [{ name: spec.label, extensions: Object.keys(spec.types) }],
      });
      if (result.canceled || !result.filePaths.length) return { canceled: true };
      file = result.filePaths[0];
    }
    try {
      const ext = path.extname(file).slice(1).toLowerCase();
      const mime = spec.types[ext];
      if (!mime) return { canceled: false, error: 'tipo de arquivo não permitido' };
      const size = fs.statSync(file).size;
      if (size > MAX_PICK_BYTES) return { canceled: false, error: 'arquivo grande demais' };
      const data = await fs.promises.readFile(file);
      return { canceled: false, name: path.basename(file), mime, size, dataUrl: `data:${mime};base64,${data.toString('base64')}` };
    } catch (err) {
      return { canceled: false, error: `não foi possível ler o arquivo: ${err.message}` };
    }
  });

  // Captura a tela principal inteira (resolucao fisica), sem dialogo.
  handle('blind:screen:capture', async () => {
    try {
      const primary = screen.getPrimaryDisplay();
      const thumbnailSize = {
        width: Math.round(primary.size.width * primary.scaleFactor),
        height: Math.round(primary.size.height * primary.scaleFactor),
      };
      const sources = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize });
      const source = sources.find((s) => s.display_id === String(primary.id)) || sources[0];
      if (!source || source.thumbnail.isEmpty()) return { ok: false, error: 'não foi possível capturar a tela' };
      return { ok: true, dataUrl: `data:image/png;base64,${source.thumbnail.toPNG().toString('base64')}` };
    } catch (err) {
      mainLog.error(`captura de tela falhou: ${err.message}`);
      return { ok: false, error: String(err.message || err) };
    }
  });

  handle('blind:shell:open-logs', async () => {
    const error = await shell.openPath(logDir);
    return error ? { ok: false, error } : { ok: true };
  });

  handle('blind:window:minimize', () => win && win.minimize());
  handle('blind:window:toggle-maximize', () => {
    if (!win) return false;
    if (win.isMaximized()) win.unmaximize();
    else win.maximize();
    return win.isMaximized();
  });
  handle('blind:window:hide', () => hideWindow());
  handle('blind:window:show', () => showWindow());
  handle('blind:window:is-maximized', () => Boolean(win && win.isMaximized()));

  const publicSettings = () => {
    const s = settings.get();
    return { hotkey: s.hotkey, closeToTray: s.closeToTray, startHidden: s.startHidden };
  };
  handle('blind:settings:get', () => publicSettings());
  handle('blind:settings:set', (patch) => {
    const next = {};
    if (patch && typeof patch === 'object') {
      if (typeof patch.closeToTray === 'boolean') next.closeToTray = patch.closeToTray;
      if (typeof patch.startHidden === 'boolean') next.startHidden = patch.startHidden;
    }
    if (Object.keys(next).length) settings.set(next);
    return publicSettings();
  });
  handle('blind:settings:set-hotkey', (accelerator) => {
    if (typeof accelerator !== 'string' || accelerator.length > 64) return { ok: false, error: 'Atalho inválido.' };
    const previous = settings.get().hotkey;
    const result = registerHotkey(accelerator.trim());
    if (!result.ok) {
      registerHotkey(previous);
      return result;
    }
    settings.set({ hotkey: accelerator.trim() });
    return { ok: true };
  });

  handle('blind:settings:get-login-item', () => {
    if (SMOKE || (process.platform !== 'win32' && process.platform !== 'darwin')) {
      return { supported: false, openAtLogin: false };
    }
    if (!app.isPackaged) {
      return { supported: false, openAtLogin: false, reason: 'not-packaged' };
    }
    try {
      const s = app.getLoginItemSettings();
      return { supported: true, openAtLogin: Boolean(s && s.openAtLogin) };
    } catch (_) {
      return { supported: false, openAtLogin: false };
    }
  });

  handle('blind:settings:set-login-item', (enabled) => {
    if (SMOKE || (process.platform !== 'win32' && process.platform !== 'darwin')) {
      return { ok: false, supported: false, openAtLogin: false };
    }
    if (!app.isPackaged) {
      return { ok: false, supported: false, openAtLogin: false, reason: 'not-packaged' };
    }
    try {
      app.setLoginItemSettings({ openAtLogin: Boolean(enabled) });
      const s = app.getLoginItemSettings();
      return { ok: true, supported: true, openAtLogin: Boolean(s && s.openAtLogin) };
    } catch (err) {
      return { ok: false, supported: true, openAtLogin: false, error: String(err && err.message ? err.message : err) };
    }
  });

  // ------------------------------------------------------------ smoke test (scripts/smoke.js --electron)

  function writeSmoke(result) {
    const out = process.env.BLIND_SMOKE_OUT;
    if (out) fs.writeFileSync(out, JSON.stringify(result, null, 2), 'utf8');
    console.log(`SMOKE_RESULT ${JSON.stringify(result)}`);
  }

  let smokeDone = false;
  async function onPageLoaded() {
    if (!SMOKE || smokeDone || !win) return;
    const wc = win.webContents;
    const currentUrl = wc.getURL().replace(/\\/g, '/');
    if (shownPage === 'app' && !currentUrl.endsWith('/src/renderer/index.html')) return;
    if (shownPage === 'error' && !currentUrl.endsWith('/src/pages/error.html')) return;
    try {
      if (shownPage === 'app') {
        smokeDone = true;
        // Sem crases nem interpolacao aqui dentro: e uma string JS dentro de um template literal.
        const probe = `(async () => {
          const B = window.blind;
          const out = {
            page: 'app',
            href: location.href,
            title: document.title,
            hasBlind: typeof B === 'object',
            keys: Object.keys(B).sort(),
            platform: B.platform,
            version: B.version,
          };
          out.backendUrl = await B.backendUrl();
          out.status = await B.api.request({ path: '/api/status' });
          out.echo = await B.api.request({ method: 'POST', path: '/api/echo', body: { a: 1, b: 'x' } });
          out.text = await B.api.request({ path: '/api/text' });
          out.notFound = await B.api.request({ path: '/api/nada' });
          out.badPath = await B.api.request({ path: '/etc/passwd' });
          out.badTraversal = await B.api.request({ path: '/api/../secret' });
          out.badHost = await B.api.request({ path: '/api//evil.example/x' });
          out.badMethod = await B.api.request({ method: 'TRACE', path: '/api/status' });
          out.noArgs = await B.api.request();
          out.slowRequest = await B.api.request({ path: '/api/slow', timeoutMs: 1000 });
          out.servers = await B.mcp.servers();
          out.tools = await B.mcp.tools();
          out.call = await B.mcp.call('demo', 'echo', { a: 1 });
          out.restart = await B.mcp.restart('windows-desktop');
          out.settings = await B.settings.get();
          out.settingsSet = await B.settings.set({ closeToTray: false, startHidden: true, hotkey: 'X', evil: 1 });
          const slim = (r) => {
            if (!r || !r.dataUrl) return r;
            const c = Object.assign({}, r);
            c.dataUrlPrefix = r.dataUrl.slice(0, 120);
            c.dataUrlLength = r.dataUrl.length;
            delete c.dataUrl;
            return c;
          };
          out.pickImage = slim(await B.files.pick({ kind: 'image' }));
          out.pickDoc = slim(await B.files.pick({ kind: 'document' }));
          out.pickBig = slim(await B.files.pick({ kind: 'image' }));
          out.pickWrongType = slim(await B.files.pick({ kind: 'document' }));
          out.pickCanceled = slim(await B.files.pick({ kind: 'image' }));
          out.pickBadKind = slim(await B.files.pick({ kind: 'exe' }));
          out.capture = slim(await B.screen.capture());
          out.micState = (await navigator.permissions.query({ name: 'microphone' })).state;
          out.camState = (await navigator.permissions.query({ name: 'camera' })).state;
          window.__got = [];
          window.__off = B.shortcuts.onTrigger((id) => window.__got.push(id));
          return out;
        })()`;
        const result = await wc.executeJavaScript(probe);

        // Atalhos: dispara cada item do menu por codigo e confere o que chegou ao renderer.
        const menu = Menu.getApplicationMenu();
        result.accelerators = {};
        for (const { id } of SHORTCUTS) {
          const item = menu.getMenuItemById(`shortcut-${id}`);
          result.accelerators[id] = item ? item.accelerator : null;
          if (item) item.click();
        }
        await new Promise((r) => setTimeout(r, 400));
        result.shortcutsReceived = await wc.executeJavaScript('window.__got.slice()');
        await wc.executeJavaScript('window.__off()');
        menu.getMenuItemById('shortcut-home').click();
        await new Promise((r) => setTimeout(r, 300));
        result.shortcutsAfterUnsubscribe = await wc.executeJavaScript('window.__got.length');

        // Permissao de midia: uma pagina http (origem do backend) tem de ser negada.
        const probeWin = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true } });
        try {
          await probeWin.loadURL(`http://127.0.0.1:${supervisor.port}/api/status`);
          result.httpPermission = await probeWin.webContents.executeJavaScript(
            `(async () => {
              const q = await navigator.permissions.query({ name: 'microphone' });
              let gum = 'allowed';
              try { await navigator.mediaDevices.getUserMedia({ audio: true }); } catch (e) { gum = e.name; }
              return { origin: location.origin, state: q.state, gum };
            })()`,
          );
        } finally {
          probeWin.destroy();
        }
        writeSmoke(result);
        quitApp();
      } else if (shownPage === 'error') {
        smokeDone = true;
        const result = await wc.executeJavaScript(
          `(async () => ({ page: 'error', title: document.title, info: await window.blind.app.info(), reason: document.getElementById('reason').textContent, hasRetry: Boolean(document.getElementById('retry')) }))()`,
        );
        writeSmoke(result);
        quitApp();
      }
    } catch (err) {
      smokeDone = true;
      writeSmoke({ page: shownPage, error: String(err && err.stack ? err.stack : err) });
      quitApp();
    }
  }

  // ------------------------------------------------------------ ciclo de vida

  let supervisorStopped = false;
  let stoppingNow = false;
  app.on('before-quit', (event) => {
    quitting = true;
    if (supervisorStopped) return;
    event.preventDefault();
    if (stoppingNow) return;
    stoppingNow = true;
    globalShortcut.unregisterAll();
    const guardTimer = setTimeout(() => app.exit(0), 10000);
    supervisor
      .stop()
      .catch(() => {})
      .finally(() => {
        clearTimeout(guardTimer);
        supervisorStopped = true;
        mainLog.info('encerrando.');
        mainLog.close();
        backendLog.close();
        app.quit();
      });
  });

  app.on('window-all-closed', () => app.quit());
  app.on('will-quit', () => globalShortcut.unregisterAll());
  app.on('second-instance', () => showWindow());
  app.on('web-contents-created', (_event, contents) => {
    contents.on('will-attach-webview', (e) => e.preventDefault());
  });

  app.whenReady().then(() => {
    try {
      app.setAccessibilitySupportEnabled(true);
    } catch (_) {
      // suporte de acessibilidade nativo ativo
    }
    // Permissoes: so microfone (media, apenas audio) e so para as paginas file:// do proprio app.
    // Todo o resto e negado (camera, notificacoes, clipboard, tela cheia, origens http...).
    // A captura de tela e o seletor de arquivos passam pelo IPC (screen.capture / files.pick).
    const ses = session.defaultSession;
    const requesterUrl = (wc, details, origin) => (details && details.requestingUrl) || origin || (wc && wc.getURL()) || '';
    ses.setPermissionRequestHandler((wc, permission, callback, details) => {
      const types = details && Array.isArray(details.mediaTypes) ? details.mediaTypes : [];
      const audioOnly = types.length > 0 && types.every((t) => t === 'audio');
      callback(permission === 'media' && audioOnly && isAllowedUrl(requesterUrl(wc, details)));
    });
    ses.setPermissionCheckHandler((wc, permission, origin, details) => {
      const audio = details && details.mediaType === 'audio';
      return permission === 'media' && audio && isAllowedUrl(requesterUrl(wc, details, origin));
    });
    ses.setDisplayMediaRequestHandler((_request, callback) => callback({}));

    createMenu();
    createWindow();
    if (!SMOKE) {
      createTray();
      const hotkey = settings.get().hotkey;
      const result = registerHotkey(hotkey);
      if (!result.ok) mainLog.warn(`atalho global "${hotkey}" não registrado: ${result.error}`);
    }
    startBackend();

    if (SMOKE) {
      setTimeout(() => {
        if (!smokeDone) {
          writeSmoke({ timeout: true, shownPage, state: lastState });
          app.exit(2);
        }
      }, Number(process.env.BLIND_SMOKE_TIMEOUT_MS) || 60000);
    }
  });
}
