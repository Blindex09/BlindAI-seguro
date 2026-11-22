// Tela: Leitura de faturas e documentos (PDF e TXT).

import { h, actionButton } from '../lib/dom.js';
import { announce, sanitizeScreenReaderText } from '../lib/a11y.js';
import { playBeep } from '../lib/sound.js';
import { speak } from '../lib/tts.js';
import * as api from '../lib/api.js';
import * as store from '../lib/store.js';

function dataUrlToText(dataUrl) {
  const base64 = String(dataUrl).split(',')[1] || '';
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  return new TextDecoder('utf-8').decode(bytes);
}

export function createDocsScreen(ctx) {
  const output = h('div', { id: 'docs-output', class: 'output', role: 'region', 'aria-label': 'Resumo do documento', tabindex: '0' }, 'O resumo aparecerá aqui.');
  const busy = h('p', { class: 'hint', role: 'status', 'aria-live': 'polite' });
  const openChat = actionButton({ id: 'btn-docs-chat', label: 'Conversar sobre este documento', cls: 'plain', onClick: () => ctx.nav('chat') });
  openChat.hidden = true;
  const pickBtn = actionButton({ id: 'btn-pick-doc', label: 'Escolher fatura ou documento', hint: 'Alt+Shift+D. PDF ou TXT', onClick: () => choose() });

  const root = h(
    'section',
    { class: 'screen', id: 'screen-docs', hidden: true, 'aria-labelledby': 'docs-title' },
    h('h1', { id: 'docs-title', tabindex: '-1', text: 'Ler fatura ou documento' }),
    h('p', { class: 'lead', text: 'O Blind AI lê o arquivo, destaca valores, datas e instruções de pagamento e deixa você tirar dúvidas na conversa.' }),
    h('div', { class: 'card' }, h('div', { class: 'button-grid' }, pickBtn), busy),
    h('div', { class: 'card' }, h('h2', { text: 'Resumo' }), output, h('div', { class: 'row' }, openChat))
  );

  function setBusy(on, text = '') {
    pickBtn.disabled = on;
    busy.textContent = on ? text : '';
    output.setAttribute('aria-busy', on ? 'true' : 'false');
  }

  async function choose() {
    playBeep(880, 0.12);
    announce('Abrindo o explorador de arquivos para escolher o documento.', true);
    const file = await api.pickFile('document');
    if (file.canceled) {
      announce('Nenhum documento escolhido.', true);
      return;
    }
    if (file.error) {
      announce(`Não foi possível usar o arquivo: ${file.error}`, true);
      return;
    }
    const lower = file.name.toLowerCase();
    if (lower.endsWith('.docx')) {
      const msg = 'Arquivos DOCX ainda não são suportados. Salve o documento como PDF ou TXT e tente de novo.';
      output.textContent = msg;
      announce(msg, true);
      return;
    }
    if (lower.endsWith('.txt')) {
      await readText(file);
      return;
    }
    await readPdf(file);
  }

  async function readPdf(file) {
    const s = store.get();
    setBusy(true, `Lendo ${file.name}...`);
    const sessionId = await ctx.chat.newSession(`Fatura/Doc: ${file.name}`, 'docs');
    ctx.chat.append('Smart Audio Desk', `Arquivo ${file.name}: extraindo o texto e gerando o resumo acessível...`, false);
    announce(`Arquivo ${file.name} escolhido. Extraindo o texto e preparando o resumo.`, true);
    const res = await api.post(
      '/api/docs/read',
      { file_base64: file.dataUrl, filename: file.name, provider: s.provider, model: s.model || null, api_key: s.apiKey || null, session_id: sessionId },
      180000
    );
    setBusy(false);
    if (!res.ok) {
      const msg = `Erro ao ler o documento: ${api.errorText(res)}`;
      output.textContent = msg;
      ctx.chat.append('Smart Audio Desk', msg, false);
      announce(msg, true);
      return;
    }
    const summary = sanitizeScreenReaderText(res.data.summary || `Documento lido (${res.data.total_words || 0} palavras).`);
    output.textContent = summary;
    ctx.chat.append('Smart Audio Desk', summary, false);
    openChat.hidden = false;
    playBeep(660, 0.15);
    speak(summary, { enabled: store.get().tts });
    announce(summary, true);
    output.focus();
  }

  async function readText(file) {
    const text = dataUrlToText(file.dataUrl).trim();
    if (!text) {
      announce('O arquivo de texto está vazio.', true);
      return;
    }
    await ctx.chat.newSession(`Fatura/Doc: ${file.name}`, 'docs');
    output.textContent = `Arquivo ${file.name} enviado para a conversa para ser resumido.`;
    openChat.hidden = false;
    ctx.nav('chat');
    await ctx.chat.send(`Resuma de forma clara e objetiva, para uma pessoa com deficiência visual, o documento ${file.name}:\n\n${text.slice(0, 12000)}`);
  }

  return { id: 'docs', label: 'Ler fatura ou PDF', title: 'Ler fatura ou documento', key: 'Alt+Shift+D', root, actions: { choose } };
}
