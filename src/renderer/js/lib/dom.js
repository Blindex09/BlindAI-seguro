// Criacao de elementos sem innerHTML: texto sempre entra como textContent.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'text') el.textContent = value;
    else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'hidden') el.hidden = Boolean(value);
    else if (key === 'value') el.value = value;
    else if (key === 'checked' || key === 'disabled') el[key] = Boolean(value);
    else el.setAttribute(key, value === true ? '' : String(value));
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function clear(el) {
  el.textContent = '';
  return el;
}

// Botao com titulo e dica secundaria (a dica fica no texto lido pelo leitor de tela).
export function actionButton({ id, label, hint, cls = '', onClick, ariaLabel }) {
  return h(
    'button',
    { type: 'button', id, class: cls, 'aria-label': ariaLabel, onClick },
    h('span', { text: label }),
    hint ? h('span', { class: 'btn-hint', text: hint }) : null
  );
}

export function field(labelText, control, hintText) {
  const id = control.id || `f-${Math.random().toString(36).slice(2, 8)}`;
  control.id = id;
  const wrap = h('div', { class: 'field' }, h('label', { for: id, text: labelText }), control);
  if (hintText) {
    const hintId = `${id}-hint`;
    control.setAttribute('aria-describedby', hintId);
    wrap.append(h('p', { id: hintId, class: 'hint', text: hintText }));
  }
  return wrap;
}
