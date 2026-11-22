// Barra rapida global: permite digitar, falar por voz ou iniciar uma nova conversa de qualquer tela (Ctrl+K).

import { h, actionButton } from './dom.js';
import { announce, sanitizeScreenReaderText } from './a11y.js';
import { playBeep } from './sound.js';
import * as store from './store.js';
import * as voice from './voice.js';

export function createQuickbar({ rootEl, ctx }) {
  let busy = false;

  const contextEl = h('p', { id: 'quickbar-context', class: 'quickbar-context' });
  const replyTextEl = h('p', { id: 'quickbar-reply-text', class: 'quickbar-reply-text' });
  const openChatBtn = actionButton({
    id: 'btn-quick-open-chat',
    label: 'Ver conversa completa',
    cls: 'plain',
    onClick: () => ctx.nav('chat'),
  });
  const closeReplyBtn = actionButton({
    id: 'btn-quick-close-reply',
    label: 'Ocultar resposta',
    cls: 'plain',
    onClick: () => {
      replyBox.hidden = true;
      replyTextEl.textContent = '';
      input.focus();
    },
  });
  const replyBox = h(
    'div',
    {
      id: 'quickbar-reply',
      class: 'quickbar-reply',
      role: 'region',
      'aria-label': 'Última resposta rápida',
      tabindex: '-1',
      hidden: true,
    },
    replyTextEl,
    h('div', { class: 'row' }, openChatBtn, closeReplyBtn)
  );

  const input = h('input', {
    id: 'quickbar-input',
    type: 'text',
    class: 'quickbar-input',
    autocomplete: 'off',
    onKeydown: (e) => {
      const mode = store.get().sendShortcut || 'enter';
      if (mode === 'ctrl-enter') {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
          e.preventDefault();
          submit(input.value, false);
        }
      } else if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        submit(input.value, false);
      }
    },
  });

  const sendBtn = actionButton({
    id: 'btn-quick-send',
    label: 'Enviar',
    cls: 'sky',
    ariaLabel: 'Enviar mensagem pela barra rápida',
    onClick: () => submit(input.value, false),
  });
  const voiceBtn = actionButton({
    id: 'btn-quick-voice',
    label: 'Falar',
    cls: 'green',
    ariaLabel: 'Falar por voz nesta tela',
    onClick: () => dictateHere(),
  });
  const newBtn = actionButton({
    id: 'btn-quick-new',
    label: 'Nova conversa',
    cls: 'plain',
    ariaLabel: 'Iniciar nova conversa sem sair desta tela',
    onClick: () => startNew(),
  });

  function syncState() {
    const s = store.get();
    const title = (s.activeSessionTitle || '').trim();
    contextEl.textContent = title
      ? `Assunto atual: ${title}`
      : 'Nova conversa — digite ou fale de qualquer tela (Ctrl+K)';
    const mode = s.sendShortcut || 'enter';
    input.placeholder =
      mode === 'ctrl-enter'
        ? 'Pergunte ou peça ao Blind (Ctrl+Enter envia)...'
        : 'Pergunte ou peça ao Blind (Enter envia)...';
  }
  syncState();
  store.subscribe(syncState);

  function setBusy(on) {
    busy = on;
    sendBtn.disabled = on;
    newBtn.disabled = on;
  }

  async function submit(raw, fromVoice = false) {
    const text = String(raw || '').trim();
    if (!text || busy || !ctx.chat) return;
    setBusy(true);
    input.value = '';
    const res = await ctx.chat.send(text, { fromVoice });
    setBusy(false);
    if (!res || res.skipped) return;
    replyTextEl.textContent = sanitizeScreenReaderText(res.ok ? res.reply : res.error || 'Sem resposta.');
    replyBox.hidden = false;
  }

  async function dictateHere() {
    if (voice.isRecording()) {
      voice.dictate();
      return;
    }
    voiceBtn.classList.add('recording');
    const outcome = await voice.dictate();
    voiceBtn.classList.remove('recording');
    if (outcome.ok) {
      announce(`Você disse: ${outcome.text}`, true);
      await submit(outcome.text, true);
    } else {
      input.focus();
    }
  }

  function startNew() {
    if (ctx.chat && ctx.chat.startFreshSession) ctx.chat.startFreshSession();
    replyBox.hidden = true;
    replyTextEl.textContent = '';
    playBeep(660, 0.1);
    input.focus();
  }

  rootEl.append(
    contextEl,
    replyBox,
    h(
      'div',
      { class: 'quickbar-controls' },
      h('label', { for: 'quickbar-input', class: 'sr-only', text: 'Perguntar ou pedir ao Blind' }),
      input,
      sendBtn,
      voiceBtn,
      newBtn
    )
  );

  return {
    setVisible(visible) {
      rootEl.hidden = !visible;
    },
    focus() {
      if (!rootEl.hidden) input.focus();
    },
  };
}
