// Tela Inicial: navegacao rapida por caixa de combinacao (digite ou use as setas + Enter).

import { h } from '../lib/dom.js';
import { setDocumentTitle } from '../lib/a11y.js';
import { createCombobox } from '../lib/combobox.js';
import * as api from '../lib/api.js';
import * as store from '../lib/store.js';

export function createHomeScreen(ctx) {
  const heading = h('h1', { id: 'home-title', tabindex: '-1', text: 'Blind' });
  const summary = h('p', {
    id: 'home-summary',
    class: 'desktop-statusbar',
    role: 'status',
    'aria-live': 'polite',
    text: 'Verificando sistema...',
  });

  const commandItems = [
    { id: 'jarvis', label: 'Modo Jarvis (voz contínua)', hint: 'Alt+Shift+J', keywords: 'voz continua ouvir microfone jarvis' },
    { id: 'listen', label: 'Falar comando de voz', hint: 'Alt+Shift+L', keywords: 'ditar falar microfone comando' },
    { id: 'chat', label: 'Conversa por texto ou voz', hint: 'Alt+Shift+C', keywords: 'chat conversar escrever perguntar' },
    { id: 'screen', label: 'Descrever tela atual', hint: 'Alt+Shift+T', keywords: 'visao tela captura ler tela' },
    { id: 'image', label: 'Descrever arquivo de imagem', hint: 'Alt+Shift+I', keywords: 'foto imagem arquivo descrever' },
    { id: 'docs', label: 'Ler fatura ou PDF', hint: 'Alt+Shift+D', keywords: 'documento pdf fatura boleto ler' },
    { id: 'writer', label: 'Redigir ou ditar documento', hint: 'Alt+Shift+E', keywords: 'escrever redator texto nota' },
    { id: 'channels', label: 'WhatsApp e Telegram', hint: 'Alt+Shift+W', keywords: 'mensagens whatsapp telegram canal' },
    { id: 'account', label: 'Entrar na conta, criar conta ou assinatura', hint: 'Alt+Shift+U', keywords: 'conta login cadastrar entrar assinatura' },
    { id: 'settings', label: 'Configurações', hint: 'Alt+Shift+S', keywords: 'opcoes voz atalho janela aparencia contraste' },
    { id: 'activity', label: 'Atividades recentes', hint: 'Alt+Shift+A', keywords: 'historico atividades diario' },
    { id: 'models', label: 'Motor de IA (Avançado)', hint: 'Alt+Shift+M', keywords: 'modelo ia provedor api' },
    { id: 'tools', label: 'Servidores MCP (Avançado)', hint: 'Alt+Shift+F', keywords: 'ferramentas mcp servidores' },
  ];

  const combo = createCombobox({
    id: 'home-command-combo',
    label: 'O que você quer fazer?',
    hint: 'Use Seta para Baixo e Cima, ou digite o que procura, e aperte Enter para abrir.',
    placeholder: 'Ex.: conversa, pdf, whatsapp, conta, configurações...',
    items: commandItems,
    onSelect: (item) => ctx.run(item.id),
  });

  function syncTitle() {
    const s = store.get();
    const sessTitle = (s.activeSessionTitle || '').trim();
    const full = sessTitle ? `Blind - ${sessTitle}` : 'Blind';
    heading.textContent = full;
    return full;
  }
  store.subscribe(syncTitle);

  const root = h(
    'section',
    { class: 'screen', id: 'screen-home', 'aria-labelledby': 'home-title' },
    heading,
    h(
      'div',
      { class: 'card', role: 'region', 'aria-label': 'Comando principal' },
      combo.root
    ),
    summary
  );

  async function refresh() {
    setDocumentTitle(syncTitle());

    const res = await api.get('/api/status');
    if (!res.ok || !res.data) {
      summary.textContent = `Status: Sistema indisponível (${api.errorText(res)})`;
      return;
    }
    const mcp = Array.isArray(res.data.mcp) ? res.data.mcp : [];
    const tools = mcp.reduce((n, item) => n + (item.tool_count || 0), 0);
    summary.textContent = `Status: Sistema pronto — Piloto Automático ativo (${tools} ferramentas integradas)`;
  }

  return {
    id: 'home',
    label: 'Início',
    title: 'Blind',
    key: 'Alt+Shift+H',
    root,
    onShow: refresh,
    focusCombo: () => combo.focus(),
  };
}
