// Tela: Atividades. O que o Blind fez, o que deu certo e o que deu errado, em frases simples.
// Acessibilidade: lista navegavel por leitor de tela; NENHUM anuncio automatico (nao interrompe a pessoa).
// So anuncia o resumo quando a pessoa pede (Atualizar) ou muda o filtro. Atualizar sozinho e opcional e silencioso.

import { h, clear, actionButton } from '../lib/dom.js';
import { announce } from '../lib/a11y.js';
import * as api from '../lib/api.js';

const STATE_TEXT = {
  deu_certo: 'Deu certo',
  falhou: 'Falhou',
  aviso: 'Aviso',
  corrigido: 'Corrigido sozinho',
  em_andamento: 'Em andamento',
};
const STATE_CLASS = { deu_certo: 'state-connected', corrigido: 'state-connected', falhou: 'state-error', aviso: 'state-starting', em_andamento: 'state-starting' };

function when(iso) {
  // "2026-11-17T12:32:47" -> "12:32:47" (hoje) ou "17/11 12:32:47"
  if (!iso || typeof iso !== 'string' || iso.length < 19) return '';
  const local = new Date();
  const localDay = `${local.getFullYear()}-${String(local.getMonth() + 1).padStart(2, '0')}-${String(local.getDate()).padStart(2, '0')}`;
  const time = iso.slice(11, 19);
  return iso.slice(0, 10) === localDay ? time : `${iso.slice(8, 10)}/${iso.slice(5, 7)} ${time}`;
}

export function createActivityScreen() {
  const status = h('p', { id: 'activity-status', class: 'lead', role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true' }, 'Carregando atividades...');
  const list = h('ul', { id: 'activity-list', class: 'server-list', 'aria-label': 'Atividades recentes, da mais nova para a mais antiga' });
  const onlyErrors = h('input', { type: 'checkbox', id: 'activity-only-errors' });
  const autoRefresh = h('input', { type: 'checkbox', id: 'activity-auto' });
  let timer = null;
  let visible = false;
  let lastStatusText = '';

  const root = h(
    'section',
    { class: 'screen', id: 'screen-activity', hidden: true, 'aria-labelledby': 'activity-title' },
    h('h1', { id: 'activity-title', tabindex: '-1', text: 'Atividades' }),
    h('p', { class: 'lead', text: 'Aqui você vê o que o Blind AI fez no seu computador, o que deu certo e o que deu errado. Nada é falado sozinho: a lista só muda quando você atualiza.' }),
    h(
      'div',
      { class: 'row' },
      actionButton({ id: 'btn-activity-refresh', label: 'Atualizar a lista', cls: 'sky', onClick: () => load(true) })
    ),
    h('div', { class: 'field' }, onlyErrors, h('label', { for: 'activity-only-errors', text: 'Mostrar só o que falhou' })),
    h('div', { class: 'field' }, autoRefresh, h('label', { for: 'activity-auto', text: 'Atualizar a lista sozinho a cada 5 segundos, sem avisar por voz' })),
    status,
    list
  );

  function setStatus(text) {
    if (text !== lastStatusText) {
      lastStatusText = text;
      status.textContent = text;
    }
  }

  function render(items) {
    clear(list);
    items.forEach((it) => {
      const stateText = STATE_TEXT[it.estado] || it.estado;
      const li = h('li', { class: 'server-item' });
      li.append(
        h(
          'p',
          {},
          h('strong', { class: `name ${STATE_CLASS[it.estado] || ''}`, text: `${stateText}: ` }),
          it.frase,
          h('span', { class: 'hint', text: ` ${it.origem}${when(it.quando) ? `, ${when(it.quando)}` : ''}${it.ms ? `, ${(it.ms / 1000).toFixed(1).replace('.', ',')} s` : ''}` })
        )
      );
      list.append(li);
    });
  }

  async function load(announceResult) {
    const qs = `?limit=50${onlyErrors.checked ? '&only_errors=true' : ''}`;
    const res = await api.get(`/api/activity${qs}`);
    if (!res.ok || !res.data || !Array.isArray(res.data.atividades)) {
      clear(list);
      setStatus(`Não consegui consultar as atividades: ${api.errorText(res)}`);
      if (announceResult) announce(lastStatusText, true);
      return;
    }
    render(res.data.atividades);
    setStatus(res.data.resumo);
    if (announceResult) announce(lastStatusText, true);
    schedule();
  }

  function schedule() {
    clearTimeout(timer);
    if (visible && autoRefresh.checked) timer = setTimeout(() => load(false), 5000);
  }

  onlyErrors.addEventListener('change', () => load(true));
  autoRefresh.addEventListener('change', () => {
    if (autoRefresh.checked) load(false);
    else clearTimeout(timer);
  });

  return {
    id: 'activity',
    label: 'Atividades',
    title: 'Atividades',
    key: 'Alt+Shift+A',
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
