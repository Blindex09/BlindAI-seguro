// Conector WhatsApp do Blind AI (Baileys). Pareamento por CODIGO de 8 caracteres (sem QR Code), pensado para quem nao enxerga.
// Fala so com o Blind em 127.0.0.1, com token. Baseado no fluxo do openbot (requestPairingCode quando o socket fica pronto)
// e no bridge do Hermes (sessao em disco, reconexao automatica, saida quando o processo pai some).
//
// Uso: node bridge.js --session <pasta> --port <porta>     (token em BLIND_WA_TOKEN)
// Rotas: GET /health | GET /status | POST /pair {phone} | POST /logout | GET /messages?limit=20

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import pino from 'pino';
import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  Browsers,
  downloadMediaMessage,
} from '@whiskeysockets/baileys';

const args = process.argv.slice(2);
const arg = (name, def) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : def;
};
const SESSION_DIR = arg('session', path.join(process.cwd(), 'session'));
const PORT = Number(arg('port', '0'));
const TOKEN = process.env.BLIND_WA_TOKEN || '';
const PARENT_PID = Number(process.env.BLIND_WA_PARENT_PID || '0');
const DEBUG_FILE = path.join(SESSION_DIR, '..', 'bridge-debug.log');
// Diagnostico so quando pedido (BLIND_WA_DEBUG=1): o registro tem dados da conta e nao deve ficar gravado por padrao.
const logger = process.env.BLIND_WA_DEBUG === '1'
  ? pino({ level: 'info' }, pino.destination({ dest: DEBUG_FILE, sync: true, mkdir: true }))
  : pino({ level: 'silent' });

// estado visto de fora
const state = { status: 'idle', phone: '', pairingCode: '', error: '', since: Date.now(), registered: false };
const inbox = []; // ultimas mensagens recebidas (so na memoria; texto simples)
const MAX_INBOX = 100;
const MEDIA_DIR = path.join(SESSION_DIR, '..', 'media'); // audios, fotos e videos recebidos (so no computador da pessoa)
const MAX_MEDIA_BYTES = 40 * 1024 * 1024;
const CONTACTS_FILE = path.join(SESSION_DIR, '..', 'contatos.json'); // agenda do WhatsApp da pessoa (so neste computador)
const contacts = new Map(); // id -> { id, name, notify, phone, lid }
let contactsTimer = null;
let contactsSync = null;
try {
  for (const c of JSON.parse(fs.readFileSync(CONTACTS_FILE, 'utf-8'))) contacts.set(c.id, c);
} catch { /* ainda nao ha agenda guardada */ }
function saveContactsSoon() {
  if (contactsTimer) return;
  contactsTimer = setTimeout(() => {
    contactsTimer = null;
    try { fs.writeFileSync(CONTACTS_FILE, JSON.stringify([...contacts.values()])); } catch { /* disco cheio? segue sem guardar */ }
  }, 1500);
}
function noteContact(c) {
  if (!c || !c.id) return;
  const prev = contacts.get(c.id) || { id: c.id };
  const next = { ...prev };
  for (const k of ['name', 'notify', 'lid']) if (c[k]) next[k] = c[k];
  const pn = c.phoneNumber || (String(c.id).endsWith('@s.whatsapp.net') ? c.id : '');
  if (pn) next.phone = String(pn).replace(/\D/g, '');
  contacts.set(c.id, next);
  saveContactsSoon();
}

let sock = null;
let starting = null;
let pairing = null; // { phone, resolve, reject, timer }
let stopping = false;

const digits = (s) => String(s || '').replace(/\D/g, '');
const setStatus = (status, extra = {}) => {
  state.status = status;
  Object.assign(state, extra);
};

async function startSocket() {
  if (starting) return starting;
  starting = (async () => {
    fs.mkdirSync(SESSION_DIR, { recursive: true });
    const { state: auth, saveCreds } = await useMultiFileAuthState(SESSION_DIR);
    const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }));
    state.registered = Boolean(auth.creds.registered);
    const s = makeWASocket({
      version,
      auth,
      logger,
      printQRInTerminal: false,
      browser: Browsers.macOS('Chrome'), // WhatsApp recusa (bad-request) o pedido de codigo com nome de navegador proprio (visto no openbot, nov/2026)
      syncFullHistory: false,
      markOnlineOnConnect: false,
    });
    sock = s;
    s.ev.on('creds.update', saveCreds);
    s.ev.on('contacts.upsert', (list) => list.forEach(noteContact));
    s.ev.on('contacts.update', (list) => list.forEach(noteContact));
    s.ev.on('messaging-history.set', ({ contacts: list }) => (list || []).forEach(noteContact));

    s.ev.on('connection.update', async (u) => {
      const { connection, lastDisconnect, qr } = u;
      // O socket esta pronto para parear: e agora que o codigo pode ser pedido (nao ha QR, so o evento).
      if (qr && pairing && !auth.creds.registered) {
        try {
          const code = await s.requestPairingCode(pairing.phone);
          setStatus('waiting_link', { pairingCode: code, phone: pairing.phone, error: '' });
          const p = pairing;
          clearTimeout(p.timer);
          pairing = null;
          p.resolve(code);
        } catch (e) {
          const p = pairing;
          clearTimeout(p.timer);
          pairing = null;
          setStatus('error', { error: `Nao consegui pedir o codigo: ${e && e.message ? e.message : e}` });
          p.reject(e);
        }
      }
      if (connection === 'open') {
        // Agenda: na 1a vez baixa tudo; nas seguintes so o que mudou desde a ultima (contato novo salvo no celular, nome mudado).
        // Alem disso o WhatsApp avisa na hora (eventos contacts.*) e, por garantia, conferimos de 10 em 10 minutos.
        const sync = (full) => { try { s.resyncAppState(['critical_unblock_low'], full).catch(() => {}); } catch { /* tenta na proxima */ } };
        setTimeout(() => sync(!contacts.size), 5000);
        if (contactsSync) clearInterval(contactsSync);
        contactsSync = setInterval(() => { if (sock === s) sync(false); }, 10 * 60 * 1000);
        contactsSync.unref();
      }
      if (connection === 'open') {
        setStatus('connected', { pairingCode: '', error: '', registered: true, phone: digits(String((s.user && s.user.id) || '').split(/[:@]/)[0]) || state.phone });
      } else if (connection === 'close') {
        const code = lastDisconnect && lastDisconnect.error && lastDisconnect.error.output && lastDisconnect.error.output.statusCode;
        sock = null;
        starting = null;
        if (stopping) return;
        if (code === DisconnectReason.loggedOut) {
          setStatus('logged_out', { registered: false, pairingCode: '', error: 'O WhatsApp foi desconectado pelo celular.' });
          try { fs.rmSync(SESSION_DIR, { recursive: true, force: true }); } catch { /* sem sessao para apagar */ }
          return; // sessao limpa; um novo pareamento reinicia o socket do zero
        }
        // Codigo nao usado a tempo (o WhatsApp encerra a espera, ~2,5 min): descarta as credenciais pela metade (o pedido do
        // codigo ja grava um "eu" nelas e a proxima conexao tentaria entrar como conta existente e falharia) e espera novo pedido.
        if (!auth.creds.registered && code !== 515) {
          try { fs.rmSync(SESSION_DIR, { recursive: true, force: true }); } catch { /* nada a apagar */ }
          setStatus('code_expired', { registered: false, pairingCode: '', error: 'O codigo expirou sem ser digitado. Peca um novo.' });
          return;
        }
        // 515 = reiniciar depois de parear (normal). Qualquer outra queda: reconecta.
        setStatus(state.registered ? 'reconnecting' : 'waiting_link', { error: code ? `Conexao fechada (codigo ${code}).` : '' });
        setTimeout(() => startSocket().catch(() => {}), code === 515 ? 500 : 3000);
      }
    });

    s.ev.on('messages.upsert', async ({ messages, type }) => {
      if (type !== 'notify') return;
      for (const m of messages) {
        if (!m.message) continue;
        // Conversa "voce mesmo" = canal do Blind: aceita o que a pessoa escreve para si e ignora o que o Blind respondeu.
        const proprio = !!m.key.fromMe;
        if (proprio && (!ehConversaPropria(s, m.key.remoteJid) || respostasDoBlind.has(m.key.id))) continue;
        const msg = m.message;
        const text = msg.conversation || (msg.extendedTextMessage && msg.extendedTextMessage.text) || '';
        const kind = msg.audioMessage ? 'audio' : msg.imageMessage ? 'imagem' : msg.videoMessage ? 'video'
          : msg.documentMessage ? 'documento' : msg.stickerMessage ? 'figurinha' : '';
        const media = msg.audioMessage || msg.imageMessage || msg.videoMessage || msg.documentMessage || null;
        noteContact({ id: m.key.remoteJid, notify: m.pushName });
        const entry = {
          id: m.key.id,
          jid: m.key.remoteJid,
          de: digits(m.key.remoteJid),
          nome: m.pushName || '',
          texto: text || (media && media.caption) || '',
          tipo: kind || (text ? 'texto' : Object.keys(msg)[0] || 'outro'),
          proprio,
          quando: new Date((Number(m.messageTimestamp) || Date.now() / 1000) * 1000).toISOString(),
        };
        if (media && kind !== 'figurinha') {
          entry.segundos = Number(media.seconds) || 0;
          entry.arquivo = '';
          const size = Number(media.fileLength) || 0;
          if (size > MAX_MEDIA_BYTES) {
            entry.erro_midia = 'Arquivo grande demais para baixar (' + Math.round(size / 1048576) + ' MB).';
          } else {
            try {
              const buf = await downloadMediaMessage(m, 'buffer', {}, { logger, reuploadRequest: s.updateMediaMessage });
              const ext = kind === 'audio' ? 'ogg' : kind === 'imagem' ? 'jpg' : kind === 'video' ? 'mp4'
                : (path.extname(media.fileName || '') || '.bin').replace('.', '');
              fs.mkdirSync(MEDIA_DIR, { recursive: true });
              entry.arquivo = path.join(MEDIA_DIR, `${String(m.key.id).replace(/[^A-Za-z0-9_-]/g, '')}.${ext}`);
              fs.writeFileSync(entry.arquivo, buf);
            } catch (e) {
              entry.erro_midia = 'Nao consegui baixar o arquivo: ' + (e && e.message ? e.message : e);
            }
          }
        }
        inbox.push(entry);
        while (inbox.length > MAX_INBOX) inbox.shift();
      }
    });
  })();
  try {
    await starting;
  } catch (e) {
    starting = null;
    setStatus('error', { error: `Falha ao iniciar o WhatsApp: ${e && e.message ? e.message : e}` });
    throw e;
  }
  return starting;
}

// ids das mensagens que o proprio Blind enviou (para nao responder a si mesmo na conversa "voce mesmo")
const respostasDoBlind = new Set();
function ehConversaPropria(s, remoteJid) {
  const eu = s && s.user ? s.user : {};
  const base = (j) => String(j || '').split(/[:@]/)[0];
  const alvo = base(remoteJid);
  return !!alvo && (alvo === base(eu.id) || alvo === base(eu.lid));
}

function requestCode(phone) {
  return new Promise((resolve, reject) => {
    if (pairing) return reject(new Error('Ja existe um pareamento em andamento.'));
    const timer = setTimeout(() => {
      pairing = null;
      setStatus('error', { error: 'O WhatsApp nao respondeu a tempo para gerar o codigo.' });
      reject(new Error('O WhatsApp nao respondeu a tempo para gerar o codigo (30 s). Confira a internet e tente de novo.'));
    }, 30000);
    pairing = { phone, resolve, reject, timer };
    setStatus('requesting_code', { phone, error: '' });
    // Se ja existe um socket que passou do ponto do QR, reinicia para receber um novo evento de QR.
    const restart = async () => {
      try { if (sock) sock.end(undefined); } catch { /* ja fechado */ }
      sock = null;
      starting = null;
      await startSocket();
    };
    restart().catch((e) => {
      clearTimeout(timer);
      pairing = null;
      reject(e);
    });
  });
}

// ------------------------------ HTTP local ------------------------------
function send(res, code, body) {
  res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}

function readBody(req) {
  return new Promise((resolve) => {
    let raw = '';
    req.on('data', (c) => { raw += c; if (raw.length > 100000) req.destroy(); });
    req.on('end', () => { try { resolve(raw ? JSON.parse(raw) : {}); } catch { resolve({}); } });
  });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  if (TOKEN && req.headers.authorization !== `Bearer ${TOKEN}`) return send(res, 401, { ok: false, error: 'nao autorizado' });
  try {
    if (req.method === 'GET' && url.pathname === '/health') return send(res, 200, { ok: true, pid: process.pid });
    if (req.method === 'GET' && url.pathname === '/status') {
      return send(res, 200, { ok: true, status: state.status, phone: state.phone, registered: state.registered, error: state.error,
        pairing_code: state.status === 'waiting_link' ? state.pairingCode : '' });
    }
    if (req.method === 'POST' && url.pathname === '/send') {
      const body = await readBody(req);
      const text = String(body.text || '').trim();
      if (!text) return send(res, 400, { ok: false, error: 'A mensagem esta vazia.' });
      if (!sock || state.status !== 'connected') return send(res, 409, { ok: false, error: 'O WhatsApp nao esta conectado agora.' });
      let jid = String(body.jid || '');
      if (!jid) {
        const phone = digits(body.phone);
        if (phone.length < 10) return send(res, 400, { ok: false, error: 'Numero invalido: informe DDI, DDD e numero.' });
        const found = await sock.onWhatsApp(phone).catch(() => null);
        if (!found || !found[0] || !found[0].exists) return send(res, 404, { ok: false, error: 'Esse numero nao tem WhatsApp.' });
        jid = found[0].jid;
      }
      const sent = await sock.sendMessage(jid, { text });
      if (sent && sent.key && sent.key.id) { respostasDoBlind.add(sent.key.id); if (respostasDoBlind.size > 500) respostasDoBlind.delete(respostasDoBlind.values().next().value); }
      return send(res, 200, { ok: true, enviado: true, jid, id: sent && sent.key && sent.key.id });
    }
    if (req.method === 'POST' && url.pathname === '/send_media') {
      // Audio (mensagem de voz) ou arquivo, SO para a conversa "voce mesmo" (canal do Blind).
      const body = await readBody(req);
      if (!sock || state.status !== 'connected') return send(res, 409, { ok: false, error: 'O WhatsApp nao esta conectado agora.' });
      const jid = String(body.jid || '');
      if (!ehConversaPropria(sock, jid)) return send(res, 403, { ok: false, error: 'Midia so pode ir para a conversa da propria pessoa.' });
      const file = String(body.path || '');
      if (!file || !fs.existsSync(file)) return send(res, 400, { ok: false, error: 'Arquivo nao encontrado.' });
      const buf = fs.readFileSync(file);
      const kind = String(body.kind || 'document');
      const content = kind === 'audio'
        ? { audio: buf, mimetype: 'audio/ogg; codecs=opus', ptt: true }
        : { document: buf, fileName: String(body.filename || path.basename(file)), mimetype: String(body.mimetype || 'application/octet-stream'), caption: String(body.caption || '') };
      const sent = await sock.sendMessage(jid, content);
      if (sent && sent.key && sent.key.id) { respostasDoBlind.add(sent.key.id); if (respostasDoBlind.size > 500) respostasDoBlind.delete(respostasDoBlind.values().next().value); }
      return send(res, 200, { ok: true, enviado: true, jid, id: sent && sent.key && sent.key.id });
    }
    if (req.method === 'GET' && url.pathname === '/contacts') {
      const q = String(url.searchParams.get('q') || '');
      const list = [...contacts.values()].filter((c) => c.name || c.notify)
        .map((c) => ({ jid: c.id, nome: c.name || '', nome_publico: c.notify || '', telefone: c.phone || '' }));
      return send(res, 200, { ok: true, total: list.length, q, contatos: list });
    }
    if (req.method === 'GET' && url.pathname === '/messages') {
      const limit = Math.max(1, Math.min(Number(url.searchParams.get('limit') || 20), 100));
      return send(res, 200, { ok: true, total: inbox.length, mensagens: inbox.slice(-limit).reverse() });
    }
    if (req.method === 'POST' && url.pathname === '/pair') {
      const body = await readBody(req);
      const phone = digits(body.phone);
      if (phone.length < 10) return send(res, 400, { ok: false, error: 'Numero invalido: informe DDI, DDD e numero.' });
      if (state.status === 'connected' && state.registered) return send(res, 200, { ok: true, status: 'connected', phone: state.phone });
      const code = await requestCode(phone);
      return send(res, 200, { ok: true, status: 'waiting_link', phone, code });
    }
    if (req.method === 'POST' && url.pathname === '/logout') {
      stopping = true;
      try { if (sock) await sock.logout(); } catch { /* ja desconectado */ }
      try { fs.rmSync(SESSION_DIR, { recursive: true, force: true }); } catch { /* nada a apagar */ }
      setStatus('logged_out', { registered: false, pairingCode: '' });
      send(res, 200, { ok: true });
      setTimeout(() => process.exit(0), 300);
      return;
    }
    return send(res, 404, { ok: false, error: 'rota desconhecida' });
  } catch (e) {
    return send(res, 500, { ok: false, error: e && e.message ? e.message : String(e) });
  }
});

server.listen(PORT, '127.0.0.1', () => {
  const addr = server.address();
  console.log(JSON.stringify({ event: 'listening', port: addr.port }));
  // Se ja ha sessao salva, reconecta sozinho; senao espera o pedido de pareamento.
  if (fs.existsSync(path.join(SESSION_DIR, 'creds.json'))) startSocket().catch(() => {});
  else setStatus('idle');
});

// Sai quando o processo pai (servidor do Blind) some, para nao ficar processo solto.
if (PARENT_PID) {
  setInterval(() => {
    try { process.kill(PARENT_PID, 0); } catch { process.exit(0); }
  }, 5000).unref();
}
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => process.exit(0));
