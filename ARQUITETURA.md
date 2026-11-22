# Blind AI: arquitetura Electron + MCP

## Visão geral

```
Electron (main)          supervisiona o backend, janela, bandeja, atalho, menu, IPC
  └─ renderer            src/renderer: 9 telas nativas do app (início, conversa, modelo, descrever tela/imagem,
                         ler PDF, redigir, WhatsApp/Telegram, ferramentas MCP, configurações).
                         Fala com o backend SÓ por IPC (window.blind.api); CSP com connect-src 'none'.
Backend Python (FastAPI, server.py)
  ├─ chat + roteador de modelos (smart_router) + sessões (SQLite)
  └─ blind_mcp/          cliente MCP + loop de tool calling nativo
       └─ servidores MCP, cada um em PROCESSO PRÓPRIO (stdio):
            windows          Windows-MCP (CursorTouch): captura, apps, processos, arquivos, PowerShell, Registro e mouse (sem teclado)
            agent-desktop    CLI oficial do agent-desktop + UIA (árvore @ref, janelas, bandeja e ações no desktop)
            blind-speech     fala offline (SAPI)
            blind-stt        ditado: transcrição local com Whisper (faster-whisper), o áudio não sai do PC
            blind-docs       documentos acessíveis (PDF digital e escaneado, formulários PDF), audiodescrição de imagem, escrita assistida e leitura da web
            blind-channels   WhatsApp (pareamento por código) e Telegram
            blind-memory     memória pessoal, busca no histórico de conversas e cofre de segredos
            blind-schedule   tarefas e lembretes falados
            blind-system     diagnóstico somente leitura: diário de ações, saúde do teclado e trabalho não salvo
            blind-commander  Desktop Commander (wonderwhy-er, versão fixa 0.3.3): terminal, arquivos, edição e processos
            blind-a11y       accessibility-agents-mcp 7.1.0 (versão fixa): scanners locais de acessibilidade
            blind            só para o Claude: "blind" → comecar devolve o guia de ferramentas e regras
```

Também existem no código `blind-mail` e `blind-drive` (Gmail e Drive só para o Claude), mas estão **desligados** desde 17/11/2026: o Blind usa os conectores de Gmail e Drive do Claude.

A lista de servidores vive em `backend/mcp.json` (formato `mcpServers`, igual ao do Claude Desktop e do Cursor).
## De onde vem cada servidor (lista conferida com `backend/mcp.json` em 2026-11-22)

| Servidor | Origem | Observação |
|---|---|---|
| `windows` | `C:\repos ia\Windows-MCP` (`BLIND_REPOS_DIR`), via `uv run --directory` | Único que lê um repositório externo, sem cópia. |
| `agent-desktop` | Pacote npm global `agent-desktop` (`npm install -g agent-desktop`) | O servidor só chama o binário. A pasta `C:\repos ia\agent-desktop` **não** é usada. |
| `blind-speech`, `blind-stt`, `blind-docs`, `blind-channels`, `blind-memory`, `blind-schedule`, `blind-system`, `blind` | Código próprio em `backend/blind_mcp/servers/` | Sem dependência dos repos. |
| `blind-commander` | Pacote npm `@wonderwhy-er/desktop-commander`, versão fixa 0.3.3 (MIT), via `npx` | Sem controle de teclado nem de mouse. |
| `blind-a11y` | `accessibility-agents-mcp` 7.1.0 (MIT, versão fixa), instalado em `backend/vendor/a11y-mcp` | As ferramentas `glow_*` ficam desligadas: enviariam arquivos a um serviço externo. Passo a passo em `backend/patches/README.md`. |

Código de terceiros **copiado e adaptado** (não é lido de `C:\repos ia` em tempo de execução):
`blind-docs` (PDF e defesa de URL, do Abacus), `blind-memory` (lembretes, do Abacus) e `blind-channels`
(`backend/core/channels/whatsapp_manager` e `backend/channels/ts_connectors/openbot_whatsapp`, do OpenBot).
`openbot`, `repoabacusai` e `repohermes` em `C:\repos ia` não são servidores MCP do Blind AI.

**Adicionar uma ferramenta nova = adicionar uma entrada nesse arquivo.** Não se edita o código do projeto de terceiros
nem o do Blind AI para isso.

## O que mudou em relação à versão anterior

| Antes | Agora |
|---|---|
| Trechos de Windows-MCP, agent-desktop e outros copiados para dentro do backend | Cada projeto roda como está, em processo separado, com seu próprio ambiente |
| O modelo escrevia `[TOOL: ...]` no texto e o Blind AI interpretava com regex | Tool calling nativo (OpenAI/Anthropic): o modelo devolve chamadas estruturadas, o Blind AI executa no servidor MCP e devolve o resultado real |
| "Pronto, abri o YouTube" sem chamar nada | Se o modelo afirma uma ação sem chamar ferramenta, é corrigido uma vez e depois recebe uma resposta honesta ("nada foi feito") |
| Contexto da tela (UIA) lido em toda mensagem | Só quando o modelo pede (`screen_context`/`snapshot`) |
| Servidor escutando em `0.0.0.0:8765` | Somente `127.0.0.1`, porta por `BLIND_PORT` |
| Rotas `/api/desktop/*` e `/api/windows-mcp/*` | `/api/mcp/servers`, `/api/mcp/tools`, `/api/mcp/servers/{nome}/restart`, `/api/mcp/call` |
| `windows_mcp_bridge.py` (reimplementação em ctypes) | Removido; o Windows-MCP original é usado |
| Uma página HTML única (`backend/ui/index.html`) servida pelo FastAPI | Removida. A interface é o renderer do Electron (`src/renderer`), em módulos, uma tela por arquivo |
| Ditado pelo `webkitSpeechRecognition` (não funciona no Electron) | O app grava o microfone (WAV 16 kHz) e o Whisper local do backend transcreve |
| Código de pareamento do WhatsApp sorteado na própria tela (não era o do backend) | A tela mostra o código gerado e guardado pelo backend |
| `prompt()` para nomear conversas (não existe no Electron) | Diálogo modal acessível (`<dialog>`) |
| Primeira mensagem de uma conversa nova: a bolha do usuário sumia | Corrigido (a sessão é criada antes de exibir a mensagem) |

## Usar os mesmos MCPs no Claude

`python scripts/gerar-mcp-claude.py` lê `backend/mcp.json` e grava `.mcp.json` na raiz (formato do Claude Code, caminhos reais,
`PYTHONPATH` no lugar de `cwd`). `.claude/settings.json` nega no Claude as ferramentas de `modelHiddenTools`. `CLAUDE.md` explica o projeto
ao Claude. O servidor `blind` (`backend/blind_mcp/servers/blind.py`, `"clientOnly": "claude"` no `mcp.json`) é a porta de entrada, no estilo
do `comecar` do Tank: o Claude chama `comecar` quando você diz "blind" e recebe o guia de qual ferramenta usar e o que nunca fazer sem pedido.
O app Electron não inicia esse servidor. Validado: os 7 servidores iniciam fora da pasta do backend e listam 71 ferramentas. Ao abrir o projeto no Claude Code, aprove os
servidores do `.mcp.json` (pedido de uma vez só). Mudou o `mcp.json`? Gere de novo. O app Electron continua lendo só `backend/mcp.json`.
`python scripts/gerar-mcp-claude.py --desktop` também grava no app Claude Desktop (chat): no pacote da Microsoft Store o arquivo fica em
`%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\claude_desktop_config.json` (o script mescla e guarda um `.bak`). Lá o `blind-stt` fica de
fora e `telegram_connect` continua visível (o Desktop não tem `deny` por arquivo): negue-o nas permissões do conector, se quiser.

## Segurança

- `windows`: todas as ferramentas do Windows-MCP (incluindo `PowerShell` e `Registry`) vêm **habilitadas** por padrão em `mcp.json`. Confirmado em teste: `PowerShell` executa comandos e `Registry` lê valores. Para restringir, use `disabledTools`.
- `telegram_connect` recebe o token do bot. Está em `modelHiddenTools`: a interface chama, o modelo nunca vê a ferramenta.
- Telemetria do Windows-MCP desligada (`ANONYMIZED_TELEMETRY=false`).
- O Windows-MCP tem seu próprio portão de consentimento: antes de a IA assumir mouse/teclado, aparece um diálogo com contagem
  regressiva (10 s). Sem resposta, o controle é concedido. Veja `ControlStatus` e o README dele para mudar a política.
- OpenBot e AbacusAI Bot (aplicativos de terceiros) rodam agentes com permissão total; não estão ligados ao Blind AI.

## Custo de tokens e latência

- Conversa comum não envia ferramentas. Só pedidos que parecem ação no computador (`wants_tools`) enviam o catálogo.
- Medição de 16/11/2026, com 7 servidores (hoje são 12 ativos: refaça a contagem antes de citar este número): o catálogo tinha 71 ferramentas, das quais 67 visíveis ao modelo (as 4 de `modelHiddenTools` ficavam escondidas):
  windows 21, agent-desktop 20, blind-docs 9, blind-channels 7 visíveis (8 no total), blind-memory 7, blind-speech 3. Isso é da ordem de
  10 mil tokens (estimativa por caracteres, não contagem do tokenizer; o número antigo de 8,4 mil era de antes do `blind-memory`).
  Reduza com `disabledTools` ou `"enabled": false` por servidor.
- Dois saltos extras por chamada (backend → processo MCP → ferramenta). Medido: os 7 servidores conectam em ~4 s e a chamada de
  ferramenta é pequena perto do tempo do modelo.

## Voz (ditado)

1. Botão "Ouvir voz" (Alt+Shift+L), "Ditar por voz" no chat ou "Ditar texto" no redator. Bipe de início, gravação do microfone.
2. A gravação termina sozinha após 1,5 s de silêncio, em Esc, ou em 60 s. Se ninguém falar em 8 s, avisa e cancela.
3. O WAV vai por IPC para `POST /api/stt/transcribe`, que chama o servidor MCP `blind-stt` (faster-whisper).
4. O texto vira a mensagem do chat (ou entra no documento, no redator).

Modelo padrão `base` (~145 MB, baixado uma vez para `backend/data/models/whisper`); `BLIND_STT_MODEL=small` é mais preciso e mais pesado.
A tela de Configurações mostra o estado e tem o botão "Preparar o reconhecimento de voz" (baixa o modelo antes do primeiro uso).
As ferramentas do `blind-stt` ficam escondidas do modelo de IA (`modelHiddenTools`): áudio nunca é oferecido a um LLM.

## Como rodar

```bash
cd backend && pip install -r requirements.txt     # uma vez
cd .. && npm install && npm start                 # Electron sobe o backend sozinho
```

Variáveis: `BLIND_PORT`, `BLIND_PYTHON`, `BLIND_MCP_CONFIG`, `BLIND_DATA_DIR`, `BLIND_REPOS_DIR` (onde ficam
`Windows-MCP`; padrão `C:\repos ia`). Detalhes do lado Electron em `ELECTRON.md`.

## Verificação real dos servidores (2026-11-16)

Backend real em `127.0.0.1:8765`, chamadas por `POST /api/mcp/call`. Os 7 servidores conectam (71 ferramentas).
Funcionaram: `windows` (ControlStatus, DisplayInventory, Process, Clipboard, Wait, FileSystem, Snapshot, Screenshot, Registry leitura,
PowerShell `echo`), `agent-desktop` (status, list_windows, list_apps, list_tray, screen_context, clipboard, snapshot, find, wait_for),
`blind-speech` (list_voices, speak, stop_speaking), `blind-stt` (stt_status, prepare com o modelo `base`), `blind-memory`
(memory_save/recall/forget, session_search), `blind-schedule` (blindschedule_create/list/snooze/delete), `blind-docs` (read_document, pdf_forms, pdf_merge_split,
web_read, web_search, writer_draft) e `blind-channels` (whatsapp_status, telegram_status, telegram_messages; `telegram_connect` recusa
token inválido e `telegram_send` avisa que não há bot).

**Atualização (2026-11-17): as ferramentas de teclado e mouse do `windows` foram removidas** (`WINDOWS_MCP_EXCLUDE_TOOLS` e
`WINDOWS_MCP_CONTROL=false` em `backend/mcp.json` e em `claude_desktop_config.json`), porque o teclado do usuário travou 3 vezes
(Kernel-Power 41 às 20:48, 23:12 e 23:33 de 16/11) logo após Click/Type/Shortcut. Causa provável, não provada: ganchos globais do modo
"controle" ou tecla modificadora presa. O texto abaixo é o histórico do teste anterior e não vale mais para o `windows`.

**Melhorias de 2026-11-17** (todas testadas em `backend/blind_mcp/tests/test_melhorias.py`): servidor `blind-system` (só leitura:
`acoes_recentes`, `saude_teclado`, `trabalho_nao_salvo`); diário de ações em `backend/data/audit/acoes.jsonl`, gravado pelo wrapper
`servers/_audit.py` (início antes, fim depois; texto digitado só como tamanho; não cobre `windows` nem `blind-commander`, que são de
terceiros); `comecar` devolve `estado` (configurado x faltando; não prova conexão); agent-desktop devolve `mudancas` (diferença das
janelas) e `confirmado` (releitura do campo) e ganhou `descrever_janela`; `telegram_send` exige rascunho + código de confirmação
(uso único, 10 min) e aceita apelidos; lembretes semanal/adiar e correção do lembrete diário atrasado que disparava em sequência;
`read_document(continuar)` e `document_outline`. Limite honesto: lembretes só falam com o servidor `blind-schedule` aberto.

Teste de mouse e teclado (2026-11-16, na Calculadora e na janela Executar, sem tocar em documentos): `windows.Move`, `Click`, `Scroll`, `Shortcut` com
modificador (`win+r`, `esc`), `Type` em campo de texto (leu de volta o valor) e, no `agent-desktop`, `click` por @ref, `press_keys`,
`element_action` (hover) e `window_action` funcionaram. O primeiro uso do Windows-MCP espera o portão de consentimento (~10 s).
Limites que existiam e foram corrigidos (retestados pelas ferramentas MCP reais):
- `Type` e `Shortcut` de uma tecla não digitavam na Calculadora (app UWP). Causa: o `uia.SendUnicodeChar` do Windows-MCP manda só eventos
  Unicode (vk=0), que apps XAML ignoram. Correção: `backend/patches/windows-mcp-vk-keys.patch` (única alteração local no
  Windows-MCP; veja `backend/patches/README.md` para reaplicar após `git pull`). Retestado: `Shortcut 8` mostrou `8` e `Type 7*6=` mostrou `42`.
- `close_app` não fechava apps UWP (o processo visível é `ApplicationFrameHost.exe`). Agora, se o agent-desktop devolve `APP_NOT_FOUND`,
  o bridge acha a janela pelo título ou `app_name`, confere o foco e clica no botão Fechar. Com mais de uma janela igual devolve
  `AMBIGUOUS_WINDOW` e não fecha nada. Alt+F4 não serve: o agent-desktop o bloqueia por segurança. Retestado: a Calculadora fechou.
Ainda vale: `scroll` por `@ref` só funciona em elementos roláveis (num botão recusa, como esperado), e a primeira ação do
Windows-MCP espera o portão de consentimento (~10 s).

Defeitos achados e corrigidos:
- `web_search`: o DuckDuckGo HTML passou a responder 202 com desafio anti-bot e a ferramenta devolvia `ok: true` com 0 resultados.
  Agora o Bing é a fonte principal (link real decodificado de `/ck/a?u=a1...`), o DuckDuckGo é reserva e, se ninguém responder, volta
  `ok: false` com o motivo. Se o Bing mudar o HTML, a busca falha com erro explícito em vez de silêncio.
- `launch_app`/`close_app`: o CLI do agent-desktop leva ~30 s para abrir um app e o limite era 15 s, então a ferramenta dava erro com o app
  já aberto. O limite passou a 60 s (`LAUNCH_TIMEOUT_SEC`) e o `callTimeout` do servidor, de 40 para 75 s.
- `stop_speaking`: usava o objeto COM do SAPI de outra thread e sempre falhava (`status: unknown`). Agora a thread da fala vigia um
  `threading.Event` e interrompe a si mesma.

Não exercitados: `whatsapp_pair` (inicia pareamento real), `telegram_connect` com token válido, `describe_image` e
`channel_describe_image` (enviam imagem a um modelo na nuvem), `transcribe`/`channel_transcribe_audio` (o ditado completo é coberto por
`npm run test:e2e`), `pdf_fill`
(o PDF de teste não tem campos).

## Testes

```bash
cd backend
python -m pytest blind_mcp/tests -q                           # gerenciador, loop de agente, rotas, busca web e fala
set BLIND_INTEGRATION=1 && python -m pytest blind_mcp/tests   # inclui o stack real (somente leitura)
python tests/run_oracles.py --module desktop                  # oráculos, com o backend rodando
cd .. && npm test                                             # Electron: supervisor e cliente da API (sem janela)
cd .. && npm run test:e2e                                     # Electron REAL + backend REAL + ditado com microfone simulado
```

`test:e2e` abre a janela de verdade por alguns minutos. A frase ditada vem de um WAV gerado com a voz pt-BR do Windows e
nenhum comando que mexa no computador é enviado. Cobre as 9 telas (foco no título, nomes acessíveis, alvos de 24 px),
CSP, IPC, 7 servidores MCP conectados, código do WhatsApp, Telegram recusando token inválido e o ditado completo
(gravação, Whisper, mensagem, resposta da IA).

## Limites conhecidos

- `winzapp` (oráculo que envia mensagem real) **não** foi executado.
- Ninguém usou a interface com um leitor de tela real (NVDA/JAWS) nem com microfone físico: o ditado foi testado com um microfone
  simulado por arquivo e a acessibilidade por DOM/ARIA e script. Teste com o seu leitor antes de confiar.
- Alt+Shift+letra pode trocar o idioma do teclado no Windows. Há alternativa: Ctrl+1 a Ctrl+9 abrem as telas.
- Ler fatura: PDF e TXT funcionam; DOCX é recusado com aviso (o backend só extrai PDF).
- Descrever tela/imagem e Ler PDF usam o diálogo real de arquivos e um modelo de visão: não foram exercitados de ponta a ponta
  (a captura de tela mandaria a sua tela para um modelo na nuvem).
- OpenCode (provedor só de texto) não usa ferramentas do computador; pedidos de ação são roteados para modelos com `tools`.
- Os bancos `blind_*.db` do app instalado ficam em `userData/data` e não são migrados do repositório antigo.
