// Gravacao de voz no app: microfone -> PCM -> WAV 16 kHz mono (formato que o Whisper do backend le direto).
// Para sozinha apos uma pausa na fala; Esc ou o botao Parar encerram na hora.

const TARGET_RATE = 16000;
const MAX_SECONDS = 60;
const NO_SPEECH_TIMEOUT_MS = 8000;
const SILENCE_AFTER_SPEECH_MS = 1500;

export class RecordingError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

function resample(samples, fromRate, toRate) {
  if (fromRate === toRate) return samples;
  const ratio = fromRate / toRate;
  const length = Math.floor(samples.length / ratio);
  const out = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    const pos = i * ratio;
    const i0 = Math.floor(pos);
    const i1 = Math.min(i0 + 1, samples.length - 1);
    const frac = pos - i0;
    out[i] = samples[i0] * (1 - frac) + samples[i1] * frac;
  }
  return out;
}

export function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const write = (offset, text) => [...text].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  write(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  write(8, 'WAVE');
  write(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: 'audio/wav' });
}

export function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

// Controle de uma gravacao: handle.stop() encerra e entrega o WAV; handle.cancel() descarta.
export async function startRecording({ onLevel, onAutoStop, silenceAfterSpeechMs } = {}) {
  const silenceLimit = Math.max(600, Math.min(10000, Number(silenceAfterSpeechMs) || SILENCE_AFTER_SPEECH_MS));
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    throw new RecordingError('unsupported', 'Este computador não oferece acesso ao microfone.');
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch (err) {
    const denied = err && (err.name === 'NotAllowedError' || err.name === 'SecurityError');
    throw new RecordingError(
      denied ? 'denied' : 'no-device',
      denied
        ? 'O acesso ao microfone foi negado. Libere o microfone nas configurações de privacidade do Windows.'
        : 'Nenhum microfone foi encontrado.'
    );
  }

  const ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: TARGET_RATE });
  if (ctx.state === 'suspended') await ctx.resume();
  const source = ctx.createMediaStreamSource(stream);
  const chunks = [];
  let total = 0;
  let finished = false;
  let speechStarted = false;
  let noiseFloor = null;
  let lastSpeechAt = 0;
  const startedAt = performance.now();
  let calibrationUntil = startedAt + 400;

  const handleChunk = (data) => {
    if (finished) return;
    chunks.push(data);
    total += data.length;
    let sum = 0;
    for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
    const rms = Math.sqrt(sum / data.length);
    const now = performance.now();
    if (onLevel) onLevel(rms);
    if (now < calibrationUntil) {
      noiseFloor = Math.max(noiseFloor ?? 0, rms);
      return;
    }
    const threshold = Math.max(0.012, (noiseFloor ?? 0) * 3);
    if (rms > threshold) {
      speechStarted = true;
      lastSpeechAt = now;
    }
    const silentFor = now - lastSpeechAt;
    if (speechStarted && silentFor > silenceLimit) autoStop('silence');
    else if (!speechStarted && now - startedAt > NO_SPEECH_TIMEOUT_MS) autoStop('no-speech');
    else if ((now - startedAt) / 1000 > MAX_SECONDS) autoStop('max');
  };

  let node = null;
  let processor = null;
  try {
    await ctx.audioWorklet.addModule(new URL('./pcm-worklet.js', import.meta.url).href);
    node = new AudioWorkletNode(ctx, 'pcm-capture');
    node.port.onmessage = (e) => handleChunk(e.data);
    source.connect(node);
  } catch (_) {
    // Sem AudioWorklet: usa o ScriptProcessor, mais antigo mas amplamente suportado.
    processor = ctx.createScriptProcessor(4096, 1, 1);
    processor.onaudioprocess = (e) => handleChunk(new Float32Array(e.inputBuffer.getChannelData(0)));
    source.connect(processor);
    processor.connect(ctx.destination);
  }

  let resolveDone;
  const done = new Promise((resolve) => {
    resolveDone = resolve;
  });

  const teardown = async () => {
    finished = true;
    try {
      source.disconnect();
      if (node) node.disconnect();
      if (processor) processor.disconnect();
    } catch (_) {
      // ja desconectado
    }
    stream.getTracks().forEach((t) => t.stop());
    try {
      await ctx.close();
    } catch (_) {
      // contexto ja fechado
    }
  };

  const finish = async (reason, discard) => {
    if (finished) return null;
    await teardown();
    const merged = new Float32Array(total);
    let offset = 0;
    for (const c of chunks) {
      merged.set(c, offset);
      offset += c.length;
    }
    const result = discard
      ? { reason, speechDetected: speechStarted, blob: null, seconds: 0 }
      : {
          reason,
          speechDetected: speechStarted,
          seconds: merged.length / ctx.sampleRate,
          blob: encodeWav(resample(merged, ctx.sampleRate, TARGET_RATE), TARGET_RATE),
        };
    resolveDone(result);
    return result;
  };

  function autoStop(reason) {
    finish(reason, false).then((r) => r && onAutoStop && onAutoStop(r));
  }

  return {
    done,
    stop: () => finish('stopped', false),
    cancel: () => finish('cancelled', true),
  };
}
