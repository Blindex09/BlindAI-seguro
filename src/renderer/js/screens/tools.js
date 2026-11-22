// Tela: Ferramentas (MCP). Servidores conectados, estado, ferramentas de cada um e reinicio.

import { h, clear, actionButton } from '../lib/dom.js';
import { announce } from '../lib/a11y.js';
import * as api from '../lib/api.js';

const LABELS = { connected: 'Conectado', starting: 'Iniciando', error: 'Com erro', disabled: 'Desativado' };

export function createToolsScreen() {
  const status = h('p', { id: 'mcp-status', class: 'lead', role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true' }, 'Carregando servidores...');
  const list = h('ul', { id: 'mcp-list', class: 'server-list', 'aria-label': 'Servidores de ferramentas' });
  let timer = null;
  let visible = false;
  let lastStatusText = '';

  const root = h(
    'section',
    { class: 'screen', id: 'screen-tools', hidden: true, 'aria-labelledby': 'tools-title' },
    h('h1', { id: 'tools-title', tabindex: '-1', text: 'Ferramentas (MCP)' }),
    h('p', { class: 'lead', text: 'Cada servidor oferece ações ao Blind AI, como controlar janelas, ler documentos, falar ou enviar mensagens. Aqui você vê o estado e pode reiniciar um que falhou.' }),
    h('div', { class: 'row' }, actionButton({ id: 'btn-mcp-refresh', label: 'Atualizar a lista', cls: 'sky', onClick: () => load(true) })),
    status,
    list
  );

  function setStatus(text) {
    if (text !== lastStatusText) {
      lastStatusText = text;
      status.textContent = text;
    }
  }

  async function restart(name, button) {
    button.disabled = true;
    announce(`Reiniciando o servidor ${name}...`, true);
    const res = await api.post(`/api/mcp/servers/${encodeURIComponent(name)}/restart`, {}, 180000);
    const ok = res.ok && res.data && res.data.ok;
    announce(ok ? `Servidor ${name} reiniciado.` : `Não consegui reiniciar ${name}: ${(res.data && res.data.error) || api.errorText(res)}`, true);
    await load(false);
  }

  function render(servers, tools) {
    clear(list);
    servers.forEach((server) => {
      const own = tools.filter((t) => t.server === server.name);
      const li = h('li', { class: 'server-item' });
      const count = server.tool_count === 1 ? '1 ferramenta' : `${server.tool_count} ferramentas`;
      li.append(
        h(
          'p',
          {},
          h('strong', { class: 'name', text: server.name }),
          ' - ',
          h('span', { class: `state-${server.status}`, text: LABELS[server.status] || server.status }),
          `, ${count}`
        )
      );
      if (server.description) li.append(h('p', { class: 'hint', text: server.description }));
      if (server.error) li.append(h('p', { class: 'error-text', text: `Erro: ${server.error}` }));
      if (own.length) {
        li.append(
          h(
            'details',
            {},
            h('summary', { text: `Ver ferramentas de ${server.name}` }),
            h('ul', { class: 'tool-list' }, ...own.map((t) => h('li', { text: `${t.name}${t.description ? `: ${t.description}` : ''}${t.hidden_from_model ? ' (somente interface)' : ''}` })))
          )
        );
      }
      if (server.status !== 'disabled') {
        const btn = actionButton({ label: `Reiniciar ${server.name}`, cls: 'plain', ariaLabel: `Reiniciar o servidor ${server.name}`, onClick: () => restart(server.name, btn) });
        li.append(btn);
      }
      list.append(li);
    });
  }

  async function load(announceResult) {
    const [serversRes, toolsRes] = await Promise.all([api.get('/api/mcp/servers'), api.get('/api/mcp/tools')]);
    if (!serversRes.ok || !Array.isArray(serversRes.data)) {
      clear(list);
      setStatus(`Não consegui consultar as ferramentas: ${api.errorText(serversRes)}`);
      return;
    }
    const servers = serversRes.data;
    const tools = toolsRes.ok && Array.isArray(toolsRes.data) ? toolsRes.data : [];
    render(servers, tools);
    const connected = servers.filter((s) => s.status === 'connected').length;
    const starting = servers.filter((s) => s.status === 'starting').length;
    setStatus(`${connected} de ${servers.length} servidores conectados${starting ? `, ${starting} iniciando` : ''}.`);
    if (announceResult) announce(lastStatusText, true);
    clearTimeout(timer);
    if (visible && starting) timer = setTimeout(() => load(false), 2000);
  }

  return {
    id: 'tools',
    label: 'Servidores MCP (Avançado)',
    title: 'Ferramentas (MCP)',
    key: 'Alt+Shift+F',
    advanced: true,
    root,
    onShow: () => {
      visible = true;
      load(false);
    },
    onHide: () => {
      visible = false;
      clearTimeout(timer);
    },
  };
}
