// Cliente do backend. Toda chamada passa pelo processo principal do Electron (IPC):
// o renderer nao conhece a porta nem faz fetch de rede.

const OUTSIDE_APP = 'Esta interface precisa rodar dentro do aplicativo Blind AI.';

export function hasShell() {
  return Boolean(window.blind && window.blind.api);
}

export async function request(method, path, body, timeoutMs) {
  if (!hasShell()) return { ok: false, status: 0, data: null, error: OUTSIDE_APP };
  try {
    return await window.blind.api.request({ method, path, body, timeoutMs });
  } catch (err) {
    return { ok: false, status: 0, data: null, error: err && err.message ? err.message : String(err) };
  }
}

export const get = (path, timeoutMs) => request('GET', path, undefined, timeoutMs);
export const post = (path, body, timeoutMs) => request('POST', path, body ?? {}, timeoutMs);
export const del = (path) => request('DELETE', path);

// Texto de erro para mostrar e anunciar. O backend FastAPI devolve {detail: "..."}.
export function errorText(res) {
  if (!res) return 'Falha desconhecida.';
  const detail = res.data && typeof res.data === 'object' ? res.data.detail || res.data.reply : null;
  if (detail) return typeof detail === 'string' ? detail : JSON.stringify(detail);
  if (res.status === 0) return res.error || 'O servidor do Blind AI não respondeu.';
  return res.error || `Erro ${res.status}`;
}

export async function pickFile(kind) {
  if (!window.blind || !window.blind.files) return { canceled: false, error: OUTSIDE_APP };
  return window.blind.files.pick({ kind });
}

export async function captureScreen() {
  if (!window.blind || !window.blind.screen) return { ok: false, error: OUTSIDE_APP };
  return window.blind.screen.capture();
}
