// Dialogo modal acessivel (substitui window.prompt/confirm, que o Electron nao oferece).
// <dialog> nativo: foco preso, Esc fecha, foco volta ao elemento que abriu.

import { h } from './dom.js';

export function askText({ title, label, value = '', confirmText = 'Confirmar' }) {
  const dialog = document.getElementById('dialog');
  const opener = document.activeElement;
  return new Promise((resolve) => {
    const input = h('input', { type: 'text', id: 'dialog-input', value });
    const form = h(
      'form',
      { method: 'dialog' },
      h('h2', { id: 'dialog-title', text: title }),
      h('label', { for: 'dialog-input', text: label }),
      input,
      h(
        'div',
        { class: 'row' },
        h('button', { type: 'button', class: 'plain', text: 'Cancelar', onClick: () => dialog.close('cancel') }),
        h('button', { type: 'submit', text: confirmText })
      )
    );
    dialog.textContent = '';
    dialog.append(form);
    form.addEventListener('submit', () => {
      dialog.returnValue = 'ok';
    });
    dialog.addEventListener(
      'close',
      () => {
        const ok = dialog.returnValue === 'ok';
        const text = input.value.trim();
        dialog.textContent = '';
        if (opener && opener.focus) opener.focus();
        resolve(ok && text ? text : null);
      },
      { once: true }
    );
    dialog.returnValue = '';
    dialog.showModal();
    input.focus();
    input.select();
  });
}

export function confirmDialog({ title, message, confirmText = 'Confirmar' }) {
  const dialog = document.getElementById('dialog');
  const opener = document.activeElement;
  return new Promise((resolve) => {
    const form = h(
      'form',
      { method: 'dialog' },
      h('h2', { id: 'dialog-title', text: title }),
      h('p', { text: message }),
      h(
        'div',
        { class: 'row' },
        h('button', { type: 'button', class: 'plain', text: 'Cancelar', onClick: () => dialog.close('cancel') }),
        h('button', { type: 'submit', id: 'dialog-confirm', text: confirmText })
      )
    );
    dialog.textContent = '';
    dialog.append(form);
    form.addEventListener('submit', () => {
      dialog.returnValue = 'ok';
    });
    dialog.addEventListener(
      'close',
      () => {
        const ok = dialog.returnValue === 'ok';
        dialog.textContent = '';
        if (opener && opener.focus) opener.focus();
        resolve(ok);
      },
      { once: true }
    );
    dialog.returnValue = '';
    dialog.showModal();
    document.getElementById('dialog-confirm').focus();
  });
}
