// Caixa de combinacao acessivel (WAI-ARIA APG Combobox com aria-activedescendant).
// Mantem o foco no campo de texto enquanto o leitor de tela navega pelas opcoes com as setas.

import { h, clear } from './dom.js';
import { announce } from './a11y.js';

export function createCombobox({ id, label, placeholder, items, onSelect, hint }) {
  const listId = `${id}-listbox`;
  const hintId = hint ? `${id}-hint` : null;
  let open = false;
  let filtered = [...items];
  let activeIndex = -1;

  const input = h('input', {
    id,
    type: 'text',
    class: 'combo-input',
    role: 'combobox',
    autocomplete: 'off',
    placeholder: placeholder || 'Digite para filtrar ou use Seta para Baixo...',
    'aria-expanded': 'false',
    'aria-autocomplete': 'list',
    'aria-haspopup': 'listbox',
    'aria-controls': listId,
    'aria-describedby': hintId || undefined,
    'aria-activedescendant': '',
  });

  const listbox = h('ul', {
    id: listId,
    class: 'combo-list',
    role: 'listbox',
    'aria-label': label,
    hidden: true,
  });

  function renderOptions() {
    clear(listbox);
    if (!filtered.length) {
      listbox.append(h('li', { class: 'combo-empty', role: 'presentation', text: 'Nenhuma opção encontrada.' }));
      input.setAttribute('aria-activedescendant', '');
      return;
    }
    filtered.forEach((item, idx) => {
      const optId = `${id}-opt-${idx}`;
      const isActive = idx === activeIndex;
      const opt = h(
        'li',
        {
          id: optId,
          role: 'option',
          class: isActive ? 'combo-option is-active' : 'combo-option',
          'aria-selected': isActive ? 'true' : 'false',
          onMouseDown: (e) => {
            e.preventDefault();
            choose(item);
          },
          onMouseEnter: () => {
            activeIndex = idx;
            syncActive();
          },
        },
        h('span', { class: 'combo-opt-label', text: item.label }),
        item.hint ? h('span', { class: 'combo-opt-hint', text: item.hint }) : null
      );
      listbox.append(opt);
    });
    syncActive();
  }

  function syncActive() {
    const els = listbox.querySelectorAll('[role="option"]');
    els.forEach((el, idx) => {
      const active = idx === activeIndex;
      el.classList.toggle('is-active', active);
      el.setAttribute('aria-selected', active ? 'true' : 'false');
      if (active) {
        input.setAttribute('aria-activedescendant', el.id);
        el.scrollIntoView({ block: 'nearest' });
      }
    });
    if (activeIndex < 0 || !els.length) {
      input.setAttribute('aria-activedescendant', '');
    }
  }

  function openList(initialIndex = 0) {
    open = true;
    input.setAttribute('aria-expanded', 'true');
    listbox.hidden = false;
    activeIndex = filtered.length ? Math.max(0, Math.min(initialIndex, filtered.length - 1)) : -1;
    renderOptions();
  }

  function closeList() {
    if (!open) return;
    open = false;
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-activedescendant', '');
    listbox.hidden = true;
    activeIndex = -1;
  }

  function filterItems(query) {
    const q = (query || '').trim().toLowerCase();
    filtered = q
      ? items.filter((it) => `${it.label} ${it.keywords || ''} ${it.hint || ''}`.toLowerCase().includes(q))
      : [...items];
    open = true;
    input.setAttribute('aria-expanded', 'true');
    listbox.hidden = false;
    activeIndex = filtered.length ? 0 : -1;
    renderOptions();
    announce(
      filtered.length
        ? `${filtered.length} ${filtered.length === 1 ? 'opção disponível' : 'opções disponíveis'}. ${filtered[0].label}`
        : 'Nenhuma opção encontrada.',
      false
    );
  }

  function choose(item) {
    if (!item) return;
    closeList();
    input.value = '';
    filtered = [...items];
    onSelect(item);
  }

  input.addEventListener('input', () => filterItems(input.value));

  input.addEventListener('keydown', (e) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        if (!open) {
          filtered = input.value.trim() ? filtered : [...items];
          openList(0);
        } else if (filtered.length) {
          activeIndex = (activeIndex + 1) % filtered.length;
          syncActive();
        }
        break;
      case 'ArrowUp':
        e.preventDefault();
        if (!open) {
          filtered = input.value.trim() ? filtered : [...items];
          openList(filtered.length - 1);
        } else if (filtered.length) {
          activeIndex = (activeIndex - 1 + filtered.length) % filtered.length;
          syncActive();
        }
        break;
      case 'Home':
        if (open && filtered.length) {
          e.preventDefault();
          activeIndex = 0;
          syncActive();
        }
        break;
      case 'End':
        if (open && filtered.length) {
          e.preventDefault();
          activeIndex = filtered.length - 1;
          syncActive();
        }
        break;
      case 'Enter':
        if (open && activeIndex >= 0 && filtered[activeIndex]) {
          e.preventDefault();
          choose(filtered[activeIndex]);
        } else if (filtered.length === 1) {
          e.preventDefault();
          choose(filtered[0]);
        } else if (!open) {
          e.preventDefault();
          openList(0);
        }
        break;
      case 'Escape':
        if (open) {
          e.preventDefault();
          e.stopPropagation();
          closeList();
        }
        break;
      default:
        break;
    }
  });

  input.addEventListener('blur', () => {
    setTimeout(() => closeList(), 120);
  });

  const root = h(
    'div',
    { class: 'combo-wrap' },
    h('label', { for: id, class: 'combo-label', text: label }),
    hint ? h('p', { id: hintId, class: 'hint', text: hint }) : null,
    input,
    listbox
  );

  return {
    root,
    input,
    focus: () => input.focus(),
    isOpen: () => open,
    close: closeList,
  };
}
