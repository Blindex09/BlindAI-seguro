# Implementação Futura: Blind Cloud (Assinatura Única + Arquitetura Nuvem)

Documento de planejamento para transformar o **Blind AI** em um produto por assinatura mensal única, onde o usuário final não precisa instalar dependências extras, não precisa abrir Claude Desktop ou IDE e não precisa configurar chave de API.

---

## 1. Objetivo do Produto

- **Pagamento único:** o usuário paga apenas uma assinatura mensal do Blind AI (sem precisar pagar outra plataforma de IA por fora).
- **Zero configuração técnica:** sem chave de API, sem terminal, sem Python/Node instalados manualmente pelo usuário.
- **Experiência no app:** o usuário baixa um único instalador (`.exe`), cria sua conta com e-mail, faz a assinatura dentro do próprio app (100% acessível por voz e leitor de tela) e começa a usar.

> **Nota sobre contas pessoais de IA:** Não é viável nem permitido compartilhar uma assinatura pessoal (como Claude Pro/Max ou ChatGPT Plus) por trás dos panos para vários usuários. O modelo sustentável é usar **APIs oficiais no servidor (Gateway)** com controle de cota mensal por assinante.

---

## 2. Divisão da Arquitetura (Nuvem vs. PC do Usuário)

A ideia é mover tudo o que for possível para a nuvem — deixando o app instalado leve — e manter no PC apenas o que depende fisicamente do Windows do usuário, já embutido dentro do instalador único.

### 2.1. O que vai para a Nuvem (Gateway + Serviços)

- **Autenticação e Assinaturas:**
  - Cadastro e login por e-mail/senha (ou código de verificação por e-mail).
  - Integração com gateway de pagamento (Mercado Pago, Asaas, Kiwify ou Stripe) com webhook para ativar/renovar/cancelar a assinatura automaticamente.
- **Gateway de IA (Proxy):**
  - Guarda as chaves oficiais (Anthropic Claude, Google Gemini, etc.) exclusivamente no servidor.
  - Valida o token da sessão do usuário e aplica **cota/teto mensal de uso** por plano.
  - Faz roteamento por custo: modelos rápidos/econômicos (ex.: `claude-3-5-haiku` / `gemini-2.5-flash`) para tarefas simples e modelos mais fortes (ex.: `claude-3-5-sonnet`) para tarefas complexas ou com muitas ferramentas.
- **MCPs e recursos migrados para a nuvem (por usuário):**
  - `blind-memory`: memória pessoal e histórico de conversas persistidos na conta do usuário.
  - `blind-schedule`: agendamentos e lembretes sincronizados na nuvem.
  - `blind-docs`: busca web (`web_search`, `web_read`), análise de PDFs e audiodescrição de imagens enviadas pelo app.
  - **STT (Transcrição de voz):** transcrição na nuvem, eliminando a necessidade de baixar o modelo Whisper (`~145 MB`) no PC do usuário.
  - `blind-channels`: integração de Telegram e ponte de canais.

### 2.2. O que permanece no PC do Usuário (embutido no instalador)

Um servidor na nuvem não consegue enxergar a tela do Windows do usuário nem interagir com janelas e arquivos locais. Por isso, permanecem no app instalado (empacotados juntos, sem instalação separada):

- **Casca Electron (`src/renderer`):** interface acessível, atalhos, bandeja e comunicação por IPC.
- **Ponte local Windows:**
  - `agent-desktop` e `windows`: árvore de acessibilidade (`@ref`), leitura de janelas abertas, captura de tela sob demanda e ações no desktop.
  - `blind-system`: monitoramento de saúde do teclado/mouse e trabalho não salvo.
  - Leitura/escrita de arquivos locais autorizados no PC do usuário.
  - Fala no alto-falante (`blind-speech` SAPI offline ou reprodução de áudio gerado na nuvem).

---

## 3. Fluxo do Usuário Final

1. Baixa e instala o executável único do Blind AI (`electron-builder` / NSIS já previsto em `package.json`).
2. Na primeira abertura, acessa uma tela acessível de **Criar conta / Entrar** com e-mail e senha.
3. Caso não tenha assinatura ativa, o app apresenta a opção **Assinar plano mensal** (checkout acessível e confirmação automática).
4. Com a assinatura ativa, o app libera todas as telas e atalhos (`Alt+Shift+L` para voz, chat, leitura de tela/PDF, redator, canais).
5. A cada pedido, o gateway na nuvem decide se usa uma ferramenta na nuvem ou devolve a chamada (`tool_use`) para a ponte local executar no Windows do usuário e retornar o resultado.

---

## 4. Fases de Implementação Sugeridas

### Fase 1 — Gateway na Nuvem (Backend SaaS)
- Criar serviço web (ex.: FastAPI) com:
  - Cadastro/login (JWT ou token de sessão).
  - Tabela de assinaturas e consumo mensal por usuário (tokens/custo).
  - Webhook do meio de pagamento escolhido.
  - Endpoint proxy compatível com o loop de ferramentas (`tool_use` / `tool_result` da Anthropic e `tool_calls` estilo OpenAI).

### Fase 2 — Login, Assinatura e Provedor `blind_cloud` no App
- Adicionar telas acessíveis de Login, Cadastro e Status da Assinatura em `src/renderer/`.
- Ocultar a tela avançada de chaves de API para o usuário comum.
- Adicionar o provedor `blind_cloud` em `backend/server.py`, enviando o token do assinante no cabeçalho para o gateway na nuvem.
- *(Opcional se usar 100% Claude)* Adicionar tier da Anthropic em `backend/core/vision/smart_vision_router.py` para audiodescrição de imagens também usar a API do Claude.

### Fase 3 — Migração dos MCPs de Nuvem
- Isolar `blind-memory`, `blind-schedule`, `blind-docs` (web/PDF/visão) e STT por `user_id` no servidor na nuvem.
- Manter no cliente apenas o `MCPManager` local enxuto (`agent-desktop`, `windows`, `blind-speech`, `blind-system`) e a ponte de execução remota quando o modelo chamar uma ferramenta local.

### Fase 4 — Empacotamento Único (`npm run dist`)
- Embutir o runtime Python mínimo necessário junto aos recursos do `electron-builder` em `package.json` para que o usuário instale apenas um `.exe` sem depender de Python, Node ou Git pré-instalados no Windows.
