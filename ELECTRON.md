# Blind AI - lado Electron (processo principal)

## Arquitetura

```
Electron (main.js)
 ├─ src/supervisor.js   inicia/vigia o backend Python (server.py): porta livre, health check, reinício com backoff
 ├─ src/api.js          cliente HTTP do backend (proxy api.request + rotas /api/mcp/*)
 ├─ src/logger.js       logs em userData/logs (main.log, backend.log; rotação em 5 MB)
 ├─ src/settings.js     userData/settings.json (atalho global, fechar para a bandeja, iniciar oculto)
 ├─ src/pages/          telas de carregamento e de erro (acessíveis, com CSP)
 ├─ src/renderer/       a interface (escrita pelo coordenador). Carregada por file:// quando o backend fica pronto
 ├─ preload.js          window.blind (contextBridge) → ipcRenderer.invoke
 └─ janela (sandbox, contextIsolation, sem nodeIntegration)
```

- O backend **não serve mais a UI**. O renderer só fala com o backend por IPC (`window.blind.api.request`),
  nunca por `fetch`. A porta é resolvida a cada chamada, então reiniciar o backend ou trocar de porta
  não exige recarregar a janela.
- Fluxo da janela: `loading.html` → (backend pronto) `src/renderer/index.html`; falha → `error.html`; "Tentar novamente" volta ao carregamento.
- URLs confiáveis (`isAllowedUrl`): somente `file:` dentro de `src/renderer/` e `src/pages/`. Nenhuma origem http é confiável.
  Navegação para fora é bloqueada; links http/https/mailto abrem no navegador padrão. O IPC só aceita o `webContents` da janela principal em página confiável.
- **CSP**: o main não injeta cabeçalho (respostas `file://` não passam por `onHeadersReceived` de forma confiável);
  o renderer deve trazer o `<meta http-equiv="Content-Security-Policy">`, sem `connect-src` para o backend.
  As páginas internas (`src/pages`) já têm CSP.
- Fechar a janela **oculta para a bandeja** (padrão, `closeToTray`). Sair: bandeja, menu Blind AI > Sair ou Ctrl+Q.
  Ao sair, o backend e a árvore de processos são encerrados (`taskkill /T /F`).
- Atalho global (padrão `Control+Alt+L`) mostra e foca a janela. Ctrl+Alt equivale a AltGr em alguns layouts: é configurável.

## Contrato `window.blind` (preload.js)

```ts
blind.platform: string                                   // process.platform
blind.version: string                                    // versão do app
blind.backendUrl(): Promise<string>                      // "http://127.0.0.1:<porta>" ou "" se não pronto

blind.api.request(opts: { method?: 'GET'|'POST'|'PUT'|'PATCH'|'DELETE', path: string, body?: any, timeoutMs?: number })
  : Promise<{ ok: boolean, status: number, data: any, error?: string }>
  // path deve começar com /api/ ou /v1/ (sem "..", "//", espaços ou "\"); método padrão GET; timeoutMs padrão 120000 (limite 1000..600000).
  // body é enviado como JSON. data = JSON parseado, ou o texto se a resposta não for JSON, ou null se vazia.
  // Falha de rede/validação/timeout: { ok:false, status:0, data:null, error }. HTTP não-2xx: { ok:false, status, data, error:'HTTP <status>' }.
  // Sem streaming: a resposta chega inteira.

blind.files.pick(opts: { kind: 'image'|'document' })
  : Promise<{ canceled: true }
          | { canceled: false, name: string, mime: string, size: number, dataUrl: string }
          | { canceled: false, error: string }>
  // image: png, jpg, jpeg, webp, gif. document: pdf, txt, docx. Máx. 25 MB.
  // Erros: 'arquivo grande demais', 'tipo de arquivo não permitido', 'tipo invalido: use "image" ou "document"'.

blind.screen.capture(): Promise<{ ok: true, dataUrl: string } | { ok: false, error: string }>
  // PNG da tela principal inteira (resolução física), sem diálogo.

blind.shortcuts.onTrigger(cb: (id: string) => void): () => void   // retorna unsubscribe
  // ids: listen, chat, screen, image, docs, writer, channels, tools, models, home, settings, activity
  // Aceleradores locais do menu (só com a janela em foco): Alt+Shift + L C T I D E W F M H S A, respectivamente (A = Atividades).
  // Só são enviados enquanto o renderer está carregado (não durante loading/erro).

blind.settings.get(): Promise<{ hotkey: string, closeToTray: boolean, startHidden: boolean }>
blind.settings.set(patch: { closeToTray?: boolean, startHidden?: boolean }): Promise<{ hotkey, closeToTray, startHidden }>   // ignora outras chaves
blind.settings.setHotkey(accelerator: string): Promise<{ ok: boolean, error?: string }>   // "" desativa

blind.app.info(): Promise<{ version, platform, logDir, state, attempt, error, output }>
blind.app.retry(): Promise<{ ok: true }>
blind.app.onBackendState(cb: (s: { state: 'starting'|'ready'|'restarting'|'failed'|'stopped', attempt, error, output }) => void): () => void

blind.mcp.servers(): Promise<{ available: boolean, servers: { name, status, tool_count, error|null }[], error? }>
blind.mcp.tools(): Promise<{ available: boolean, tools: { server, name, description }[], error? }>
blind.mcp.restart(name: string): Promise<{ ok: boolean, error? }>
blind.mcp.call(server: string, tool: string, args?: object): Promise<{ ok, content, is_error, error? }>

blind.shell.openLogs(): Promise<{ ok: boolean, error? }>
blind.window.{ minimize, toggleMaximize, hide, show, isMaximized }(): Promise<...>
```

Permissões da sessão: **somente** microfone (`media`, só áudio) e **somente** para `file://` do app. Câmera, notificações, clipboard,
tela cheia, `getDisplayMedia` e qualquer origem http são negados (captura de tela e arquivos passam pelo IPC acima).
Ações Alt+Shift do menu existem também como itens do menu "Atalhos" (barra oculta; Alt a mostra).

## Rodar

```bash
npm install
npm start                # janela normal
npm run dev              # com DevTools
npm run lint             # node --check em tudo
npm test                 # supervisor + API (sem Electron)
npm run test:electron    # + Electron real contra backend falso
node scripts/smoke.js --packaged   # idem contra dist/win-unpacked (depois de npm run pack)
npm run pack             # dist/win-unpacked (npm run dist = instalador NSIS, não testado)
```

Requer Python no PATH (ou `BLIND_PYTHON`); ele **não** vai dentro do pacote.

## Variáveis de ambiente

| Variável | Efeito |
|---|---|
| `BLIND_PYTHON` | executável do Python (padrão `python`) |
| `BLIND_BACKEND_DIR` | pasta do backend (padrão `./backend`; empacotado: `resources/backend`) |
| `BLIND_BACKEND_SCRIPT` | script de entrada (padrão `server.py`) |
| `BLIND_PORT` | porta preferida (padrão 8765). Se ocupada, o supervisor escolhe outra e exporta `BLIND_PORT` ao backend |
| `BLIND_HEALTH_TIMEOUT_MS` | espera pelo `GET /api/status` (padrão 30000) |
| `BLIND_MCP_CONFIG` | repassado ao backend; se não definido e `backend/mcp.json` existe, o main o define |
| `BLIND_DATA_DIR` | repassado ao backend; **empacotado** o main define `userData/data` se não houver valor |
| `BLIND_HOTKEY` | atalho global (prioridade sobre `settings.json`; vazio desativa) |
| `BLIND_DEV=1` | igual a `--dev` |

Só no modo de teste (`BLIND_SMOKE=1`): `BLIND_SMOKE_OUT`, `BLIND_SMOKE_USERDATA`, `BLIND_SMOKE_TIMEOUT_MS` e
`BLIND_TEST_PICK_FILE` (lista de caminhos separada por `|`, uma por chamada de `files.pick`; esgotada = cancelado; o diálogo real nunca abre no smoke).

Logs: `%APPDATA%\blind-ai\logs\` (`main.log`, `backend.log`).

## Supervisor do backend

- Porta: tenta `BLIND_PORT`/8765; confere conexão e bind em `127.0.0.1` e `0.0.0.0`.
- Pronto = `GET /api/status` 2xx dentro do timeout. Falha na subida (saiu, timeout, comando inexistente) **não** é repetida:
  tela de erro com as últimas linhas da saída, caminho dos logs e "Tentar novamente".
- Depois de pronto, se cair: reinicia com backoff 1 s, 2 s, 4 s, no máximo 3 vezes (contador zera após 60 s estável); esgotado → tela de erro.
- Se `src/renderer/index.html` não existir quando o backend ficar pronto, mostra a tela de erro "Interface não encontrada".

## Verificado de fato (Windows 11, Node 24, Electron 33.4.11)

`npm run test:electron` (19/19) e `--packaged` contra `dist/win-unpacked/Blind AI.exe` (19/19), com o **Electron real**
(janela oculta, userData temporário) e `scripts/fixtures/fake-backend.js`:
- janela carrega `file:///.../src/renderer/index.html` (dentro do asar, no pacote);
- `api.request`: GET/POST JSON, resposta não-JSON como texto, 404 com `data`, rejeição de `/etc/passwd`, `..`, `//`, método TRACE, sem argumentos, timeout de 1 s;
- `mcp.*`, `settings.get/set` (ignora chaves desconhecidas e `hotkey`), `backendUrl`;
- `files.pick` com o stub: PNG, TXT, arquivo de 26 MB (`arquivo grande demais`), extensão errada, cancelado, `kind` inválido;
- `screen.capture`: PNG real (assinatura e dimensões ≥ 640×480 lidas do cabeçalho);
- permissões: microfone `granted` no `file://`, câmera `denied`, página http: `permissions.query` = `denied` e `getUserMedia` = `NotAllowedError`;
- `shortcuts.onTrigger`: os 11 itens de menu disparados por código chegam na ordem certa, aceleradores `Alt+Shift+<letra>` conferidos, nada chega após o unsubscribe;
- backend sem `/api/mcp/*` (404) e backend que falha ao subir (tela de erro com saída e botão Tentar novamente);
- supervisor e cliente da API: 16 testes sem Electron (portas, queda e recuperação, reinícios esgotados, stop() mata a árvore etc.).

## Não verificado

- Teclas físicas dos aceleradores (os itens de menu foram disparados por código; o Windows pode usar Alt+Shift para trocar de layout de teclado).
- Diálogo real de `files.pick` (só o stub), microfone real (`getUserMedia` no `file://` não foi chamado para não ligar o microfone; só `permissions.query`).
- Bandeja, atalho global Ctrl+Alt+L, fechar-para-bandeja, instância única, controles de janela (o smoke desliga os três primeiros).
- Aparência e leitor de tela real; instalador NSIS; o renderer real (só o placeholder de `src/renderer/index.html` foi carregado);
  o backend Python real sem a rota `/` (o smoke usa o backend falso).
- `screen.capture` em máquina com vários monitores/DPI diferentes (testado em uma tela).

## Pendências / atenção

- `src/renderer/index.html` neste momento é um **placeholder** criado pelo lado Electron (a pasta não existia); o renderer real o substitui.
- Reconhecimento de voz: `webkitSpeechRecognition` do navegador falha no Electron (sem chaves do Google); ditado precisa de gravação (`getUserMedia`) + STT no backend.
- Com `BLIND_DATA_DIR` do app empacotado em `userData/data`, os `blind_*.db` da pasta do backend não são migrados.
- `ElectronBuilder`: `signAndEditExecutable:false` (o `winCodeSign` exige privilégio de symlink); ícone gerado em memória.
- `api.request` não faz streaming; `FormData`/binário não são suportados (use `files.pick` + `body` com a data URL).
