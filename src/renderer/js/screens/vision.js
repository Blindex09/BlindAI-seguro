// Tela: Audiodescricao de tela e imagem.

import { h, actionButton, field } from '../lib/dom.js';
import { announce, sanitizeScreenReaderText } from '../lib/a11y.js';
import { playBeep } from '../lib/sound.js';
import { speak } from '../lib/tts.js';
import * as api from '../lib/api.js';
import * as store from '../lib/store.js';

export function createVisionScreen(ctx) {
  const question = h('textarea', { id: 'vision-question', rows: 2, placeholder: 'Ex.: Qual é o valor total? (opcional)' });
  const output = h('div', { id: 'vision-output', class: 'output', role: 'region', 'aria-label': 'Resultado da audiodescrição', tabindex: '0' }, 'A descrição aparecerá aqui.');
  const busy = h('p', { class: 'hint', role: 'status', 'aria-live': 'polite' });
  const openChat = actionButton({ id: 'btn-vision-chat', label: 'Abrir a conversa desta descrição', cls: 'plain', onClick: () => ctx.nav('chat') });
  openChat.hidden = true;
  const buttons = [
    actionButton({ id: 'btn-capture', label: 'Descrever a tela agora', hint: 'Alt+Shift+T. Captura o monitor principal', cls: '', onClick: () => captureScreen() }),
    actionButton({ id: 'btn-choose-image', label: 'Descrever uma imagem do computador', hint: 'Alt+Shift+I. Escolha um arquivo', cls: 'green', onClick: () => chooseImage() }),
  ];

  const root = h(
    'section',
    { class: 'screen', id: 'screen-vision', hidden: true, 'aria-labelledby': 'vision-title' },
    h('h1', { id: 'vision-title', tabindex: '-1', text: 'Descrever tela ou imagem' }),
    h('p', { class: 'lead', text: 'O Blind AI descreve com detalhe o que aparece na tela ou em uma foto, incluindo textos, botões e pessoas.' }),
    h('div', { class: 'card' }, field('Pergunta específica sobre a imagem (opcional)', question), h('div', { class: 'button-grid' }, ...buttons), busy),
    h('div', { class: 'card' }, h('h2', { text: 'Resultado' }), output, h('div', { class: 'row' }, openChat))
  );

  function setBusy(on, text = '') {
    buttons.forEach((b) => (b.disabled = on));
    busy.textContent = on ? text : '';
    output.setAttribute('aria-busy', on ? 'true' : 'false');
  }

  async function describe(dataUrl, label) {
    const s = store.get();
    setBusy(true, 'Analisando a imagem...');
    const sessionId = await ctx.chat.newSession(`Audiodescrição: ${label}`, 'vision');
    ctx.chat.append('Audiodescrição', `${label}: analisando a imagem e gerando a descrição...`, false);
    announce(`${label}. Analisando a imagem e gerando a descrição.`, true);
    const res = await api.post(
      '/api/vision/describe',
      {
        image_base64: dataUrl,
        provider: s.provider,
        model: s.model || null,
        api_key: s.apiKey || null,
        prompt: question.value.trim() || undefined,
        session_id: sessionId,
        source_label: label,
      },
      180000
    );
    setBusy(false);
    if (!res.ok) {
      const msg = `Erro ao descrever a imagem: ${api.errorText(res)}`;
      output.textContent = msg;
      ctx.chat.append('Audiodescrição', msg, false);
      announce(msg, true);
      return;
    }
    const text = sanitizeScreenReaderText(res.data.description || 'O modelo não devolveu descrição.');
    output.textContent = text;
    ctx.chat.append(`Audiodescrição (${label})`, text, false);
    openChat.hidden = false;
    playBeep(660, 0.15);
    speak(text, { enabled: store.get().tts });
    announce(text, true);
    output.focus();
  }

  async function captureScreen() {
    playBeep(880, 0.12);
    announce('Capturando a tela principal para descrever.', true);
    const shot = await api.captureScreen();
    if (!shot.ok) {
      // O Electron nao obteve a imagem: o backend pede a captura ao MCP agent-desktop (screenshot oficial).
      announce('A captura direta falhou. Pedindo a captura à ferramenta agent-desktop.', true);
      await describe(null, 'Captura da tela atual');
      return;
    }
    await describe(shot.dataUrl, 'Captura da tela atual');
  }

  async function chooseImage() {
    playBeep(880, 0.12);
    announce('Abrindo o explorador de arquivos para escolher a imagem.', true);
    const file = await api.pickFile('image');
    if (file.canceled) {
      announce('Nenhuma imagem escolhida.', true);
      return;
    }
    if (file.error) {
      announce(`Não foi possível usar o arquivo: ${file.error}`, true);
      return;
    }
    await describe(file.dataUrl, file.name);
  }

  return {
    id: 'vision',
    label: 'Descrever tela ou imagem',
    title: 'Descrever tela ou imagem',
    key: 'Alt+Shift+T',
    root,
    actions: { captureScreen, chooseImage },
  };
}
