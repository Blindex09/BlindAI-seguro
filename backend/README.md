# Blind AI 🌟
### Assistente Pessoal e Acessibilidade Sensorial para Pessoas com Deficiência Visual

O **Blind AI** é um software de acessibilidade visual projetado para operar prioritariamente através de **áudio, voz contínua e audiodescrição inteligente**. Ele foi construído através da síntese e clonagem direta de módulos de código e testes de três grandes projetos de código aberto:

1. **`repohermes` (Hermes Agent / Nous Research)**: Motor de voz em tempo real, detecção de wake-word exclusiva ("Blind"), síntese de fala local (Piper) e nuvem, transcrição Whisper, visão multimodal e normalização de texto falado.
2. **`openbot` (Nightly Labs)**: Componentes acessíveis do `packages/ui`, integração com WhatsApp, drivers de acessibilidade e arquitetura de queues.
3. **`repoabacusai` (Abacus AI)**: Conectores de mensageria (Telegram e WhatsApp) e barramento RPC.

---

## 🚀 Capacidades Principais

* **Modo 1: Olhos Virtuais e Voz Contínua (Ideia 1)**
  * Ativação exclusiva por palavra-chave ("*Blind*") sem necessidade de usar o teclado.
  * Transcrição de fala de baixa latência e leitura em áudio descritivo de objetos, rótulos e imagens da tela ou câmera.
* **Modo 2: Conversa com o Chat de IA (Texto & Fala)**
  * Botão direto para conversar com a inteligência artificial com balões de mensagem acessíveis (`role="article"` e `aria-label`).
  * As respostas são narradas em voz alta via síntese de voz nativa e região viva ARIA para o leitor de telas.
* **Modo 3: Smart Audio Desk (Ideia 3)**
  * Leitor conversacional de faturas, contas, contratos e PDFs inacessíveis.
  * O usuário conversa diretamente com o documento em vez de ouvir uma leitura linear exaustiva.
  * Normalização fonética inteligente (ex: transforma datas, siglas e moedas R$ em português falado natural).
* **Modo 3: Redação, Ditado e Escrita de Arquivos (Smart Writer)**
  * Permite ao usuário ditar recados, listas, cartas ou notas.
  * O assistente redige, faz a revisão falada em áudio para o usuário aprovar e grava o arquivo de forma segura e atômica no disco.
* **Modo 4: Hub Multicanal no WhatsApp e Telegram (Ideia 4)**
  * **Conexão por Número de Telefone (Pairing Code)**: Pessoas cegas não conseguem mirar a câmera em um QR Code. O Blind AI gera um código de 8 dígitos alfanumérico que é soletrado e falado em voz alta para digitação no WhatsApp sob *"Conectar com número de telefone"*.
  * Permite que a pessoa com deficiência visual use o assistente na rua através do smartphone via WhatsApp ou Telegram.
  * O usuário envia uma foto ou áudio de voz e recebe a audiodescrição falada de volta no próprio aplicativo.
* **Modo 4: Interface Visual e Sonora Acessível (WCAG 2.1 - SC 2.1.4)**
  * Interface em alto contraste, totalmente operável via `Tab` + `Enter` / `Barra de Espaço`.
  * Atalhos seguros via modificadores: `Alt + Shift + L` (Ouvir), `Alt + Shift + O` (Audiodescrição), `Alt + Shift + D` (Documentos), `Alt + Shift + W` (WhatsApp).
  * Sem atalhos de tecla única, evitando 100% de conflito com a navegação de cursor virtual do NVDA e JAWS.
  * Feedback por regiões vivas ARIA (`aria-live="polite"` e `assertive`).

---

## 🧠 Suporte Híbrido a Modelos de IA (Local vs Nuvem)

O software permite alternar de forma transparente entre **modelos gratuitos instalados na máquina** e **modelos em nuvem pagos**:

| Tipo | Provedores Suportados | Vantagens |
| :--- | :--- | :--- |
| **Local / Grátis** | `opencode`, `ollama`, `lmstudio`, `custom` | 100% privado, sem custo por token, funciona offline com Piper TTS e Whisper.cpp. |
| **Nuvem / Pago** | `openai`, `gemini`, `anthropic`, `openrouter` | Maior raciocínio complexo e audiodescrição visual de alta definição. |

Para alternar, basta ajustar o arquivo `.env` ou `config/settings.py`:
```env
# Exemplo 1: Usando IA local do seu computador (OpenCode / Ollama)
BLIND_LLM_PROVIDER=opencode
BLIND_LLM_MODEL=opencode-zen
LOCAL_ENDPOINT_URL=http://127.0.0.1:11434/v1

# Exemplo 2: Usando IA em nuvem (OpenAI ou Gemini)
BLIND_LLM_PROVIDER=gemini
GEMINI_API_KEY=sua_chave_aqui
```

---

## 📁 Estrutura do Projeto Clonado

```
blind-ai/
├── config/
│   └── settings.py          # Gerenciamento de credenciais e provedores
├── core/
│   ├── audio/               # Motor de voz, wake-word ("Blind"), Piper TTS, Whisper STT
│   ├── vision/              # Audiodescrição de imagens e leitura de tela
│   ├── providers/           # Adaptadores de IA Local (OpenCode) e Nuvem (OpenAI/Gemini)
│   ├── docs/                # Smart Audio Desk, normalizador fonético e busca FTS5
│   └── utils/               # Utilitários de sistema clonados do Hermes
├── channels/
│   ├── whatsapp_common.py   # Gateway WhatsApp
│   ├── whatsapp_identity.py # Identificação de usuários em canais
│   └── ts_connectors/       # Conectores TypeScript de mensageria
├── ui/
│   ├── index.html           # Interface web acessível compatível com NVDA e JAWS
│   └── accessible_kit/      # Kit completo de componentes acessíveis do OpenBot
├── tests/                   # Suítes de testes clonadas dos repositórios originais
│   ├── audio/               # Testes de TTS, Whisper, Wake-word e modo de voz
│   ├── vision/              # Testes de visão e escala de imagem
│   ├── providers/           # Testes de integração de modelos
│   ├── docs/                # Testes de normalização e busca
│   └── channels/            # Testes de entrega e mensageria
├── data/
│   └── wakewords/           # Modelos de palavra de ativação ("Blind")
├── .env.example             # Modelo de variáveis de ambiente
├── pytest.ini               # Configuração do executor de testes
└── main.py                  # Ponto de entrada do sistema
```

---

## 🧪 Como Executar os Testes Clonados

Para validar a integridade dos testes clonados:

```bash
pytest
```
Ou para testar uma funcionalidade específica:
```bash
pytest tests/audio/test_tts_text_normalize.py
pytest tests/vision/test_vision_tools.py
```

---

## 📦 Como Mover esta Pasta

Este projeto foi criado de forma **100% autocontida**.
Você pode copiar ou recortar a pasta do projeto e colocá-la em qualquer pasta de sua preferência. Todos os caminhos internos usam referências relativas.
