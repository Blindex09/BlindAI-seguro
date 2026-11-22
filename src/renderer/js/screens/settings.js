// Tela: Configuracoes completas do Blind AI (voz, conversa/memoria, acessibilidade, janela, seguranca, canais e diagnostico).

import { h, clear, actionButton, field } from '../lib/dom.js';
import { announce } from '../lib/a11y.js';
import { playBeep } from '../lib/sound.js';
import { listVoices, speak, stopSpeaking } from '../lib/tts.js';
import { askText, confirmDialog } from '../lib/dialog.js';
import * as api from '../lib/api.js';
import * as store from '../lib/store.js';

function normalizeSearch(s) {
  return String(s || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim();
}

function parseMcpJson(res) {
  if (!res || !res.ok || res.is_error) return null;
  try {
    return JSON.parse(res.content || '{}');
  } catch (_) {
    return null;
  }
}

async function callMcp(server, tool, args = {}) {
  if (!window.blind || !window.blind.mcp) return null;
  try {
    const res = await window.blind.mcp.call(server, tool, args);
    return parseMcpJson(res);
  } catch (_) {
    return null;
  }
}

const SHORTCUT_GUIDE = [
  ['Alt+Shift+H ou Esc', 'Voltar à tela inicial'],
  ['Alt+Shift+J', 'Ligar ou pausar Modo Jarvis (voz contínua)'],
  ['Alt+Shift+L', 'Falar comando de voz (ditado)'],
  ['Alt+Shift+C', 'Conversa por texto ou voz'],
  ['Alt+Shift+T', 'Descrever tela atual'],
  ['Alt+Shift+I', 'Descrever arquivo de imagem'],
  ['Alt+Shift+D', 'Ler fatura ou PDF'],
  ['Alt+Shift+E', 'Redigir ou ditar documento'],
  ['Alt+Shift+W', 'WhatsApp e Telegram'],
  ['Alt+Shift+U', 'Conta e Assinatura'],
  ['Alt+Shift+S', 'Configurações'],
  ['Alt+Shift+A', 'Atividades recentes'],
  ['Alt+Shift+M / F', 'Motor de IA / Servidores MCP (Avançado)'],
  ['Ctrl+K', 'Focar barra rápida (falar ou digitar em qualquer tela)'],
  ['Ctrl+1 a Ctrl+9', 'Ir direto para os módulos pela ordem'],
];

export function createSettingsScreen(ctx) {
  // ---------------- Barra de categoria + busca ----------------
  const categorySelect = h(
    'select',
    { id: 'settings-category-select', onChange: () => applyFilters(true) },
    h('option', { value: 'all', text: 'Todas as seções (7 categorias)' }),
    h('option', { value: 'voice', text: '1. Voz, fala e ditado' }),
    h('option', { value: 'chat', text: '2. Conversa, instruções e memória' }),
    h('option', { value: 'a11y', text: '3. Aparência e leitor de tela' }),
    h('option', { value: 'window', text: '4. Janela, inicialização e atalhos' }),
    h('option', { value: 'safety', text: '5. Segurança e vigia de teclado/mouse' }),
    h('option', { value: 'channels', text: '6. Canais (WhatsApp e Telegram)' }),
    h('option', { value: 'system', text: '7. Conta, IA e diagnóstico' })
  );
  const searchInput = h('input', {
    type: 'search',
    id: 'settings-search',
    placeholder: 'Ex.: voz, contraste, atalho, vigia, memória, whatsapp...',
    onInput: () => applyFilters(false),
  });
  const searchStatus = h('p', { id: 'settings-search-status', class: 'hint', role: 'status', 'aria-live': 'polite' });

  // ---------------- 1. Voz, fala e ditado ----------------
  const tts = h('input', { type: 'checkbox', id: 'opt-tts', onChange: (e) => togglePref('tts', e.target.checked, 'Fala das respostas') });
  const voiceSelect = h('select', { id: 'opt-tts-voice', onChange: (e) => setPref('ttsVoice', e.target.value, 'Voz selecionada.') });
  const rateSelect = h(
    'select',
    { id: 'opt-tts-rate', onChange: (e) => setPref('ttsRate', Number(e.target.value), `Velocidade ${e.target.value}x selecionada.`) },
    h('option', { value: '0.75', text: '0.75x (Devagar)' }),
    h('option', { value: '1', text: '1.0x (Normal)' }),
    h('option', { value: '1.25', text: '1.25x (Rápido)' }),
    h('option', { value: '1.5', text: '1.5x (Mais rápido)' }),
    h('option', { value: '1.75', text: '1.75x (Muito rápido)' }),
    h('option', { value: '2', text: '2.0x (Máximo)' })
  );
  const beeps = h('input', { type: 'checkbox', id: 'opt-beeps', onChange: (e) => togglePref('beeps', e.target.checked, 'Bipes de confirmação') });
  const langSelect = h(
    'select',
    { id: 'opt-language', onChange: (e) => setPref('language', e.target.value, 'Idioma do reconhecimento de voz atualizado.') },
    h('option', { value: 'pt', text: 'Português (Brasil)' }),
    h('option', { value: 'en', text: 'Inglês' }),
    h('option', { value: 'es', text: 'Espanhol' }),
    h('option', { value: 'auto', text: 'Detectar automaticamente' })
  );
  const silenceSelect = h(
    'select',
    { id: 'opt-silence-ms', onChange: (e) => setPref('silenceAfterSpeechMs', Number(e.target.value), 'Tempo de pausa do microfone atualizado.') },
    h('option', { value: '1000', text: '1 segundo (Rápido)' }),
    h('option', { value: '1500', text: '1,5 segundos (Padrão)' }),
    h('option', { value: '2500', text: '2,5 segundos (Calmo)' }),
    h('option', { value: '4000', text: '4 segundos (Pausas longas)' })
  );
  const jarvisPref = h('input', { type: 'checkbox', id: 'opt-jarvis', onChange: (e) => togglePref('jarvisMode', e.target.checked, 'Modo Jarvis padrão') });
  const sttStatus = h('p', { id: 'stt-status', class: 'hint', role: 'status', 'aria-live': 'polite' }, 'Consultando o reconhecimento de voz...');
  const prepareBtn = actionButton({
    id: 'btn-stt-prepare',
    label: 'Preparar o reconhecimento de voz',
    hint: 'Baixa o modelo Whisper uma vez, para o ditado responder rápido',
    cls: 'indigo',
    onClick: () => prepareStt(),
  });

  // ---------------- 2. Conversa, instrucoes e memoria ----------------
  const sendShortcutSelect = h(
    'select',
    { id: 'opt-send-shortcut', onChange: (e) => setPref('sendShortcut', e.target.value, 'Atalho de envio atualizado.') },
    h('option', { value: 'enter', text: 'Enter envia (Shift+Enter quebra a linha)' }),
    h('option', { value: 'ctrl-enter', text: 'Ctrl+Enter envia (Enter quebra a linha)' })
  );
  const showAgentSteps = h('input', { type: 'checkbox', id: 'opt-agent-steps', onChange: (e) => togglePref('showAgentSteps', e.target.checked, 'Mostrar ações do computador na conversa') });
  const responseStyleSelect = h(
    'select',
    { id: 'opt-response-style', onChange: (e) => setPref('responseStyle', e.target.value, 'Estilo das respostas atualizado.') },
    h('option', { value: 'curto', text: 'Curto e direto (ideal para ouvir)' }),
    h('option', { value: 'normal', text: 'Equilibrado (padrão)' }),
    h('option', { value: 'detalhado', text: 'Detalhado passo a passo' })
  );
  const customInstructionsInput = h('textarea', {
    id: 'opt-custom-instructions',
    rows: 3,
    placeholder: 'Ex.: Me chame de Maria. Sempre informe valores em reais por extenso.',
  });
  const instructionsStatus = h('p', { id: 'instructions-status', class: 'hint', role: 'status', 'aria-live': 'polite' });

  const memorySummary = h('p', { id: 'memory-summary', class: 'hint' }, 'Carregando memória pessoal...');
  const memoryList = h('ul', { id: 'memory-list', class: 'memory-list', 'aria-label': 'Itens salvos na memória pessoal' });

  // ---------------- 3. Aparencia e leitor de tela ----------------
  const fontSizeSelect = h(
    'select',
    { id: 'opt-fontsize', onChange: (e) => setPref('fontSize', e.target.value || 'normal', 'Tamanho da letra atualizado.') },
    h('option', { value: 'normal', text: 'Padrão (100%)' }),
    h('option', { value: 'large', text: 'Grande (120%)' }),
    h('option', { value: 'xlarge', text: 'Extra grande (140%)' })
  );
  const highContrast = h('input', { type: 'checkbox', id: 'opt-contrast', onChange: (e) => togglePref('highContrast', e.target.checked, 'Alto contraste máximo') });
  const reduceMotion = h('input', { type: 'checkbox', id: 'opt-reduce-motion', onChange: (e) => togglePref('reduceMotion', e.target.checked, 'Reduzir animações') });
  const verboseSr = h('input', { type: 'checkbox', id: 'opt-verbose-sr', onChange: (e) => togglePref('verboseAnnouncements', e.target.checked, 'Anúncios detalhados de fundo') });

  // ---------------- 4. Janela, inicializacao e atalhos ----------------
  const hotkey = h('input', { type: 'text', id: 'opt-hotkey', placeholder: 'Control+Alt+L' });
  const hotkeyStatus = h('p', { class: 'hint', role: 'status', 'aria-live': 'polite' });
  const closeToTray = h('input', { type: 'checkbox', id: 'opt-tray', onChange: () => saveWindowOptions() });
  const startHidden = h('input', { type: 'checkbox', id: 'opt-hidden', onChange: () => saveWindowOptions() });
  const launchAtLogin = h('input', { type: 'checkbox', id: 'opt-launch-login', onChange: () => saveLoginItem() });
  const launchLoginHint = h('p', { id: 'launch-login-hint', class: 'hint' });

  // ---------------- 5. Seguranca e vigia ----------------
  const vigiaStatusText = h('p', { id: 'vigia-status-text', class: 'hint', role: 'status', 'aria-live': 'polite' }, 'Consultando o vigia de teclado e mouse...');
  const vigiaLigado = h('input', { type: 'checkbox', id: 'opt-vigia-ligado', onChange: () => saveVigia({ ligado: vigiaLigado.checked }) });
  const vigiaTeclas = h('input', { type: 'checkbox', id: 'opt-vigia-teclas', onChange: () => saveVigia({ liberar_teclas_presas: vigiaTeclas.checked }) });
  const vigiaA11y = h('input', { type: 'checkbox', id: 'opt-vigia-a11y', onChange: () => saveVigia({ restaurar_recursos_de_acessibilidade: vigiaA11y.checked }) });
  const vigiaInseguras = h('input', { type: 'checkbox', id: 'opt-vigia-inseguras', onChange: () => saveVigia({ encerrar_copias_inseguras: vigiaInseguras.checked }) });
  const vigiaVoz = h('input', { type: 'checkbox', id: 'opt-vigia-voz', onChange: () => saveVigia({ avisar_por_voz: vigiaVoz.checked }) });
  const keyboardHealthResult = h('p', { id: 'keyboard-health-result', class: 'hint', role: 'status', 'aria-live': 'polite' });

  // ---------------- 6. Canais ----------------
  const channelsInfo = h('p', { id: 'settings-channels-info', class: 'hint', role: 'status', 'aria-live': 'polite' }, 'Verificando canais...');
  const canaisAtivo = h('input', { type: 'checkbox', id: 'opt-canais-ativo', onChange: () => saveCanais({ ativo: canaisAtivo.checked }) });
  const canaisVoz = h('input', { type: 'checkbox', id: 'opt-canais-voz', onChange: () => saveCanais({ voz_espelho: canaisVoz.checked }) });
  const canaisCerebro = h(
    'select',
    { id: 'opt-canais-cerebro', onChange: () => saveCanais({ cerebro: canaisCerebro.value }) },
    h('option', { value: 'claude', text: 'Claude (sessão conectada, com reserva do app)' }),
    h('option', { value: 'local', text: 'Modelo configurado no aplicativo' })
  );

  // ---------------- 7. Conta, IA e diagnostico ----------------
  const accountInfo = h('p', { id: 'settings-account-info', class: 'hint' });
  const appInfo = h('p', { id: 'app-info', class: 'hint' });

  // ---------------- Cartoes das 7 secoes ----------------
  const sections = [
    h(
      'div',
      { class: 'card settings-section', 'data-category': 'voice' },
      h('h2', { tabindex: '-1', text: '1. Voz, fala e ditado' }),
      h('div', { class: 'check' }, tts, h('label', { for: 'opt-tts', text: 'Falar as respostas em voz alta (desligado por padrão, para não falar em cima do NVDA/JAWS)' })),
      h('div', { class: 'grid-2' }, field('Voz da fala', voiceSelect, 'Vozes instaladas no sistema para leitura em voz alta.'), field('Velocidade da fala', rateSelect)),
      h(
        'div',
        { class: 'row' },
        actionButton({ id: 'btn-test-voice', label: 'Testar voz agora', cls: 'sky', onClick: testVoice }),
        actionButton({ id: 'btn-stop-voice', label: 'Parar fala', cls: 'plain', onClick: () => { stopSpeaking(); announce('Fala interrompida.', false); } })
      ),
      h('div', { class: 'check' }, beeps, h('label', { for: 'opt-beeps', text: 'Tocar bipes curtos de confirmação ao navegar e executar ações' })),
      h('div', { class: 'row' }, actionButton({ id: 'btn-test-beep', label: 'Testar bipe', cls: 'plain', onClick: () => playBeep(880, 0.14) })),
      h('div', { class: 'grid-2' }, field('Idioma do reconhecimento de voz', langSelect), field('Tempo de pausa para encerrar o microfone', silenceSelect)),
      h('div', { class: 'check' }, jarvisPref, h('label', { for: 'opt-jarvis', text: 'Manter o Modo Jarvis (escuta contínua por voz) ativo após cada resposta falada' })),
      sttStatus,
      h('div', { class: 'row' }, prepareBtn)
    ),
    h(
      'div',
      { class: 'card settings-section', 'data-category': 'chat' },
      h('h2', { tabindex: '-1', text: '2. Conversa, instruções e memória' }),
      h('div', { class: 'grid-2' }, field('Tecla para enviar mensagem', sendShortcutSelect), field('Estilo das respostas da IA', responseStyleSelect)),
      h('div', { class: 'check' }, showAgentSteps, h('label', { for: 'opt-agent-steps', text: 'Mostrar o detalhe das ações executadas no computador em cada resposta' })),
      field('Instruções personalizadas para a IA', customInstructionsInput, 'Aplicadas em todas as conversas (sem necessidade de formatação).'),
      h('div', { class: 'row' }, actionButton({ id: 'btn-save-instructions', label: 'Salvar instruções', cls: 'sky', onClick: saveInstructions })),
      instructionsStatus,
      h('h3', { text: 'Memória pessoal e Cofre' }),
      memorySummary,
      memoryList,
      h(
        'div',
        { class: 'row' },
        actionButton({ id: 'btn-memory-add', label: 'Adicionar preferência à memória', cls: 'green', onClick: addMemoryItem }),
        actionButton({ id: 'btn-memory-refresh', label: 'Atualizar memória', cls: 'plain', onClick: loadMemory })
      )
    ),
    h(
      'div',
      { class: 'card settings-section', 'data-category': 'a11y' },
      h('h2', { tabindex: '-1', text: '3. Aparência e leitor de tela' }),
      field('Tamanho do texto', fontSizeSelect, 'Ajuda pessoas com baixa visão a ler a tela com conforto.'),
      h('div', { class: 'check' }, highContrast, h('label', { for: 'opt-contrast', text: 'Alto contraste máximo (fundo preto, texto branco e foco amarelo)' })),
      h('div', { class: 'check' }, reduceMotion, h('label', { for: 'opt-reduce-motion', text: 'Reduzir animações e movimentos na tela' })),
      h('div', { class: 'check' }, verboseSr, h('label', { for: 'opt-verbose-sr', text: 'Anunciar avisos de segundo plano no leitor de tela (erros e respostas continuam sempre ativos)' }))
    ),
    h(
      'div',
      { class: 'card settings-section', 'data-category': 'window' },
      h('h2', { tabindex: '-1', text: '4. Janela, inicialização e atalhos' }),
      field('Atalho global para mostrar o Blind AI de qualquer programa', hotkey, 'Use o formato do Electron, por exemplo Control+Alt+L. Deixe vazio para desativar.'),
      h('div', { class: 'row' }, actionButton({ id: 'btn-hotkey', label: 'Salvar atalho', cls: 'sky', onClick: () => saveHotkey() })),
      hotkeyStatus,
      h('div', { class: 'check' }, closeToTray, h('label', { for: 'opt-tray', text: 'Ao fechar a janela, manter o Blind AI na bandeja do sistema' })),
      h('div', { class: 'check' }, startHidden, h('label', { for: 'opt-hidden', text: 'Iniciar sem mostrar a janela' })),
      h('div', { class: 'check' }, launchAtLogin, h('label', { for: 'opt-launch-login', text: 'Iniciar automaticamente junto com o sistema' })),
      launchLoginHint,
      h(
        'details',
        { class: 'settings-details' },
        h('summary', { text: 'Ver todos os atalhos de teclado do Blind AI' }),
        h(
          'ul',
          { class: 'shortcut-list' },
          ...SHORTCUT_GUIDE.map(([keys, desc]) =>
            h('li', { class: 'shortcut-row' }, h('span', { text: desc }), h('span', { class: 'kbd-badge', text: keys }))
          )
        )
      )
    ),
    h(
      'div',
      { class: 'card settings-section', 'data-category': 'safety' },
      h('h2', { tabindex: '-1', text: '5. Segurança e vigia de teclado e mouse' }),
      vigiaStatusText,
      h('div', { class: 'check' }, vigiaLigado, h('label', { for: 'opt-vigia-ligado', text: 'Manter o vigia automático ativo em segundo plano' })),
      h('div', { class: 'check' }, vigiaTeclas, h('label', { for: 'opt-vigia-teclas', text: 'Soltar automaticamente teclas Shift, Ctrl, Alt, Win ou botão do mouse presos' })),
      h('div', { class: 'check' }, vigiaA11y, h('label', { for: 'opt-vigia-a11y', text: 'Desligar Teclas de Aderência/Filtragem se ligarem sozinhas durante o uso' })),
      h('div', { class: 'check' }, vigiaInseguras, h('label', { for: 'opt-vigia-inseguras', text: 'Encerrar cópias inseguras do Windows-MCP com controle global ligado' })),
      h('div', { class: 'check' }, vigiaVoz, h('label', { for: 'opt-vigia-voz', text: 'Avisar por voz quando o vigia detectar tecla presa (pode interromper o leitor de tela)' })),
      h('div', { class: 'row' }, actionButton({ id: 'btn-check-keyboard', label: 'Verificar saúde do teclado e mouse agora', cls: 'sky', onClick: checkKeyboardHealth })),
      keyboardHealthResult
    ),
    h(
      'div',
      { class: 'card settings-section', 'data-category': 'channels' },
      h('h2', { tabindex: '-1', text: '6. Canais (WhatsApp e Telegram)' }),
      channelsInfo,
      h('div', { class: 'check' }, canaisAtivo, h('label', { for: 'opt-canais-ativo', text: 'Atender mensagens recebidas pelos Canais do Blind' })),
      h('div', { class: 'check' }, canaisVoz, h('label', { for: 'opt-canais-voz', text: 'Responder em áudio (voz espelho) quando a pessoa mandar áudio' })),
      field('Quem responde nos canais', canaisCerebro),
      h('div', { class: 'row' }, actionButton({ id: 'btn-settings-channels', label: 'Configurar pareamento WhatsApp e Telegram', cls: 'sky', onClick: () => ctx && ctx.nav('channels') }))
    ),
    h(
      'div',
      { class: 'card settings-section', 'data-category': 'system' },
      h('h2', { tabindex: '-1', text: '7. Conta, IA e diagnóstico' }),
      accountInfo,
      appInfo,
      h(
        'div',
        { class: 'row' },
        actionButton({ id: 'btn-settings-account', label: 'Conta e Assinatura', cls: 'green', onClick: () => ctx && ctx.nav('account') }),
        actionButton({ id: 'btn-settings-activity', label: 'Atividades recentes', cls: 'plain', onClick: () => ctx && ctx.nav('activity') }),
        actionButton({ id: 'btn-adv-models', label: 'Motor de IA (Avançado)', cls: 'plain', onClick: () => ctx && ctx.nav('models') }),
        actionButton({ id: 'btn-adv-mcp', label: 'Servidores MCP (Avançado)', cls: 'plain', onClick: () => ctx && ctx.nav('tools') }),
        actionButton({ id: 'btn-logs', label: 'Abrir pasta de registros', cls: 'plain', onClick: () => openLogs() }),
        actionButton({ id: 'btn-reset-settings', label: 'Restaurar configurações padrão', cls: 'plain', onClick: restoreDefaults })
      )
    ),
  ];

  const root = h(
    'section',
    { class: 'screen', id: 'screen-settings', hidden: true, 'aria-labelledby': 'settings-title' },
    h('h1', { id: 'settings-title', tabindex: '-1', text: 'Configurações' }),
    h(
      'div',
      { class: 'card' },
      h(
        'div',
        { class: 'settings-toolbar' },
        field('Ir direto para categoria', categorySelect),
        field('Buscar configuração', searchInput)
      ),
      searchStatus
    ),
    ...sections
  );

  // ---------------- Filtros e helpers ----------------
  function applyFilters(fromCategory) {
    const cat = categorySelect.value || 'all';
    const q = normalizeSearch(searchInput.value);
    let visibleCount = 0;

    sections.forEach((sec) => {
      const secCat = sec.dataset.category;
      const matchesCat = cat === 'all' || secCat === cat;
      const matchesSearch = !q || normalizeSearch(sec.textContent).includes(q);
      const show = q ? matchesSearch : matchesCat;
      sec.hidden = !show;
      if (show) visibleCount += 1;
    });

    if (q) {
      searchStatus.textContent = visibleCount
        ? `${visibleCount} ${visibleCount === 1 ? 'seção encontrada' : 'seções encontradas'} para "${searchInput.value.trim()}".`
        : `Nenhuma configuração encontrada para "${searchInput.value.trim()}".`;
    } else {
      searchStatus.textContent = '';
    }

    if (fromCategory && !q && cat !== 'all') {
      const target = sections.find((s) => s.dataset.category === cat);
      const h2 = target && target.querySelector('h2');
      if (h2) h2.focus();
      announce(`Exibindo ${h2 ? h2.textContent : cat}.`, false);
    }
  }

  function togglePref(key, on, label) {
    store.set({ [key]: Boolean(on) });
    if (key !== 'beeps' || on) playBeep(on ? 880 : 440, 0.1);
    announce(`${label} ${on ? 'ativado' : 'desativado'}.`, true);
  }

  function setPref(key, value, message) {
    store.set({ [key]: value });
    playBeep(770, 0.08);
    if (message) announce(message, false);
  }

  function populateVoices() {
    const current = store.get().ttsVoice || '';
    const voices = listVoices();
    clear(voiceSelect);
    voiceSelect.append(h('option', { value: '', text: 'Voz padrão do sistema (pt-BR)' }));
    voices.forEach((v) => voiceSelect.append(h('option', { value: v.id, text: v.name })));
    voiceSelect.value = voices.some((v) => v.id === current) ? current : '';
  }

  if ('speechSynthesis' in window && typeof window.speechSynthesis.addEventListener === 'function') {
    window.speechSynthesis.addEventListener('voiceschanged', populateVoices);
  }

  function testVoice() {
    const ok = speak('Olá, esta é a voz configurada para o Blind AI.', { force: true });
    if (!ok) announce('Sintetizador de voz do navegador indisponível nesta janela.', true);
  }

  function saveInstructions() {
    store.set({ customInstructions: customInstructionsInput.value.trim() });
    playBeep(880, 0.1);
    instructionsStatus.textContent = 'Instruções personalizadas salvas.';
    announce(instructionsStatus.textContent, true);
  }

  async function loadMemory() {
    memorySummary.textContent = 'Consultando memória pessoal e cofre...';
    const [memData, cofreData] = await Promise.all([
      callMcp('blind-memory', 'memory_recall', { limit: 15 }),
      callMcp('blind-memory', 'cofre_listar', {}),
    ]);
    clear(memoryList);
    if (!memData) {
      memorySummary.textContent = 'Servidor de memória ainda iniciando ou indisponível.';
      return;
    }
    const items = Array.isArray(memData.memories) ? memData.memories : [];
    const cofreTotal = cofreData && typeof cofreData.total === 'number' ? cofreData.total : 0;
    memorySummary.textContent = `${items.length} preferência(s) na memória e ${cofreTotal} item(ns) protegido(s) no cofre.`;
    if (!items.length) {
      memoryList.append(h('li', { class: 'hint', text: 'Nenhuma preferência salva na memória ainda.' }));
      return;
    }
    items.forEach((item) => {
      memoryList.append(
        h(
          'li',
          { class: 'memory-item' },
          h('span', { text: `${item.key}: ${item.content}` }),
          actionButton({
            id: `btn-forget-${String(item.key).replace(/[^a-zA-Z0-9_-]/g, '_')}`,
            label: 'Esquecer',
            cls: 'plain',
            ariaLabel: `Esquecer memória ${item.key}`,
            onClick: () => forgetMemoryItem(item.key),
          })
        )
      );
    });
  }

  async function addMemoryItem() {
    const key = await askText({ title: 'Nova memória', label: 'Nome curto (ex.: tratamento, leitor, horario)', confirmText: 'Avançar' });
    if (!key) return;
    const content = await askText({ title: `Valor para "${key}"`, label: 'O que o Blind AI deve lembrar?', confirmText: 'Salvar na memória' });
    if (!content) return;
    const saved = await callMcp('blind-memory', 'memory_save', { key, content, category: 'preferencia' });
    if (!saved || !saved.ok) {
      announce('Não foi possível salvar na memória (lembre-se de não guardar senhas ou dados sensíveis fora do cofre).', true);
      return;
    }
    playBeep(880, 0.1);
    announce(`Memória ${key} salva.`, true);
    await loadMemory();
  }

  async function forgetMemoryItem(key) {
    const res = await callMcp('blind-memory', 'memory_forget', { key });
    if (res && res.ok) {
      playBeep(440, 0.1);
      announce(`Memória ${key} removida.`, true);
      await loadMemory();
    }
  }

  async function loadVigia() {
    const data = await callMcp('blind-system', 'vigia_status', {});
    if (!data || !data.ok) {
      vigiaStatusText.textContent = 'Vigia de teclado ainda iniciando ou indisponível no momento.';
      return;
    }
    const cfg = data.configuracao || {};
    vigiaLigado.checked = Boolean(cfg.ligado);
    vigiaTeclas.checked = Boolean(cfg.liberar_teclas_presas);
    vigiaA11y.checked = Boolean(cfg.restaurar_recursos_de_acessibilidade);
    vigiaInseguras.checked = Boolean(cfg.encerrar_copias_inseguras);
    vigiaVoz.checked = Boolean(cfg.avisar_por_voz);
    const evCount = Array.isArray(data.eventos_recentes) ? data.eventos_recentes.length : 0;
    vigiaStatusText.textContent = `Vigia ${data.rodando ? 'ativo' : 'parado'}. ${data.verificacoes_feitas || 0} verificações feitas, ${evCount} evento(s) recente(s).`;
  }

  async function saveVigia(patch) {
    const res = await callMcp('blind-system', 'vigia_configurar', patch);
    if (res && res.ok) {
      playBeep(770, 0.08);
      announce('Configuração do vigia salva.', false);
      await loadVigia();
    } else {
      announce('Não consegui atualizar o vigia de teclado agora.', true);
    }
  }

  async function checkKeyboardHealth() {
    keyboardHealthResult.textContent = 'Verificando teclado e mouse...';
    const data = await callMcp('blind-system', 'saude_teclado', {});
    keyboardHealthResult.textContent = data && data.resumo
      ? data.resumo
      : 'Não foi possível consultar a saúde do teclado no momento.';
    announce(keyboardHealthResult.textContent, true);
  }

  async function loadCanais() {
    const res = await api.get('/api/canais');
    if (!res.ok || !res.data) {
      channelsInfo.textContent = 'Gerencie o pareamento do WhatsApp e Telegram na tela de Canais.';
      return;
    }
    const c = res.data;
    const tgCount = Number(c.telegram_donos) || 0;
    const tgText = tgCount > 0 ? `${tgCount} vinculado(s)` : 'não vinculado';
    canaisAtivo.checked = Boolean(c.ativo);
    canaisVoz.checked = c.voz_espelho !== false;
    if (c.cerebro === 'claude' || c.cerebro === 'local') canaisCerebro.value = c.cerebro;
    channelsInfo.textContent = `Canais ${c.ativo ? 'ativos' : 'desativados'}. Telegram: ${tgText}. Cérebro: ${c.cerebro || 'claude'}.`;
  }

  async function saveCanais(patch) {
    const res = await api.post('/api/canais/config', patch);
    if (res.ok && res.data) {
      playBeep(770, 0.08);
      announce('Configuração dos canais salva.', false);
      await loadCanais();
    } else {
      announce(`Não consegui salvar a configuração dos canais: ${api.errorText(res)}`, true);
    }
  }

  async function loadLoginItem() {
    if (!window.blind || !window.blind.settings || !window.blind.settings.getLoginItem) {
      launchAtLogin.disabled = true;
      launchLoginHint.textContent = 'Disponível apenas no aplicativo instalado no Windows ou macOS.';
      return;
    }
    const res = await window.blind.settings.getLoginItem();
    if (!res || !res.supported) {
      launchAtLogin.disabled = true;
      launchLoginHint.textContent = res && res.reason === 'not-packaged'
        ? 'Disponível apenas no aplicativo instalado (.exe); rodando pelo .bat fica desativado.'
        : 'Inicialização automática com o sistema não suportada neste ambiente.';
      return;
    }
    launchAtLogin.disabled = false;
    launchAtLogin.checked = Boolean(res.openAtLogin);
    launchLoginHint.textContent = '';
  }

  async function saveLoginItem() {
    if (!window.blind || !window.blind.settings || !window.blind.settings.setLoginItem) return;
    const res = await window.blind.settings.setLoginItem(launchAtLogin.checked);
    if (!res || !res.ok) {
      launchAtLogin.checked = Boolean(res && res.openAtLogin);
      announce('Não foi possível alterar a inicialização com o sistema.', true);
      return;
    }
    playBeep(770, 0.08);
    announce(res.openAtLogin ? 'Blind AI abrirá junto com o sistema.' : 'Inicialização automática desativada.', false);
  }

  async function loadSettings() {
    const prefs = store.get();
    tts.checked = Boolean(prefs.tts);
    populateVoices();
    rateSelect.value = String(prefs.ttsRate || 1);
    beeps.checked = prefs.beeps !== false;
    langSelect.value = prefs.language || 'pt';
    silenceSelect.value = String(prefs.silenceAfterSpeechMs || 1500);
    jarvisPref.checked = Boolean(prefs.jarvisMode);

    sendShortcutSelect.value = prefs.sendShortcut || 'enter';
    showAgentSteps.checked = prefs.showAgentSteps !== false;
    responseStyleSelect.value = prefs.responseStyle || 'curto';
    customInstructionsInput.value = prefs.customInstructions || '';

    fontSizeSelect.value = prefs.fontSize || 'normal';
    highContrast.checked = Boolean(prefs.highContrast);
    reduceMotion.checked = Boolean(prefs.reduceMotion);
    verboseSr.checked = prefs.verboseAnnouncements !== false;

    accountInfo.textContent = prefs.accountEmail
      ? `Conta conectada: ${prefs.accountEmail} (${prefs.accountPlan || 'Aguardando assinatura'}).`
      : 'Nenhuma conta conectada no momento.';

    if (window.blind && window.blind.settings) {
      const s = await window.blind.settings.get();
      hotkey.value = s.hotkey || '';
      closeToTray.checked = Boolean(s.closeToTray);
      startHidden.checked = Boolean(s.startHidden);
    }
    if (window.blind && window.blind.app) {
      const info = await window.blind.app.info();
      appInfo.textContent = `Blind AI versão ${info.version}, ${info.platform}. Backend: ${info.state}.`;
    }

    const [sttRes] = await Promise.all([
      api.get('/api/stt/status'),
      loadLoginItem(),
      loadCanais(),
      loadMemory(),
      loadVigia(),
    ]);

    if (sttRes.ok && sttRes.data) {
      const d = sttRes.data;
      sttStatus.textContent = d.error
        ? `Reconhecimento de voz com erro: ${d.error}`
        : d.loaded
          ? `Reconhecimento de voz pronto. Modelo ${d.model}, carregado em ${d.load_seconds} segundos.`
          : d.loading
            ? 'Carregando o modelo de voz...'
            : `Reconhecimento de voz ainda não preparado. Modelo ${d.model}. Será baixado no primeiro uso.`;
    } else {
      sttStatus.textContent = `Reconhecimento de voz indisponível: ${api.errorText(sttRes)}`;
    }
    applyFilters(false);
  }

  async function prepareStt() {
    prepareBtn.disabled = true;
    sttStatus.textContent = 'Preparando o modelo de voz. A primeira vez pode levar alguns minutos...';
    announce(sttStatus.textContent, true);
    const res = await api.post('/api/stt/prepare', {}, 900000);
    prepareBtn.disabled = false;
    await loadSettings();
    announce(res.ok ? 'Reconhecimento de voz pronto.' : `Falha ao preparar o reconhecimento de voz: ${api.errorText(res)}`, true);
  }

  async function saveHotkey() {
    if (!window.blind || !window.blind.settings) return;
    const res = await window.blind.settings.setHotkey(hotkey.value.trim());
    hotkeyStatus.textContent = res && res.ok === false ? `Não foi possível usar esse atalho: ${res.error || 'inválido'}` : 'Atalho salvo.';
    announce(hotkeyStatus.textContent, true);
  }

  async function saveWindowOptions() {
    if (!window.blind || !window.blind.settings) return;
    await window.blind.settings.set({ closeToTray: closeToTray.checked, startHidden: startHidden.checked });
    announce('Opção salva.', false);
  }

  async function openLogs() {
    if (window.blind && window.blind.shell) await window.blind.shell.openLogs();
  }

  async function restoreDefaults() {
    const ok = await confirmDialog({
      title: 'Restaurar configurações padrão',
      message: 'Isso restaura voz, aparência, atalho de envio e instruções para o padrão inicial, mantendo sua conta conectada. Deseja continuar?',
      confirmText: 'Restaurar padrão',
    });
    if (!ok) return;
    store.resetPreferences();
    playBeep(660, 0.12);
    await loadSettings();
    announce('Configurações restauradas para o padrão.', true);
  }

  return { id: 'settings', label: 'Configurações', title: 'Configurações', key: 'Alt+Shift+S', root, onShow: loadSettings };
}
