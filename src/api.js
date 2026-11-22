'use strict';

// Cliente HTTP do backend, usado pelo processo principal (IPC). A UI nao precisa
// conhecer a porta. Todas as funcoes resolvem sempre (nunca rejeitam): falhas de
// rede ou rotas ausentes viram { available: false, ... } ou { ok: false, ... }.

function describeFailure(res) {
  if (res.networkError) return res.networkError;
  if (res.status === 404) return 'Rota nao encontrada no backend (o backend ainda nao tem MCP).';
  const detail = res.data && (res.data.detail || res.data.error);
  return `HTTP ${res.status}${detail ? `: ${typeof detail === 'string' ? detail : JSON.stringify(detail)}` : ''}`;
}

function createApi({ getBaseUrl, fetchImpl = globalThis.fetch, timeoutMs = 15000 }) {
  async function request(method, path, body, perCallTimeoutMs) {
    const base = getBaseUrl();
    if (!base) return { ok: false, status: 0, networkError: 'Backend indisponivel.' };
    try {
      const res = await fetchImpl(`${base}${path}`, {
        method,
        headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(perCallTimeoutMs || timeoutMs),
      });
      let data = null;
      const text = await res.text();
      if (text) {
        try {
          data = JSON.parse(text);
        } catch (_) {
          data = { raw: text };
        }
      }
      return { ok: res.ok, status: res.status, data };
    } catch (err) {
      return { ok: false, status: 0, networkError: err && err.message ? err.message : String(err) };
    }
  }

  const asList = (data, key) => {
    if (Array.isArray(data)) return data;
    if (data && Array.isArray(data[key])) return data[key];
    return [];
  };

  // Proxy generico para a UI (window.blind.api.request). So paths /api/ e /v1/ do proprio backend.
  // Devolve sempre { ok, status, data, error? }: data e o JSON parseado, ou o texto se nao for JSON.
  async function proxy(options) {
    const opts = options && typeof options === 'object' ? options : {};
    const method = String(opts.method || 'GET').toUpperCase();
    if (!['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      return { ok: false, status: 0, data: null, error: `Metodo nao permitido: ${method}` };
    }
    const reqPath = opts.path;
    if (typeof reqPath !== 'string' || !(reqPath.startsWith('/api/') || reqPath.startsWith('/v1/')) || /[\\\s]|\.\.|\/\//.test(reqPath) || reqPath.length > 2000) {
      return { ok: false, status: 0, data: null, error: 'Path invalido: so /api/ e /v1/ sao permitidos.' };
    }
    const base = getBaseUrl();
    if (!base) return { ok: false, status: 0, data: null, error: 'Backend indisponivel.' };
    let target;
    try {
      target = new URL(reqPath, base);
    } catch (_) {
      return { ok: false, status: 0, data: null, error: 'Path invalido.' };
    }
    if (target.origin !== new URL(base).origin) {
      return { ok: false, status: 0, data: null, error: 'Path invalido.' };
    }
    const timeout = Number.isFinite(opts.timeoutMs) ? Math.min(Math.max(opts.timeoutMs, 1000), 600000) : 120000;
    const hasBody = opts.body !== undefined && opts.body !== null && method !== 'GET';
    try {
      const res = await fetchImpl(target.href, {
        method,
        headers: hasBody ? { 'Content-Type': 'application/json' } : undefined,
        body: hasBody ? JSON.stringify(opts.body) : undefined,
        signal: AbortSignal.timeout(timeout),
      });
      const text = await res.text();
      let data = null;
      if (text) {
        try {
          data = JSON.parse(text);
        } catch (_) {
          data = text;
        }
      }
      const out = { ok: res.ok, status: res.status, data };
      if (!res.ok) out.error = `HTTP ${res.status}`;
      return out;
    } catch (err) {
      const timedOut = err && (err.name === 'TimeoutError' || err.name === 'AbortError');
      return { ok: false, status: 0, data: null, error: timedOut ? `Tempo esgotado apos ${Math.round(timeout / 1000)} s.` : String((err && err.message) || err) };
    }
  }

  return {
    request,
    proxy,

    async mcpServers() {
      const res = await request('GET', '/api/mcp/servers');
      if (!res.ok) return { available: false, servers: [], error: describeFailure(res) };
      const servers = asList(res.data, 'servers').map((s) => ({
        name: String(s.name),
        status: String(s.status || 'error'),
        tool_count: Number.isFinite(Number(s.tool_count)) ? Number(s.tool_count) : 0,
        error: s.error ? String(s.error) : null,
      }));
      return { available: true, servers };
    },

    async mcpTools() {
      const res = await request('GET', '/api/mcp/tools');
      if (!res.ok) return { available: false, tools: [], error: describeFailure(res) };
      const tools = asList(res.data, 'tools').map((t) => ({
        server: String(t.server),
        name: String(t.name),
        description: t.description ? String(t.description) : '',
      }));
      return { available: true, tools };
    },

    async mcpRestart(name) {
      const res = await request('POST', `/api/mcp/servers/${encodeURIComponent(name)}/restart`, {}, 60000);
      if (res.data && typeof res.data.ok === 'boolean') {
        return res.data.ok ? { ok: true } : { ok: false, error: String(res.data.error || 'Falha ao reiniciar.') };
      }
      return res.ok ? { ok: true } : { ok: false, error: describeFailure(res) };
    },

    async mcpCall(server, tool, args) {
      const res = await request('POST', '/api/mcp/call', { server, tool, arguments: args }, 120000);
      if (res.ok && res.data) {
        return {
          ok: res.data.ok !== false,
          content: res.data.content === undefined ? null : res.data.content,
          is_error: Boolean(res.data.is_error),
        };
      }
      return { ok: false, content: null, is_error: true, error: describeFailure(res) };
    },
  };
}

module.exports = { createApi };
