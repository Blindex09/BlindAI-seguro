// Ditado por voz: grava no app e transcreve com o Whisper local do backend (servidor MCP blind-stt).

import { announce } from './a11y.js';
import { playBeep } from './sound.js';
import { h } from './dom.js';
import * as api from './api.js';
import * as store from './store.js';
import { blobToBase64, startRecording, RecordingError } from './recorder.js';

let active = null; // gravacao em andamento
let bar = null;

function showBar(onStop, onCancel) {
  hideBar();
  bar = h(
    'div',
    { class: 'recording-bar', role: 'group', 'aria-label': 'Gravação de voz em andamento' },
    h('span', { text: 'Gravando. Fale agora. ' }),
    h('button', { type: 'button', class: 'sky', onClick: onStop, text: 'Parar e transcrever (Esc)' }),
    h('button', { type: 'button', class: 'plain', onClick: onCancel, text: 'Cancelar' })
  );
  document.body.append(bar);
}

function hideBar() {
  if (bar) bar.remove();
  bar = null;
}

export function isRecording() {
  return Boolean(active);
}

document.addEventListener('keydown', (event) => {
  if (!active) return;
  if (event.key === 'Escape') {
    event.preventDefault();
    active.stop();
  }
});

async function transcribe(blob) {
  const status = await api.get('/api/stt/status');
  if (status.ok && status.data && !status.data.loaded && !status.data.error) {
    announce('Preparando o reconhecimento de voz pela primeira vez. Isso pode levar alguns minutos.', true);
  }
  const audio = await blobToBase64(blob);
  const lang = store.get().language || 'pt';
  const res = await api.post(
    '/api/stt/transcribe',
    { audio_base64: audio, language: lang === 'auto' ? null : lang },
    900000
  );
  if (!res.ok) return { ok: false, message: `Não consegui transcrever: ${api.errorText(res)}` };
  const text = String((res.data && res.data.text) || '').trim();
  if (!text) return { ok: false, empty: true, message: 'Não entendi nenhuma fala. Tente de novo, mais perto do microfone.' };
  return { ok: true, text, seconds: res.data.audio_seconds };
}

// Grava uma frase e devolve {ok:true, text} ou {ok:false, message}. Chamar de novo durante a gravacao a encerra.
export async function dictate() {
  if (active) {
    active.stop();
    return { ok: false, cancelled: true, message: '' };
  }
  let handle;
  try {
    handle = await startRecording({
      silenceAfterSpeechMs: store.get().silenceAfterSpeechMs,
      onAutoStop: () => playBeep(520, 0.12),
    });
  } catch (err) {
    const message = err instanceof RecordingError ? err.message : `Não foi possível gravar: ${err.message}`;
    announce(message, true);
    return { ok: false, message };
  }

  active = handle;
  showBar(
    () => handle.stop(),
    () => handle.cancel()
  );
  playBeep(880, 0.15);
  announce('Gravando. Fale agora. Pressione Escape para terminar.', true);

  const result = await handle.done;
  active = null;
  hideBar();

  if (result.reason === 'cancelled') {
    announce('Gravação cancelada.', true);
    return { ok: false, cancelled: true, message: 'Gravação cancelada.' };
  }
  if (!result.speechDetected) {
    const message = 'Não ouvi nenhuma fala. Verifique o microfone e tente de novo.';
    announce(message, true);
    return { ok: false, empty: true, message };
  }
  playBeep(660, 0.12);
  announce('Transcrevendo sua fala...', false);
  const outcome = await transcribe(result.blob);
  if (!outcome.ok) announce(outcome.message, true);
  return outcome;
}

export function cancelDictation() {
  if (active) active.cancel();
}
