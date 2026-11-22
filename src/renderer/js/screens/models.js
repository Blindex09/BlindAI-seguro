// Tela: Motor de IA e modelo (provedor, modelo, chave de API e estado dos servicos).

import { h, clear, field } from '../lib/dom.js';
import { announce } from '../lib/a11y.js';
import { playBeep } from '../lib/sound.js';
import * as api from '../lib/api.js';
import * as store from '../lib/store.js';
import { PROVIDERS, MODEL_CATALOG } from '../lib/catalog.js';

export function createModelsScreen(ctx) {
  const providerSelect = h('select', { id: 'ai-provider', onChange: () => onProviderChanged(true) });
  PROVIDERS.forEach((p) => providerSelect.append(h('option', { value: p.id, text: p.name })));
  const modelSelect = h('select', { id: 'ai-model', onChange: onModelChanged });
  const keyInput = h('input', { type: 'password', id: 'api-key', autocomplete: 'off', placeholder: 'Cole a chave aqui (sk-... ou AIza...)', onInput: (e) => store.set({ apiKey: e.target.value.trim() }) });
  const keyField = field('Chave de API (opcional se já estiver configurada no servidor)', keyInput, 'A chave fica só na memória do aplicativo e é enviada apenas ao seu servidor local.');
  const active = h('strong', { id: 'active-model-name' });
  const services = h('ul', { id: 'services-list', 'aria-label': 'Estado dos serviços' });

  const root = h(
    'section',
    { class: 'screen', id: 'screen-models', hidden: true, 'aria-labelledby': 'models-title' },
    h('h1', { id: 'models-title', tabindex: '-1', text: 'Motor de IA e modelo' }),
    h('p', { class: 'lead', text: 'Escolha onde a inteligência artificial roda e qual modelo usar. Se o escolhido falhar, o Blind AI tenta outro automaticamente.' }),
    h(
      'div',
      { class: 'card' },
      h('div', { class: 'grid-2' }, field('1. Provedor de IA', providerSelect), field('2. Modelo', modelSelect)),
      keyField,
      h('p', {}, 'Modelo selecionado: ', active)
    ),
    h('div', { class: 'card' }, h('h2', { text: 'Estado dos serviços' }), services)
  );

  function populate(providerId, list) {
    clear(modelSelect);
    const models = list || MODEL_CATALOG[providerId] || [];
    models.forEach((m) => modelSelect.append(h('option', { value: m.id, text: m.name })));
    const saved = store.get().model;
    if (saved && models.some((m) => m.id === saved)) modelSelect.value = saved;
    syncModel();
  }

  function syncModel() {
    const opt = modelSelect.options[modelSelect.selectedIndex];
    active.textContent = opt ? opt.textContent : 'nenhum';
    store.set({ model: modelSelect.value || '' });
  }

  async function onProviderChanged(userAction) {
    const id = providerSelect.value;
    const provider = PROVIDERS.find((p) => p.id === id);
    store.set({ provider: id, model: userAction ? '' : store.get().model });
    keyField.hidden = !(provider && provider.cloud);
    populate(id);
    if (userAction) {
      playBeep(660, 0.08);
      announce(`Provedor ${provider ? provider.name : id} selecionado.`, true);
    }
    const res = await api.get(`/api/models/${encodeURIComponent(id)}`);
    if (res.ok && res.data && Array.isArray(res.data.models) && res.data.models.length) {
      MODEL_CATALOG[id] = res.data.models;
      if (providerSelect.value === id) populate(id, res.data.models);
    }
  }

  function onModelChanged() {
    syncModel();
    playBeep(770, 0.08);
    announce(`Modelo ${active.textContent} selecionado.`, false);
  }

  async function loadServices() {
    const res = await api.get('/api/status');
    clear(services);
    if (!res.ok || !res.data) {
      services.append(h('li', { text: `Não consegui consultar o servidor: ${api.errorText(res)}` }));
      return;
    }
    services.append(h('li', { text: `Provedor configurado no servidor: ${res.data.configured_provider || 'nenhum'}` }));
  }

  // Estado inicial
  const savedProvider = store.get().provider;
  providerSelect.value = PROVIDERS.some((p) => p.id === savedProvider) ? savedProvider : 'auto';
  keyField.hidden = !(PROVIDERS.find((p) => p.id === providerSelect.value) || {}).cloud;
  populate(providerSelect.value);
  onProviderChanged(false);

  return { id: 'models', label: 'Motor de IA (Avançado)', title: 'Motor de IA (Avançado)', key: 'Alt+Shift+M', advanced: true, root, onShow: loadServices };
}
