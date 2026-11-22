'use strict';

(function () {
  const reason = document.getElementById('reason');
  const logdir = document.getElementById('logdir');
  const output = document.getElementById('output');
  const outputWrap = document.getElementById('output-wrap');
  const feedback = document.getElementById('feedback');
  const retry = document.getElementById('retry');

  function render(info) {
    if (!info) return;
    if (info.error) reason.textContent = info.error;
    if (info.logDir) logdir.textContent = info.logDir;
    if (info.output) {
      output.textContent = info.output;
      outputWrap.hidden = false;
    }
  }

  if (window.blind && window.blind.app) {
    window.blind.app.info().then(render).catch(() => {});
    window.blind.app.onBackendState((s) => {
      if (s && s.state === 'starting') feedback.textContent = 'Iniciando novamente...';
    });
  }

  retry.addEventListener('click', () => {
    retry.disabled = true;
    feedback.textContent = 'Tentando iniciar o serviço novamente...';
    window.blind.app.retry().catch(() => {
      retry.disabled = false;
      feedback.textContent = 'Não foi possível tentar novamente.';
    });
  });

  document.getElementById('logs').addEventListener('click', () => {
    window.blind.shell.openLogs();
  });

  document.getElementById('title').focus();
})();
