// Tela: WhatsApp (codigo de pareamento, sem QR Code) e Telegram (token do BotFather).

import { h, clear, actionButton, field } from '../lib/dom.js';
import { announce } from '../lib/a11y.js';
import { playBeep } from '../lib/sound.js';
import { speak } from '../lib/tts.js';
import * as api from '../lib/api.js';

export function createChannelsScreen(ctx) {
  const phone = h('input', { type: 'tel', id: 'wa-phone', placeholder: '+55 11 99999-9999', autocomplete: 'tel' });
  const codeOut = h('output', { id: 'wa-code', 'aria-live': 'assertive', 'aria-atomic': 'true' }, '----');
  const codeBox = h(
    'div',
    { class: 'code-box', role: 'region', 'aria-label': 'Código de pareamento do WhatsApp', hidden: true },
    h('p', { text: 'CÓDIGO DE PAREAMENTO DO WHATSAPP' }),
    codeOut
  );
  const speakBtn = actionButton({ id: 'btn-speak-code', label: 'Falar o código em voz alta', hint: 'Soletrado, letra por letra', cls: 'indigo', onClick: () => speakCode() });
  speakBtn.hidden = true;
  let currentCode = '';

  const token = h('input', { type: 'password', id: 'tg-token', autocomplete: 'off', placeholder: '123456789:ABC...' });
  const tgStatus = h('p', { id: 'tg-status', class: 'hint', role: 'status', 'aria-live': 'polite' });
  const botList = h('ul', { id: 'tg-bots', 'aria-label': 'Bots do Telegram conectados' });

  const whatsappPanel = h(
    'div',
    { id: 'panel-whatsapp', role: 'tabpanel', 'aria-labelledby': 'tab-whatsapp' },
    h('h2', { text: 'WhatsApp por número de telefone' }),
    h('p', { class: 'lead', text: 'Você não precisa enquadrar a câmera em QR Code. Digite seu celular, o Blind AI gera o código de 8 caracteres e você o digita em Aparelhos conectados.' }),
    field('Celular com código do país e DDD', phone, 'Exemplo: +55 11 99999-9999'),
    h('div', { class: 'row' }, actionButton({ id: 'btn-pair', label: 'Gerar código de pareamento', hint: 'Código de 8 caracteres', cls: 'green', onClick: () => pair() }), speakBtn),
    codeBox,
    h(
      'ol',
      { class: 'tool-list' },
      h('li', { text: 'Abra o WhatsApp no celular.' }),
      h('li', { text: 'Vá em Configurações, depois Aparelhos conectados.' }),
      h('li', { text: 'Toque em Conectar aparelho.' }),
      h('li', { text: 'Escolha Conectar com número de telefone.' }),
      h('li', { text: 'Digite o código de 8 caracteres mostrado aqui ou falado em voz alta.' })
    )
  );
  const telegramPanel = h(
    'div',
    { id: 'panel-telegram', role: 'tabpanel', 'aria-labelledby': 'tab-telegram', hidden: true },
    h('h2', { text: 'Bot do Telegram (BotFather)' }),
    h('p', { class: 'lead', text: 'Crie um bot gratuito conversando com @BotFather no Telegram e cole aqui o token HTTP API.' }),
    field('Token do bot', token, 'O token é enviado só ao seu servidor local e validado no Telegram.'),
    h('div', { class: 'row' }, actionButton({ id: 'btn-tg-connect', label: 'Salvar e conectar o bot', hint: 'Ativa a escuta do Telegram', cls: 'sky', onClick: () => connectTelegram() })),
    tgStatus,
    h('h3', { text: 'Bots conectados' }),
    botList
  );

  const tabWa = h('button', { type: 'button', role: 'tab', id: 'tab-whatsapp', class: 'tab green', 'aria-controls': 'panel-whatsapp', 'aria-selected': 'true', onClick: () => select('whatsapp') }, 'WhatsApp');
  const tabTg = h('button', { type: 'button', role: 'tab', id: 'tab-telegram', class: 'tab sky', 'aria-controls': 'panel-telegram', 'aria-selected': 'false', tabindex: '-1', onClick: () => select('telegram') }, 'Telegram');
  const tablist = h('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Canal de mensagens', onKeydown: onTabKey }, tabWa, tabTg);

  const root = h(
    'section',
    { class: 'screen', id: 'screen-channels', hidden: true, 'aria-labelledby': 'channels-title' },
    h('h1', { id: 'channels-title', tabindex: '-1', text: 'Conectar WhatsApp ou Telegram' }),
    tablist,
    h('div', { class: 'card' }, whatsappPanel, telegramPanel)
  );

  function select(channel, focus = false) {
    const wa = channel === 'whatsapp';
    tabWa.setAttribute('aria-selected', String(wa));
    tabTg.setAttribute('aria-selected', String(!wa));
    tabWa.tabIndex = wa ? 0 : -1;
    tabTg.tabIndex = wa ? -1 : 0;
    whatsappPanel.hidden = !wa;
    telegramPanel.hidden = wa;
    if (focus) (wa ? tabWa : tabTg).focus();
    if (!wa) loadBots();
    playBeep(600, 0.1);
  }

  function onTabKey(e) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault();
    const toWa = e.key === 'Home' || (e.key !== 'End' && document.activeElement === tabTg);
    select(toWa ? 'whatsapp' : 'telegram', true);
  }

  async function pair() {
    const digits = phone.value.trim().replace(/[^0-9+]/g, '');
    if (digits.length < 8) {
      announce('Informe um número válido com código do país e DDD.', true);
      phone.focus();
      return;
    }
    playBeep(880, 0.2);
    announce('Gerando o código de pareamento...', false);
    const res = await api.post('/api/whatsapp/pair', { phone: digits });
    if (!res.ok) {
      announce(`Não consegui gerar o código: ${api.errorText(res)}`, true);
      return;
    }
    currentCode = res.data.code;
    codeOut.textContent = currentCode;
    codeBox.hidden = false;
    speakBtn.hidden = false;
    announce(`Código de pareamento gerado: ${[...currentCode].join(' ')}. Digite este código no WhatsApp do celular.`, true);
  }

  function speakCode() {
    if (!currentCode) return;
    const spelled = [...currentCode].join(', ');
    const message = `Atenção. Seu código de pareamento do WhatsApp é: ${spelled}. Repetindo: ${spelled}.`;
    speak(message, { force: true, rate: 0.85 });
    announce(message, true);
  }

  async function connectTelegram() {
    const value = token.value.trim();
    if (!value.includes(':')) {
      announce('Informe um token válido do Telegram, no formato números, dois pontos, letras.', true);
      token.focus();
      return;
    }
    playBeep(880, 0.15);
    tgStatus.textContent = 'Conectando ao Telegram e validando o token...';
    const res = await api.post('/api/telegram/connect', { bot_token: value });
    if (res.ok && res.data && res.data.status === 'connected') {
      tgStatus.textContent = `Bot @${res.data.bot_username} conectado com sucesso.`;
      token.value = '';
      announce(tgStatus.textContent, true);
      loadBots();
    } else {
      tgStatus.textContent = `O Telegram recusou: ${api.errorText(res)}`;
      announce(tgStatus.textContent, true);
    }
  }

  async function loadBots() {
    const res = await api.get('/api/telegram/status');
    clear(botList);
    const bots = res.ok && res.data && Array.isArray(res.data.bots) ? res.data.bots : [];
    if (!bots.length) botList.append(h('li', { text: 'Nenhum bot conectado.' }));
    bots.forEach((b) => botList.append(h('li', { text: `@${b.username || b.bot_username || b.id}` })));
  }

  return {
    id: 'channels',
    label: 'WhatsApp e Telegram',
    title: 'WhatsApp e Telegram',
    key: 'Alt+Shift+W',
    root,
    onShow: () => select('whatsapp'),
  };
}
