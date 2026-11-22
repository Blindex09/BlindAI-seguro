// Catalogo padrao de provedores e modelos. O backend complementa com os modelos reais disponiveis.

export const PROVIDERS = [
  { id: 'auto', name: 'Piloto Automático (Jarvis — escolhe o melhor modelo por MCP e tarefa)', cloud: false },
  { id: 'ollama_cloud', name: 'Ollama Cloud (nuvem)', cloud: false },
  { id: 'openai', name: 'OpenAI (nuvem, pago)', cloud: true },
  { id: 'gemini', name: 'Google Gemini (nuvem, pago)', cloud: true },
  { id: 'anthropic', name: 'Anthropic Claude (nuvem, pago)', cloud: true },
  { id: 'openrouter', name: 'OpenRouter (nuvem, vários provedores)', cloud: true },
];

export const MODEL_CATALOG = {
  auto: [
    { id: 'auto', name: 'Seleção inteligente automática (precisão máxima por ferramenta MCP)' },
  ],
  ollama_cloud: [
    { id: 'deepseek-v4.1-flash', name: 'DeepSeek V4.1 Flash (ferramentas)' },
    { id: 'kimi-k2.7-code', name: 'Kimi K2.7 Code (ferramentas e visão)' },
  ],
  openai: [
    { id: 'gpt-4o', name: 'GPT-4o (multimodal, rápido e preciso)' },
    { id: 'gpt-4o-mini', name: 'GPT-4o Mini (econômico)' },
    { id: 'o1', name: 'o1 (raciocínio profundo)' },
    { id: 'o3-mini', name: 'o3-mini (raciocínio rápido)' },
  ],
  gemini: [
    { id: 'gemini-2.5-flash', name: 'Gemini 2.5 Flash (muito rápido)' },
    { id: 'gemini-2.5-pro', name: 'Gemini 2.5 Pro (alta capacidade multimodal)' },
    { id: 'gemini-2.0-flash', name: 'Gemini 2.0 Flash' },
  ],
  anthropic: [
    { id: 'claude-3-5-sonnet-latest', name: 'Claude 3.5 Sonnet (alta precisão e código)' },
    { id: 'claude-3-5-haiku-latest', name: 'Claude 3.5 Haiku (ultra rápido)' },
    { id: 'claude-3-opus-latest', name: 'Claude 3 Opus (raciocínio complexo)' },
  ],
  openrouter: [
    { id: 'anthropic/claude-3.5-sonnet', name: 'Claude 3.5 Sonnet (via OpenRouter)' },
    { id: 'deepseek/deepseek-r1', name: 'DeepSeek R1 (via OpenRouter)' },
    { id: 'meta-llama/llama-3.3-70b-instruct', name: 'Llama 3.3 70B (via OpenRouter)' },
    { id: 'google/gemini-2.5-flash', name: 'Gemini 2.5 Flash (via OpenRouter)' },
  ],
};
