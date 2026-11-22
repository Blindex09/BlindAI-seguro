// Navegacao entre telas: um unico <main>, uma tela visivel por vez, foco no titulo ao trocar.
// Usa uma caixa de combinacao global no topo + botao Voltar ao Inicio (Esc), sem barra lateral cheia de botoes.

import { announce, setDocumentTitle } from './lib/a11y.js';
import { h } from './lib/dom.js';

export function createRouter({ navEl, mainEl, screens, onRouteChange }) {
  const byId = new Map(screens.map((s) => [s.id, s]));
  const options = new Map();
  let currentId = null;

  const navSelect = h('select', {
    id: 'nav-select',
    class: 'nav-select',
    'aria-label': 'Trocar de tela',
    onChange: () => {
      if (navSelect.value && navSelect.value !== currentId) show(navSelect.value);
    },
  });

  const homeBtn = h(
    'button',
    {
      type: 'button',
      id: 'btn-nav-home',
      class: 'nav-home-btn',
      'aria-label': 'Voltar ao Início. Atalho Escape',
      onClick: () => show('home'),
    },
    'Voltar ao Início (Esc)'
  );

  screens.forEach((screen) => {
    mainEl.append(screen.root);
    const opt = h('option', {
      value: screen.id,
      'data-screen': screen.id,
      text: `${screen.label} (${screen.key})`,
    });
    options.set(screen.id, opt);
    navSelect.append(opt);
  });

  navEl.append(
    h('label', { for: 'nav-select', class: 'sr-only', text: 'Ir para tela' }),
    navSelect,
    homeBtn
  );

  function show(id, { focus = true, announceTitle = true } = {}) {
    const next = byId.get(id);
    if (!next) return false;
    if (currentId && currentId !== id) {
      const prev = byId.get(currentId);
      prev.root.hidden = true;
      if (prev.onHide) prev.onHide();
    }
    currentId = id;
    next.root.hidden = false;
    mainEl.dataset.currentScreen = id;
    navEl.hidden = id === 'home';

    options.forEach((opt, key) => {
      const scr = byId.get(key);
      opt.hidden = Boolean(scr && scr.advanced && key !== id);
    });
    navSelect.value = id;

    setDocumentTitle(next.title);
    mainEl.scrollTop = 0;
    if (next.onShow) next.onShow();
    if (focus) {
      const heading = next.root.querySelector('h1');
      if (heading) heading.focus();
    }
    if (announceTitle) announce(`Tela ${next.title}.`, false);
    if (onRouteChange) onRouteChange(id);
    return true;
  }

  return { show, current: () => currentId, has: (id) => byId.has(id) };
}
