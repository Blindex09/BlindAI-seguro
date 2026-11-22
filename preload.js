'use strict';

// Ponte segura (contextIsolation + sandbox) entre a interface e o processo principal.
// A UI usa window.blind; as chamadas HTTP ao backend sao feitas no main (IPC), entao
// a UI nao precisa conhecer a porta.

const { contextBridge, ipcRenderer } = require('electron');

const versionArg = process.argv.find((a) => a.startsWith('--blind-version='));
const version = versionArg ? versionArg.slice('--blind-version='.length) : 'desconhecida';

const invoke = (channel, ...args) => ipcRenderer.invoke(channel, ...args);

contextBridge.exposeInMainWorld('blind', {
  platform: process.platform,
  version,

  // Promise<string>, ex.: "http://127.0.0.1:8765" (vazio se o backend nao estiver pronto)
  backendUrl: () => invoke('blind:app:backend-url'),

  app: {
    // { version, platform, state, attempt, error, output, logDir }
    info: () => invoke('blind:app:info'),
    retry: () => invoke('blind:app:retry'),
    // cb({ state: 'starting'|'ready'|'restarting'|'failed'|'stopped', attempt, error, output })
    // Retorna uma funcao para cancelar a inscricao.
    onBackendState(cb) {
      const handler = (_event, state) => cb(state);
      ipcRenderer.on('blind:backend-state', handler);
      return () => {
        ipcRenderer.removeListener('blind:backend-state', handler);
      };
    },
  },

  mcp: {
    // { available, servers: [{ name, status, tool_count, error }], error? }
    servers: () => invoke('blind:mcp:servers'),
    // { available, tools: [{ server, name, description }], error? }
    tools: () => invoke('blind:mcp:tools'),
    // { ok, error? }
    restart: (name) => invoke('blind:mcp:restart', name),
    // { ok, content, is_error, error? }
    call: (server, tool, args) => invoke('blind:mcp:call', server, tool, args),
  },

  shell: {
    openLogs: () => invoke('blind:shell:open-logs'),
  },

  window: {
    minimize: () => invoke('blind:window:minimize'),
    toggleMaximize: () => invoke('blind:window:toggle-maximize'),
    hide: () => invoke('blind:window:hide'),
    show: () => invoke('blind:window:show'),
    isMaximized: () => invoke('blind:window:is-maximized'),
  },

  settings: {
    // { hotkey, closeToTray, startHidden }
    get: () => invoke('blind:settings:get'),
    // patch { closeToTray?: boolean, startHidden?: boolean } -> configuracoes atualizadas
    set: (patch) => invoke('blind:settings:set', patch),
    // Aceita aceleradores do Electron, ex.: "Control+Alt+L". "" desativa o atalho.
    setHotkey: (accelerator) => invoke('blind:settings:set-hotkey', accelerator),
    getLoginItem: () => invoke('blind:settings:get-login-item'),
    setLoginItem: (enabled) => invoke('blind:settings:set-login-item', enabled),
  },

  api: {
    // Proxy para o backend (a UI nao faz fetch). Somente paths /api/ e /v1/.
    // { method?, path, body?, timeoutMs? (padrao 120000) } -> { ok, status, data, error? }
    // data = JSON parseado (ou texto se nao for JSON). Sem streaming: a resposta chega inteira.
    request: (options) => invoke('blind:api:request', options),
  },

  files: {
    // pick({ kind: 'image' | 'document' }) ->
    //   { canceled: true } | { canceled: false, name, mime, size, dataUrl } | { canceled: false, error }
    pick: (options) => invoke('blind:files:pick', options),
  },

  screen: {
    // capture() -> { ok: true, dataUrl } (PNG da tela principal, sem dialogo) | { ok: false, error }
    capture: () => invoke('blind:screen:capture'),
  },

  shortcuts: {
    // cb(id) com id em: listen, chat, screen, image, docs, writer, channels, tools, models, home, settings.
    // Disparado pelos aceleradores Alt+Shift+<letra> do menu (so com a janela em foco).
    // Retorna uma funcao para cancelar a inscricao.
    onTrigger(cb) {
      const handler = (_event, id) => cb(id);
      ipcRenderer.on('blind:shortcut', handler);
      return () => {
        ipcRenderer.removeListener('blind:shortcut', handler);
      };
    },
  },
});
