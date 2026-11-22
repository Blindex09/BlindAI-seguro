'use strict';

(function () {
  const status = document.getElementById('status');
  const detail = document.getElementById('detail');
  let slowNotified = false;

  function render(s) {
    if (!s) return;
    if (s.state === 'starting') {
      status.textContent = 'Aguarde, iniciando o serviço local.';
    } else if (s.state === 'restarting') {
      status.textContent = `O serviço caiu e está sendo reiniciado (tentativa ${s.attempt}).`;
    } else if (s.state === 'ready') {
      status.textContent = 'Serviço pronto. Abrindo a interface.';
    }
  }

  if (window.blind && window.blind.app) {
    window.blind.app.info().then(render).catch(() => {});
    window.blind.app.onBackendState(render);
  }

  setTimeout(() => {
    if (slowNotified) return;
    slowNotified = true;
    detail.textContent = 'Está demorando mais que o normal. Se continuar, uma mensagem de erro será exibida.';
    detail.setAttribute('aria-live', 'polite');
  }, 12000);

  document.getElementById('title').focus();
})();
