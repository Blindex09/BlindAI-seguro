// Fala pelo sintetizador do sistema. Por padrao desligada para nao sobrepor NVDA/JAWS.

import { sanitizeScreenReaderText } from './a11y.js';
import * as store from './store.js';

export function listVoices() {
  if (!('speechSynthesis' in window)) return [];
  const voices = window.speechSynthesis.getVoices() || [];
  return [...voices]
    .sort((a, b) => {
      const aPt = /^pt/i.test(a.lang || '') ? 0 : 1;
      const bPt = /^pt/i.test(b.lang || '') ? 0 : 1;
      if (aPt !== bPt) return aPt - bPt;
      return String(a.name || '').localeCompare(String(b.name || ''));
    })
    .map((v) => ({
      id: v.voiceURI || v.name,
      name: `${v.name} (${v.lang || 'idioma padrão'})`,
      lang: v.lang || '',
    }));
}

export function speak(text, { rate = null, voiceName = null, force = false, enabled = false, onEnd = null } = {}) {
  if (!force && !enabled) {
    if (typeof onEnd === 'function') setTimeout(onEnd, 50);
    return false;
  }
  if (!('speechSynthesis' in window)) {
    if (typeof onEnd === 'function') setTimeout(onEnd, 50);
    return false;
  }
  const clean = sanitizeScreenReaderText(text);
  if (!clean) {
    if (typeof onEnd === 'function') setTimeout(onEnd, 50);
    return false;
  }
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(clean);
  utter.lang = 'pt-BR';
  const rawRate = Number(rate ?? store.get().ttsRate) || 1.0;
  utter.rate = Math.max(0.5, Math.min(2.5, rawRate));
  const wantedVoice = voiceName ?? store.get().ttsVoice;
  if (wantedVoice) {
    const found = (window.speechSynthesis.getVoices() || []).find(
      (v) => v.voiceURI === wantedVoice || v.name === wantedVoice
    );
    if (found) utter.voice = found;
  }
  if (typeof onEnd === 'function') {
    utter.onend = () => onEnd();
    utter.onerror = () => onEnd();
  }
  window.speechSynthesis.speak(utter);
  return true;
}

export function stopSpeaking() {
  if ('speechSynthesis' in window) window.speechSynthesis.cancel();
}
