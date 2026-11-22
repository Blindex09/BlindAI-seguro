// Tela: Smart Writer (redigir, ditar, revisar em voz alta e salvar com seguranca).

import { h, actionButton, field } from '../lib/dom.js';
import { announce } from '../lib/a11y.js';
import { playBeep } from '../lib/sound.js';
import { speak } from '../lib/tts.js';
import * as api from '../lib/api.js';
import * as store from '../lib/store.js';
import * as voice from '../lib/voice.js';

export function createWriterScreen(ctx) {
  const title = h('input', { type: 'text', id: 'writer-title', placeholder: 'Ex.: Minuta de reunião ou carta pessoal' });
  const content = h('textarea', { id: 'writer-content', rows: 8, placeholder: 'Digite ou dite o conteúdo aqui...' });
  const review = h('div', { id: 'writer-review', class: 'output', role: 'region', 'aria-label': 'Revisão do documento', tabindex: '0', hidden: true });
  let draft = null;
  const dictateBtn = actionButton({ id: 'btn-writer-dictate', label: 'Ditar texto', hint: 'Grava e acrescenta ao documento', cls: 'indigo', onClick: () => dictate() });

  const root = h(
    'section',
    { class: 'screen', id: 'screen-writer', hidden: true, 'aria-labelledby': 'writer-title-h' },
    h('h1', { id: 'writer-title-h', tabindex: '-1', text: 'Redigir ou ditar' }),
    h('p', { class: 'lead', text: 'Escreva cartas, notas ou relatórios. O Blind AI lê tudo de volta antes de salvar com segurança.' }),
    h(
      'div',
      { class: 'card' },
      field('Título do documento', title),
      field('Conteúdo do documento', content),
      h(
        'div',
        { class: 'row' },
        actionButton({ id: 'btn-review', label: 'Revisar em voz alta', hint: 'Lê o documento de volta', cls: 'sky', onClick: () => reviewDraft() }),
        actionButton({ id: 'btn-save', label: 'Salvar documento', hint: 'Gravação atômica segura', cls: 'green', onClick: () => saveDraft() }),
        dictateBtn,
        actionButton({ id: 'btn-writer-chat', label: 'Conversar sobre o documento', hint: 'Abre na conversa', cls: 'plain', onClick: () => openInChat() })
      ),
      review
    )
  );

  const currentTitle = () => title.value.trim() || 'Documento sem título';

  async function reviewDraft() {
    const text = content.value.trim();
    if (!text) {
      announce('Digite ou dite o conteúdo antes de revisar.', true);
      content.focus();
      return null;
    }
    playBeep(880, 0.15);
    announce('Gerando a minuta e a revisão falada...', false);
    const res = await api.post('/api/writer/draft', { title: currentTitle(), content: text });
    if (!res.ok) {
      announce(`Falha ao preparar a minuta: ${api.errorText(res)}`, true);
      return null;
    }
    draft = res.data;
    review.hidden = false;
    review.textContent = draft.spoken_review || 'Minuta pronta.';
    speak(review.textContent, { enabled: store.get().tts });
    announce(review.textContent, true);
    return draft;
  }

  async function saveDraft() {
    if (!draft && !(await reviewDraft())) return;
    playBeep(660, 0.2);
    announce('Gravando o documento com segurança...', false);
    const res = await api.post('/api/writer/save', { draft });
    if (!res.ok) {
      announce(`Falha ao salvar o documento: ${api.errorText(res)}`, true);
      return;
    }
    const savedTitle = draft.title || currentTitle();
    announce(res.data.confirmation_speech || 'Documento salvo.', true);
    await ctx.chat.newSession(`Documento: ${savedTitle}`, 'writer');
    ctx.chat.append('Smart Writer', `Documento '${savedTitle}' salvo com sucesso. Você pode pedir ajustes, resumos ou melhorias aqui.`, false);
    draft = null;
  }

  async function openInChat() {
    const t = currentTitle();
    const text = content.value.trim();
    playBeep(750, 0.12);
    await ctx.chat.newSession(`Documento: ${t}`, 'writer');
    ctx.chat.append(
      'Smart Writer',
      text ? `Documento: ${t}\n\n${text}\n\nPeça ajustes, resumos ou melhorias para este documento.` : `Documento '${t}' criado. Diga sobre o que deseja escrever.`,
      false
    );
    ctx.nav('chat');
    announce(`Conversa sobre o documento ${t} aberta.`, true);
  }

  async function dictate() {
    if (voice.isRecording()) {
      voice.dictate();
      return;
    }
    dictateBtn.classList.add('recording');
    const outcome = await voice.dictate();
    dictateBtn.classList.remove('recording');
    if (outcome.ok) {
      content.value = (content.value ? `${content.value} ` : '') + outcome.text;
      draft = null;
      announce(`Texto ditado: ${outcome.text}`, true);
    }
    content.focus();
  }

  return {
    id: 'writer',
    label: 'Redigir ou ditar',
    title: 'Redigir ou ditar',
    key: 'Alt+Shift+E',
    root,
    onShow: () => {},
    focusFirst: () => title.focus(),
  };
}
