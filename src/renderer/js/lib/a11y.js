// Acessibilidade: higienizacao de texto para leitores de tela, anuncios e formatacao semantica.

import * as store from './store.js';

export function sanitizeScreenReaderText(text) {
  if (!text) return '';
  return String(text)
    .replace(/```[a-zA-Z]*\n?/g, '')
    .replace(/```/g, '')
    .replace(/`/g, '')
    .replace(/\*{1,3}/g, '')
    .replace(/^#{1,6}\s*/gm, '')
    .replace(/^[*-]\s+/gm, '')
    .replace(/_{1,2}/g, '')
    .replace(/[ \t]+/g, ' ')
    .trim();
}

let assertiveTimer = null;
let politeTimer = null;

// assertive: interrompe o leitor (acoes concluidas, erros). polite: informacao de fundo.
export function announce(text, assertive = false) {
  if (!assertive && store.get().verboseAnnouncements === false) return;
  const el = document.getElementById(assertive ? 'sr-assertive' : 'sr-polite');
  if (!el) return;
  const clean = sanitizeScreenReaderText(text);
  const timerName = assertive ? 'assertive' : 'polite';
  clearTimeout(timerName === 'assertive' ? assertiveTimer : politeTimer);
  el.textContent = '';
  // O intervalo curto faz o leitor perceber a mudanca mesmo quando o texto se repete.
  setTimeout(() => {
    el.textContent = clean;
  }, 50);
  const timer = setTimeout(() => {
    el.textContent = '';
  }, 4000);
  if (assertive) assertiveTimer = timer;
  else politeTimer = timer;
}

export function setDocumentTitle(screenTitle) {
  if (!screenTitle || screenTitle === 'Blind') {
    document.title = 'Blind';
  } else if (screenTitle.startsWith('Blind - ')) {
    document.title = screenTitle;
  } else {
    document.title = `Blind - ${screenTitle}`;
  }
}

// Converte texto em paragrafos, <ol> e <ul> semanticos (leitores de tela anunciam "lista, 3 itens").
export function formatAccessibleMessageHtml(rawText) {
  const clean = sanitizeScreenReaderText(rawText);
  const wrapper = document.createElement('div');
  wrapper.className = 'message-content';
  if (!clean) return wrapper;

  let ol = null;
  let ul = null;
  let paragraph = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const p = document.createElement('p');
    p.textContent = paragraph.join(' ');
    wrapper.appendChild(p);
    paragraph = [];
  };

  for (const rawLine of clean.split('\n')) {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      ol = null;
      ul = null;
      continue;
    }
    const orderedItem = line.match(/^(\d{1,3})[.)]\s+(.+)$/);
    if (orderedItem) {
      flushParagraph();
      ul = null;
      if (!ol) {
        ol = document.createElement('ol');
        const start = parseInt(orderedItem[1], 10);
        if (start > 1) ol.setAttribute('start', String(start));
        wrapper.appendChild(ol);
      }
      const li = document.createElement('li');
      li.textContent = orderedItem[2];
      ol.appendChild(li);
      continue;
    }
    const bulletItem = line.match(/^[•\-*]\s+(.+)$/);
    if (bulletItem) {
      flushParagraph();
      ol = null;
      if (!ul) {
        ul = document.createElement('ul');
        wrapper.appendChild(ul);
      }
      const li = document.createElement('li');
      li.textContent = bulletItem[1];
      ul.appendChild(li);
      continue;
    }
    ol = null;
    ul = null;
    paragraph.push(line);
  }
  flushParagraph();
  return wrapper;
}

// Remove emojis e simbolos pictograficos: leitores de tela os leem por extenso e poluem a fala.
export function stripEmoji(text) {
  return String(text || '').replace(/[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{FE0F}]/gu, '');
}
