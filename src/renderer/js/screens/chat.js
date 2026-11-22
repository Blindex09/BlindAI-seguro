// Tela: Conversa com o Blind AI (historico persistente, ditado por voz, acoes MCP visiveis).

import { h, clear, actionButton } from '../lib/dom.js';
import { announce, formatAccessibleMessageHtml, sanitizeScreenReaderText, setDocumentTitle } from '../lib/a11y.js';
import { playBeep } from '../lib/sound.js';
import { speak } from '../lib/tts.js';
import * as api from '../lib/api.js';
import * as store from '../lib/store.js';
import * as voice from '../lib/voice.js';
import { askText } from '../lib/dialog.js';

export function createChatScreen(ctx) {
  const log = h('div', {
    id: 'chat-log',
    class: 'chat-log',
    role: 'log',
    'aria-live': 'polite',
    'aria-atomic': 'false',
    'aria-label': 'Histórico de mensagens da conversa',
    tabindex: '0',
  });
  const sessionSelect = h('select', {
    id: 'session-select',
    'aria-label': 'Conversas anteriores. Escolha uma para continuar.',
    onChange: (e) => switchSession(e.target.value),
  });
  const input = h('textarea', {
    id: 'chat-input',
    rows: 2,
    placeholder: 'Digite sua mensagem. Enter envia, Shift mais Enter quebra a linha.',
    'aria-label': 'Escreva sua mensagem para a inteligência artificial',
    onKeydown: (e) => {
      const mode = store.get().sendShortcut || 'enter';
      if (mode === 'ctrl-enter') {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
          e.preventDefault();
          send(input.value);
        }
      } else if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        send(input.value);
      }
    },
  });
  function syncInputPlaceholder() {
    const mode = store.get().sendShortcut || 'enter';
    input.placeholder = mode === 'ctrl-enter'
      ? 'Digite sua mensagem. Ctrl mais Enter envia, Enter quebra a linha.'
      : 'Digite sua mensagem. Enter envia, Shift mais Enter quebra a linha.';
  }
  syncInputPlaceholder();
  store.subscribe(syncInputPlaceholder);
  const sendBtn = actionButton({ id: 'btn-send', label: 'Enviar', cls: 'sky', onClick: () => send(input.value), ariaLabel: 'Enviar mensagem' });
  const micBtn = actionButton({ id: 'btn-dictate', label: 'Ditar por voz', cls: 'green', onClick: () => dictate(), ariaLabel: 'Ditar mensagem por microfone. Pressione de novo ou Escape para terminar.' });
  const jarvisBtn = actionButton({
    id: 'btn-jarvis-chat',
    label: 'Modo Jarvis (voz contínua)',
    cls: 'plain',
    onClick: () => toggleJarvis(),
    ariaLabel: 'Alternar Modo Jarvis de conversa por voz contínua mãos-livres',
  });

  function syncJarvisButton() {
    const on = Boolean(store.get().jarvisMode);
    jarvisBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
    jarvisBtn.textContent = on ? 'Modo Jarvis: Ativo (toque para pausar)' : 'Modo Jarvis (voz contínua)';
  }
  syncJarvisButton();

  const chatHeading = h('h1', { id: 'chat-title', tabindex: '-1', text: 'Blind' });
  const sessionsTitleById = new Map();

  function syncChatTitle() {
    const sessTitle = (store.get().activeSessionTitle || '').trim();
    const full = sessTitle ? `Blind - ${sessTitle}` : 'Blind';
    chatHeading.textContent = full;
    setDocumentTitle(full);
  }

  const root = h(
    'section',
    { class: 'screen', id: 'screen-chat', hidden: true, 'aria-labelledby': 'chat-title' },
    chatHeading,
    h('p', { class: 'lead', text: 'Fale por voz (Modo Jarvis ou ditado) ou digite por texto. O Blind AI escolhe o modelo e as ferramentas MCP automaticamente.' }),
    h(
      'div',
      { class: 'row', style: undefined },
      actionButton({ id: 'btn-new-chat', label: 'Nova conversa', cls: 'sky', onClick: () => newConversation(), ariaLabel: 'Iniciar nova conversa' }),
      jarvisBtn,
      actionButton({ id: 'btn-clear-chat', label: 'Limpar mensagens da tela', cls: 'plain', onClick: clearView, ariaLabel: 'Limpar as mensagens exibidas nesta tela' })
    ),
    h('div', { class: 'field' }, h('label', { for: 'session-select', text: 'Conversas anteriores' }), sessionSelect),
    log,
    h('div', { class: 'composer' }, input, sendBtn, micBtn)
  );

  function append(sender, text, isUser = false, actions = []) {
    const clean = sanitizeScreenReaderText(text);
    const bubble = h(
      'div',
      { class: `bubble ${isUser ? 'user' : 'assistant'}`, role: 'article' },
      h('span', { class: 'who', text: `${sender}:` }),
      formatAccessibleMessageHtml(clean)
    );
    if (actions && actions.length && store.get().showAgentSteps !== false) {
      const list = h('ul', { class: 'tool-list' });
      actions.forEach((a) => {
        list.append(h('li', { text: `${a.server || 'ferramenta'} ${a.tool || a.action}: ${a.status === 'success' ? 'concluída' : 'falhou'}` }));
      });
      bubble.append(h('details', {}, h('summary', { text: `Ações executadas no computador (${actions.length})` }), list));
    }
    log.append(bubble);
    log.scrollTop = log.scrollHeight;
  }

  function clearView() {
    clear(log);
    playBeep(440, 0.1);
    announce('Mensagens da tela limpas.', true);
    input.focus();
  }

  async function loadSessions() {
    const res = await api.get('/api/sessions');
    clear(sessionSelect);
    const sessions = res.ok && res.data && Array.isArray(res.data.sessions) ? res.data.sessions : [];
    if (!sessions.length) {
      sessionSelect.append(h('option', { value: '', text: 'Nenhuma conversa salva ainda' }));
      return;
    }
    sessionSelect.append(h('option', { value: '', text: 'Selecione uma conversa do histórico' }));
    sessionsTitleById.clear();
    sessions.forEach((s) => {
      sessionsTitleById.set(s.id, s.title);
      const time = new Date(s.updated_at * 1000).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
      const opt = h('option', { value: s.id, text: `${String(s.source || 'chat').toUpperCase()}: ${s.title} (${time})` });
      if (s.id === store.get().activeSessionId) {
        opt.selected = true;
        if (store.get().activeSessionTitle !== s.title) store.set({ activeSessionTitle: s.title });
      }
      sessionSelect.append(opt);
    });
    syncChatTitle();
  }

  async function newSession(title, source = 'chat') {
    const res = await api.post('/api/sessions', { title, source });
    if (!res.ok || !res.data || !res.data.id) {
      announce(`Não consegui criar a conversa: ${api.errorText(res)}`, true);
      return null;
    }
    store.set({ activeSessionId: res.data.id, activeSessionTitle: title });
    syncChatTitle();
    clear(log);
    await loadSessions();
    announce(`Nova conversa iniciada: ${title}.`, true);
    return res.data.id;
  }

  async function newConversation() {
    const title = await askText({ title: 'Nova conversa', label: 'Título da conversa', value: 'Nova conversa', confirmText: 'Criar' });
    if (!title) return;
    await newSession(title, 'chat');
    ctx.nav('chat');
    input.focus();
  }

  async function switchSession(id) {
    if (!id) return;
    const sessTitle = sessionsTitleById.get(id) || '';
    store.set({ activeSessionId: id, activeSessionTitle: sessTitle });
    syncChatTitle();
    const res = await api.get(`/api/sessions/${encodeURIComponent(id)}/messages`);
    if (!res.ok) {
      announce(`Não consegui abrir a conversa: ${api.errorText(res)}`, true);
      return;
    }
    clear(log);
    const messages = (res.data && res.data.messages) || [];
    messages.forEach((m) => append(m.sender, m.text, m.is_user));
    announce(messages.length ? `Conversa carregada com ${messages.length} mensagens.` : 'Esta conversa não tem mensagens salvas.', true);
  }

  let sending = false;
  async function send(raw, { fromVoice = false } = {}) {
    const text = String(raw || '').trim();
    if (!text || sending) return { ok: false, skipped: true };

    // Comando falado para encerrar o Modo Jarvis
    if (fromVoice && /\b(parar de ouvir|encerrar jarvis|desligar jarvis|pausar jarvis|encerrar modo jarvis)\b/i.test(text)) {
      store.set({ jarvisMode: false });
      syncJarvisButton();
      announce('Modo Jarvis desativado.', true);
      speak('Modo Jarvis desativado.', { force: true });
      return { ok: true, reply: 'Modo Jarvis desativado.' };
    }

    sending = true;
    input.value = '';
    // A sessao precisa existir ANTES de exibir a mensagem: criar uma sessao limpa o historico da tela.
    if (!store.get().activeSessionId) {
      const title = text.length > 48 ? `${text.slice(0, 45)}...` : text;
      await newSession(title, 'chat');
    }
    append('Você', text, true);
    playBeep(880, 0.1);
    log.setAttribute('aria-busy', 'true');
    sendBtn.disabled = true;
    ctx.setStatus('busy', 'Blind AI está pensando...');
    announce('Enviando para o Blind AI...', false);

    const s = store.get();
    const res = await api.post(
      '/api/chat',
      {
        message: text,
        session_id: store.get().activeSessionId,
        provider: s.provider || 'auto',
        model: s.model || null,
        api_key: s.apiKey || null,
        speak: false,
        response_style: s.responseStyle || 'curto',
        custom_instructions: s.customInstructions || '',
      },
      180000
    );

    log.removeAttribute('aria-busy');
    sendBtn.disabled = false;
    sending = false;
    if (!res.ok) {
      const msg = `Não consegui falar com a IA: ${api.errorText(res)}`;
      append('Blind AI (aviso)', msg);
      playBeep(330, 0.2);
      announce(msg, true);
      ctx.setStatus('error', 'Falha na conversa');
      return { ok: false, error: msg };
    }
    const data = res.data || {};
    const reply = data.reply || 'A IA não devolveu texto.';
    append('Blind AI', reply, false, data.actions || []);
    playBeep(660, 0.15);
    const shouldContinueJarvis = () => {
      if (store.get().jarvisMode && !voice.isRecording() && !sending) {
        setTimeout(() => {
          if (store.get().jarvisMode && !voice.isRecording() && !sending) dictate();
        }, 350);
      }
    };
    speak(reply, { force: fromVoice, enabled: store.get().tts, onEnd: shouldContinueJarvis });
    announce(`Blind AI respondeu: ${reply}`, true);
    ctx.setStatus('ready', 'Pronto');
    if (data.status === 'error') ctx.setStatus('error', 'A IA devolveu um erro');
    loadSessions();
    return { ok: true, reply, actions: data.actions || [] };
  }

  async function dictate() {
    if (voice.isRecording()) {
      voice.dictate();
      return;
    }
    micBtn.classList.add('recording');
    const outcome = await voice.dictate();
    micBtn.classList.remove('recording');
    if (outcome.ok) {
      announce(`Você disse: ${outcome.text}`, true);
      await send(outcome.text, { fromVoice: true });
    } else {
      if (store.get().jarvisMode) {
        store.set({ jarvisMode: false });
        syncJarvisButton();
      }
      input.focus();
    }
  }

  function toggleJarvis(forceOn = null) {
    const next = forceOn !== null ? Boolean(forceOn) : !store.get().jarvisMode;
    store.set({ jarvisMode: next });
    syncJarvisButton();
    if (next) {
      announce('Modo Jarvis ativado. Pode falar seu comando.', true);
      if (!voice.isRecording() && !sending) dictate();
    } else {
      voice.cancelDictation();
      announce('Modo Jarvis pausado.', true);
    }
  }

  function startFreshSession() {
    store.set({ activeSessionId: null, activeSessionTitle: '' });
    syncChatTitle();
    clear(log);
    sessionSelect.value = '';
    announce('Nova conversa pronta. Diga ou digite sua próxima mensagem.', true);
  }

  return {
    id: 'chat',
    label: 'Conversa',
    title: 'Blind',
    key: 'Alt+Shift+C',
    root,
    onShow: () => {
      syncChatTitle();
      syncJarvisButton();
      loadSessions();
    },
    focusInput: () => input.focus(),
    api: { append, send, newSession, startFreshSession, dictate, toggleJarvis, loadSessions },
  };
}
