// Feedback sonoro curto (WebAudio). O contexto so e criado apos um gesto do usuario.

import * as store from './store.js';

let ctx = null;

export function playBeep(freq = 440, duration = 0.15) {
  if (store.get().beeps === false) return;
  try {
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === 'suspended') ctx.resume();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = freq;
    osc.type = 'sine';
    gain.gain.setValueAtTime(0.1, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + duration);
  } catch (_) {
    // sem audio disponivel: o anuncio por texto continua valendo
  }
}
