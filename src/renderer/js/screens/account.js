// Tela: Conta e Assinatura (Entrar na conta, Criar conta e gerenciar plano Blind Cloud).

import { h, actionButton, field } from '../lib/dom.js';
import { announce } from '../lib/a11y.js';
import { playBeep } from '../lib/sound.js';
import * as store from '../lib/store.js';

export function createAccountScreen(ctx) {
  let mode = 'login'; // 'login' | 'register'

  const tabLogin = h('button', {
    type: 'button',
    id: 'tab-account-login',
    role: 'tab',
    class: 'tab-btn',
    'aria-selected': 'true',
    onClick: () => setMode('login'),
    text: 'Entrar na conta',
  });
  const tabRegister = h('button', {
    type: 'button',
    id: 'tab-account-register',
    role: 'tab',
    class: 'tab-btn',
    'aria-selected': 'false',
    onClick: () => setMode('register'),
    text: 'Criar conta',
  });

  const nameInput = h('input', { type: 'text', id: 'acc-name', autocomplete: 'name', placeholder: 'Seu nome' });
  const nameField = field('Nome completo', nameInput);
  const emailInput = h('input', { type: 'email', id: 'acc-email', autocomplete: 'email', placeholder: 'voce@exemplo.com' });
  const passInput = h('input', { type: 'password', id: 'acc-pass', autocomplete: 'current-password', placeholder: 'Mínimo 6 caracteres' });
  const passConfirmInput = h('input', { type: 'password', id: 'acc-pass-confirm', autocomplete: 'new-password', placeholder: 'Repita a senha' });
  const passConfirmField = field('Confirmar senha', passConfirmInput);

  const feedback = h('p', { id: 'acc-feedback', class: 'hint', role: 'status', 'aria-live': 'polite' });
  const submitBtn = actionButton({
    id: 'btn-acc-submit',
    label: 'Entrar',
    cls: 'green',
    onClick: submitForm,
  });

  const authCard = h(
    'div',
    { class: 'card', id: 'acc-auth-card' },
    h('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Opções de conta' }, tabLogin, tabRegister),
    nameField,
    field('E-mail', emailInput, 'Seu e-mail único para acessar o Blind e sua assinatura.'),
    field('Senha', passInput),
    passConfirmField,
    h('div', { class: 'row' }, submitBtn),
    feedback
  );

  const profileSummary = h('p', { id: 'acc-profile-summary' });
  const planStatus = h('p', { id: 'acc-plan-status', class: 'hint' });
  const profileCard = h(
    'div',
    { class: 'card', id: 'acc-profile-card', hidden: true },
    h('h2', { text: 'Sua conta conectada' }),
    profileSummary,
    planStatus,
    h(
      'div',
      { class: 'row' },
      actionButton({
        id: 'btn-acc-subscribe',
        label: 'Assinar ou gerenciar plano Blind Cloud',
        cls: 'green',
        onClick: toggleSubscription,
      }),
      actionButton({
        id: 'btn-acc-logout',
        label: 'Sair da conta',
        cls: 'plain',
        onClick: logout,
      })
    )
  );

  const root = h(
    'section',
    { class: 'screen', id: 'screen-account', hidden: true, 'aria-labelledby': 'account-title' },
    h('h1', { id: 'account-title', tabindex: '-1', text: 'Conta e Assinatura' }),
    h('p', {
      class: 'lead',
      text: 'Entre com seu e-mail ou crie uma conta para usar sua assinatura mensal no Blind sem configurar chaves de API.',
    }),
    authCard,
    profileCard
  );

  function setMode(nextMode) {
    mode = nextMode;
    const isReg = mode === 'register';
    tabLogin.setAttribute('aria-selected', isReg ? 'false' : 'true');
    tabRegister.setAttribute('aria-selected', isReg ? 'true' : 'false');
    nameField.hidden = !isReg;
    passConfirmField.hidden = !isReg;
    passInput.setAttribute('autocomplete', isReg ? 'new-password' : 'current-password');
    submitBtn.querySelector('span').textContent = isReg ? 'Criar conta' : 'Entrar';
    feedback.textContent = '';
    announce(isReg ? 'Modo criar conta selecionado.' : 'Modo entrar na conta selecionado.', false);
  }

  function submitForm() {
    const email = emailInput.value.trim();
    const pass = passInput.value;
    if (!email || !email.includes('@')) {
      feedback.textContent = 'Informe um e-mail válido.';
      announce(feedback.textContent, true);
      emailInput.focus();
      return;
    }
    if (!pass || pass.length < 6) {
      feedback.textContent = 'A senha deve ter pelo menos 6 caracteres.';
      announce(feedback.textContent, true);
      passInput.focus();
      return;
    }
    if (mode === 'register') {
      const name = nameInput.value.trim();
      if (!name) {
        feedback.textContent = 'Informe seu nome.';
        announce(feedback.textContent, true);
        nameInput.focus();
        return;
      }
      if (pass !== passConfirmInput.value) {
        feedback.textContent = 'As senhas não conferem.';
        announce(feedback.textContent, true);
        passConfirmInput.focus();
        return;
      }
      store.set({ accountEmail: email, accountName: name, accountPlan: 'Aguardando assinatura' });
      playBeep(880, 0.12);
      announce(`Conta criada para ${email}.`, true);
    } else {
      const curName = store.get().accountName || email.split('@')[0];
      store.set({ accountEmail: email, accountName: curName, accountPlan: store.get().accountPlan || 'Aguardando assinatura' });
      playBeep(880, 0.12);
      announce(`Conectado como ${email}.`, true);
    }
    passInput.value = '';
    passConfirmInput.value = '';
    refresh();
  }

  function toggleSubscription() {
    const cur = store.get().accountPlan;
    const next = cur === 'Plano Mensal Blind Cloud (Ativo)' ? 'Aguardando assinatura' : 'Plano Mensal Blind Cloud (Ativo)';
    store.set({ accountPlan: next });
    playBeep(880, 0.12);
    refresh();
    announce(
      next.includes('Ativo')
        ? 'Assinatura Blind Cloud marcada como ativa para testes locais.'
        : 'Assinatura pausada.',
      true
    );
  }

  function logout() {
    store.set({ accountEmail: '', accountName: '', accountPlan: '' });
    playBeep(440, 0.1);
    refresh();
    announce('Você saiu da conta.', true);
  }

  function refresh() {
    const s = store.get();
    const logged = Boolean(s.accountEmail);
    authCard.hidden = logged;
    profileCard.hidden = !logged;
    if (logged) {
      profileSummary.textContent = `Conectado como ${s.accountName ? `${s.accountName} (${s.accountEmail})` : s.accountEmail}.`;
      planStatus.textContent = `Status do plano: ${s.accountPlan || 'Aguardando assinatura'}. (Integração com o servidor de pagamento na nuvem prevista em docs/IMPLEMENTACAO-FUTURA-CLOUD.md).`;
    }
  }

  setMode('login');
  refresh();

  return { id: 'account', label: 'Conta e Assinatura', title: 'Conta e Assinatura', key: 'Alt+Shift+U', root, onShow: refresh };
}
