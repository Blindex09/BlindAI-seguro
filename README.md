# Blind AI

Assistente de voz para pessoas cegas, no Windows. É um app Electron com um backend Python (FastAPI) e vários servidores
MCP. Os mesmos servidores servem o app e o Claude (Desktop/Code).

## Documentação

| Arquivo | Assunto |
|---|---|
| [ARQUITETURA.md](ARQUITETURA.md) | Visão geral, servidores MCP, como rodar e testar |
| [ELECTRON.md](ELECTRON.md) | Processo principal do Electron, supervisor, API, IPC |
| [CLAUDE.md](CLAUDE.md) | Instruções para o Claude trabalhar neste projeto |
| [GOOGLE.md](GOOGLE.md) | Integração com o Google |
| [backend/README.md](backend/README.md) | Backend Python e origem dos módulos de terceiros |
| [backend/patches/README.md](backend/patches/README.md) | Patches para repositórios de terceiros |

## Requisitos

- Windows 10 ou 11
- Node.js e npm
- Python 3.14 (versão usada em `backend/requirements.txt`)

## Instalar e rodar

```powershell
cd backend
pip install -r requirements.txt
cd ..
npm install
npm start
```

No Windows também dá para abrir `Iniciar-Blind-AI.bat`.

Para usar os servidores no Claude, gere o `.mcp.json` a partir de `backend/mcp.json` (a fonte da verdade):

```powershell
python scripts/gerar-mcp-claude.py
```

O `.mcp.json` é gerado e fica fora do Git. Não o edite à mão.

## Servidores MCP

Definidos em `backend/mcp.json`. Cada um roda em seu próprio processo: `blind`, `windows`, `agent-desktop`, `blind-speech`,
`blind-docs`, `blind-stt`, `blind-channels`, `blind-memory`, `blind-schedule`, `blind-system`, `blind-commander` e
`blind-a11y`. `blind-mail` e `blind-drive` existem, mas estão desativados desde 17/11/2026. Detalhes em
[ARQUITETURA.md](ARQUITETURA.md).

## Configuração

Copie `backend/.env.example` para `backend/.env` e preencha só o que for usar. O `.env` nunca vai para o Git.
O backend escuta somente em `127.0.0.1`.

| Variável | Padrão | Para que serve |
|---|---|---|
| `BLIND_PORT` | `8765` | Porta do backend |
| `BLIND_PYTHON` | `python` | Interpretador usado pelo Electron e pelos servidores |
| `BLIND_MCP_CONFIG` | `backend/mcp.json` | Arquivo de servidores MCP |
| `BLIND_DATA_DIR` | `backend/data` | Dados locais (bancos, tokens, cofre) |
| `BLIND_REPOS_DIR` | `C:\repos ia` | Pasta dos repositórios de terceiros usados pelos servidores |
| `BLIND_STT_MODEL` | `base` | Modelo Whisper do ditado (`small` é mais preciso) |
| `BLIND_STT_DEVICE` | `auto` | Dispositivo do ditado |
| `BLIND_STT_COMPUTE` | `int8` | Precisão numérica do ditado |
| `BLIND_DOCS_DIR` | | Pasta de trabalho do redator de documentos |
| `BLIND_DOWNLOAD_DIR` | `~/Downloads/Blind` | Pasta de downloads |
| `BLIND_REMOTE_PORT` | `8770` | Porta do gateway remoto |
| `BLIND_WAKE_WORD_ENABLED` | | Liga a palavra de ativação ("blind") |
| `BLIND_LLM_PROVIDER` / `BLIND_LLM_MODEL` | `auto` | Provedor e modelo de linguagem |
| `BLIND_TTS_PROVIDER` / `BLIND_TTS_VOICE` | `piper` / `pt_BR-faber-medium` | Voz de saída |
| `BLIND_STT_PROVIDER` | `whisper_cpp` | Provedor de ditado |

As chaves de provedores (Ollama, OpenAI, Gemini, Anthropic, OpenRouter), o token do Telegram e as demais opções estão em
`backend/.env.example`. Variáveis só de teste ou internas (`BLIND_E2E`, `BLIND_FAKE_MIC_WAV`, `BLIND_INTEGRATION`,
`BLIND_PASTAS_EXTRAS`, `BLIND_WHATSAPP_BRIDGE_CMD`, `BLIND_WHATSAPP_SIMULADO`, `BLIND_WA_TOKEN`, `BLIND_WA_PARENT_PID`,
`BLIND_STT_DEBUG_DUMP`) estão documentadas apenas no código-fonte.

## Testes

```powershell
cd backend
python -m pytest blind_mcp/tests -q     # backend
cd ..
npm run lint                            # sintaxe dos arquivos JS
npm test                                # Electron: supervisor e cliente da API, sem janela
npm run test:e2e                        # Electron real + backend real (abre a janela)
```

`BLIND_INTEGRATION=1` inclui os testes do stack real. Limites conhecidos estão em [ARQUITETURA.md](ARQUITETURA.md): o app
ainda não foi validado por completo com leitor de tela real nem com microfone físico.

## O que não vai para o Git

`.env`, bancos (`*.db`), `backend/data/` (tokens e cofre), `.mcp.json` gerado, logs, caches e o binário de terceiros
`backend/bin/opencode-cli.exe` (253 MB). Veja `.gitignore`.

## Código de terceiros

Este repositório inclui código de terceiros adaptado ou copiado: módulos `hermes_*` (Nous Research), plugins, o conector de
WhatsApp baseado em Baileys, peças do Abacus e patches para o Windows-MCP. As licenças originais ficam junto de cada
componente (por exemplo Baileys, hermes-achievements e security-guidance). O projeto em si ainda não define licença.
