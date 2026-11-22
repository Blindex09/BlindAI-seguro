// Inicializacao do renderer: monta as telas, a navegacao e os atalhos.

import { announce } from './lib/a11y.js';
import { playBeep } from './lib/sound.js';
import { createQuickbar } from './lib/quickbar.js';
import * as store from './lib/store.js';
import * as voice from './lib/voice.js';
import { createRouter } from './router.js';
import { createHomeScreen } from './screens/home.js';
import { createChatScreen } from './screens/chat.js';
import { createModelsScreen } from './screens/models.js';
import { createVisionScreen } from './screens/vision.js';
import { createDocsScreen } from './screens/docs.js';
import { createWriterScreen } from './screens/writer.js';
import { createChannelsScreen } from './screens/channels.js';
import { createToolsScreen } from './screens/tools.js';
import { createActivityScreen } from './screens/activity.js';
import { createAccountScreen } from './screens/account.js';
import { createSettingsScreen } from './screens/settings.js';

const statusEl = document.getElementById('system-status');
const statusText = document.getElementById('system-status-text');

const ctx = {
  nav: (id) => router.show(id),
  setStatus(state, text) {
    statusEl.dataset.state = state;
    if (statusText.textContent !== text) statusText.textContent = text;
  },
  chat: null,
  run: (action) => runAction(action),
};

const home = createHomeScreen(ctx);
const chat = createChatScreen(ctx);
ctx.chat = chat.api;
const quickbar = createQuickbar({ rootEl: document.getElementById('quickbar'), ctx });
const vision = createVisionScreen(ctx);
const docs = createDocsScreen(ctx);
const writer = createWriterScreen(ctx);
const channels = createChannelsScreen(ctx);
const tools = createToolsScreen(ctx);
const activity = createActivityScreen(ctx);
const account = createAccountScreen(ctx);
const models = createModelsScreen(ctx);
const settings = createSettingsScreen(ctx);

// Ordem do menu = ordem dos atalhos Ctrl+1..9
const screens = [home, chat, models, vision, docs, writer, channels, tools, settings, activity, account];
const router = createRouter({
  navEl: document.getElementById('nav'),
  mainEl: document.getElementById('main'),
  screens,
  onRouteChange: (id) => quickbar.setVisible(id !== 'chat'),
});

function runAction(id) {
  playBeep(880, 0.12);
  switch (id) {
    case 'home':
      router.show('home');
      break;
    case 'chat':
      router.show('chat');
      chat.focusInput();
      announce('Campo de conversa selecionado. Digite sua mensagem.', true);
      break;
    case 'listen':
      router.show('chat', { announceTitle: false });
      chat.api.dictate();
      break;
    case 'jarvis':
      router.show('chat', { announceTitle: false });
      chat.api.toggleJarvis(true);
      break;
    case 'screen':
      router.show('vision', { announceTitle: false });
      vision.actions.captureScreen();
      break;
    case 'image':
      router.show('vision', { announceTitle: false });
      vision.actions.chooseImage();
      break;
    case 'docs':
      router.show('docs', { announceTitle: false });
      docs.actions.choose();
      break;
    case 'writer':
      router.show('writer');
      writer.focusFirst();
      break;
    case 'channels':
    case 'activity':
    case 'account':
    case 'tools':
    case 'models':
    case 'settings':
      router.show(id);
      break;
    default:
      break;
  }
}

// Navegacao nativa de software desktop:
// - Ctrl+1..9 abre cada modulo diretamente
// - Escape (quando nao esta gravando voz nem em dialogo modal) volta ao Painel de Comando
// - Setas direcionais (Cima/Baixo/Esquerda/Direita) navegam entre botoes de comando e abas
document.addEventListener('keydown', (event) => {
  if (event.ctrlKey && !event.altKey && !event.shiftKey && !event.metaKey) {
    if (event.key.toLowerCase() === 'k') {
      event.preventDefault();
      if (router.current() === 'chat') {
        chat.focusInput();
      } else {
        quickbar.focus();
        announce('Barra rápida do Blind selecionada. Digite sua mensagem ou aperte Tab para falar.', false);
      }
      return;
    }
    const index = Number(event.key) - 1;
    if (Number.isInteger(index) && index >= 0 && index < screens.length) {
      event.preventDefault();
      router.show(screens[index].id);
    }
    return;
  }

  if (event.key === 'Escape' && !event.ctrlKey && !event.altKey && !event.shiftKey && !event.metaKey) {
    const dialogEl = document.getElementById('dialog');
    if (dialogEl && dialogEl.open) return;
    if (voice.isRecording()) return;
    if (router.current() && router.current() !== 'home') {
      event.preventDefault();
      router.show('home');
      return;
    }
  }

  if (['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft'].includes(event.key) && !event.ctrlKey && !event.altKey && !event.metaKey) {
    const active = document.activeElement;
    if (!active || active.tagName !== 'BUTTON') return;
    const container = active.closest('.button-grid, .app-nav, .row, .tabs');
    if (!container) return;
    const items = [...container.querySelectorAll('button:not([hidden]):not(:disabled)')];
    const idx = items.indexOf(active);
    if (idx === -1 || items.length < 2) return;
    event.preventDefault();
    const delta = event.key === 'ArrowDown' || event.key === 'ArrowRight' ? 1 : -1;
    const nextIdx = (idx + delta + items.length) % items.length;
    items[nextIdx].focus();
  }
});

// Atalhos vindos do menu do Electron
if (window.blind && window.blind.shortcuts) {
  window.blind.shortcuts.onTrigger((id) => runAction(id));
}

// Estado do backend (iniciando, pronto, reiniciando, falhou)
const BACKEND_TEXT = {
  starting: ['busy', 'Iniciando o servidor do Blind AI...'],
  ready: ['ready', 'Pronto. Diga ou digite o que precisa.'],
  restarting: ['busy', 'Reiniciando o servidor do Blind AI...'],
  failed: ['error', 'O servidor do Blind AI parou.'],
  stopped: ['error', 'Servidor parado.'],
};
function applyBackendState(s) {
  const [state, text] = BACKEND_TEXT[s.state] || ['busy', String(s.state)];
  ctx.setStatus(state, text);
  if (s.state === 'failed') announce('O servidor do Blind AI parou e não conseguiu reiniciar.', true);
}
if (window.blind && window.blind.app) {
  window.blind.app.onBackendState(applyBackendState);
  window.blind.app.info().then(applyBackendState).catch(() => {});
} else {
  ctx.setStatus('error', 'Abra o Blind AI pelo aplicativo.');
}

window.addEventListener('beforeunload', () => voice.cancelDictation());

function applyVisualPrefs() {
  const s = store.get();
  document.documentElement.dataset.font = s.fontSize || 'normal';
  document.documentElement.dataset.contrast = s.highContrast ? 'high' : 'normal';
  document.documentElement.dataset.motion = s.reduceMotion ? 'reduced' : 'normal';
  const accBtn = document.getElementById('header-account-btn');
  if (accBtn) {
    accBtn.textContent = s.accountEmail ? s.accountEmail.split('@')[0] : 'Entrar na conta';
    accBtn.setAttribute(
      'aria-label',
      s.accountEmail ? `Conta conectada: ${s.accountEmail}. Atalho Alt+Shift+U` : 'Entrar ou criar conta. Atalho Alt+Shift+U'
    );
  }
}

const headerAccountBtn = document.getElementById('header-account-btn');
if (headerAccountBtn) headerAccountBtn.addEventListener('click', () => runAction('account'));

store.subscribe(applyVisualPrefs);
applyVisualPrefs();
router.show('home', { focus: false, announceTitle: false });
announce('Blind AI pronto.', false);

// Exposto para os testes de ponta a ponta
window.__blindRenderer = { router, ctx, runAction };
