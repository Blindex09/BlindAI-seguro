'use strict';

// Preferencias do app em userData/settings.json. O atalho global tambem pode vir
// de BLIND_HOTKEY (tem prioridade e nao e gravado em disco). BLIND_HOTKEY="" desativa.

const fs = require('fs');
const path = require('path');

const DEFAULTS = Object.freeze({
  hotkey: 'Control+Alt+L',
  closeToTray: true,
  startHidden: false,
});

function createSettings(userDataDir, env = process.env) {
  const file = path.join(userDataDir, 'settings.json');
  let data = { ...DEFAULTS };

  try {
    const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (parsed && typeof parsed === 'object') {
      if (typeof parsed.hotkey === 'string') data.hotkey = parsed.hotkey;
      if (typeof parsed.closeToTray === 'boolean') data.closeToTray = parsed.closeToTray;
      if (typeof parsed.startHidden === 'boolean') data.startHidden = parsed.startHidden;
    }
  } catch (_) {
    // sem arquivo ou invalido: usa o padrao
  }

  function save() {
    try {
      fs.mkdirSync(userDataDir, { recursive: true });
      const tmp = `${file}.tmp`;
      fs.writeFileSync(tmp, JSON.stringify(data, null, 2), 'utf8');
      fs.renameSync(tmp, file);
    } catch (_) {
      // falha ao gravar nao deve derrubar o app
    }
  }

  return {
    file,
    get() {
      const effective = { ...data };
      if (Object.prototype.hasOwnProperty.call(env, 'BLIND_HOTKEY')) {
        effective.hotkey = env.BLIND_HOTKEY;
      }
      return effective;
    },
    set(patch) {
      data = { ...data, ...patch };
      save();
    },
  };
}

module.exports = { createSettings, DEFAULTS };
