// Estado compartilhado entre telas. Preferencias vao para localStorage; a chave de API fica so em memoria.

const KEY = 'blind.prefs.v1';
const DEFAULTS = {
  provider: 'auto',
  model: 'auto',
  tts: false,
  ttsVoice: '',
  ttsRate: 1.0,
  beeps: true,
  jarvisMode: false,
  language: 'pt',
  silenceAfterSpeechMs: 1500,
  sendShortcut: 'enter',
  showAgentSteps: true,
  responseStyle: 'curto',
  customInstructions: '',
  fontSize: 'normal',
  highContrast: false,
  reduceMotion: false,
  verboseAnnouncements: true,
  accountEmail: '',
  accountName: '',
  accountPlan: '',
};

const PERSIST_KEYS = Object.keys(DEFAULTS);

function loadPrefs() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') };
  } catch (_) {
    return { ...DEFAULTS };
  }
}

const state = { ...loadPrefs(), apiKey: '', activeSessionId: null, activeSessionTitle: '' };
const listeners = new Set();

function persist() {
  try {
    const out = {};
    for (const k of PERSIST_KEYS) out[k] = state[k];
    localStorage.setItem(KEY, JSON.stringify(out));
  } catch (_) {
    // armazenamento indisponivel: segue so em memoria
  }
}

export function get() {
  return state;
}

export function set(patch) {
  Object.assign(state, patch);
  persist();
  listeners.forEach((fn) => fn(state));
}

export function resetPreferences() {
  const keep = {
    accountEmail: state.accountEmail,
    accountName: state.accountName,
    accountPlan: state.accountPlan,
  };
  Object.assign(state, DEFAULTS, keep);
  persist();
  listeners.forEach((fn) => fn(state));
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
