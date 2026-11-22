"""Configurações centrais do Blind AI.
Gerencia os provedores de IA em nuvem (Ollama Cloud, OpenAI, Gemini, Anthropic, OpenRouter).
"""

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)

@dataclass
class BlindConfig:
    # --- Provedor de Modelo de Linguagem (LLM) ---
    # Opções: "auto", "ollama_cloud", "openai", "gemini", "anthropic", "openrouter", "custom"
    llm_provider: str = os.getenv("BLIND_LLM_PROVIDER", "auto")
    llm_model: str = os.getenv("BLIND_LLM_MODEL", "auto")
    
    local_endpoint_url: str = os.getenv("LOCAL_ENDPOINT_URL", "")
    
    # Chaves para modelos em nuvem
    ollama_api_key: str = os.getenv("OLLAMA_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")

    # --- Síntese de Voz (TTS) ---
    # "piper" (100% local, ultra rápido e offline) ou "openai" / "gemini" (nuvem)
    tts_provider: str = os.getenv("BLIND_TTS_PROVIDER", "piper")
    tts_voice: str = os.getenv("BLIND_TTS_VOICE", "pt_BR-faber-medium")

    # --- Reconhecimento de Fala (STT) ---
    # "whisper_cpp" (100% local offline) ou "openai" (nuvem)
    stt_provider: str = os.getenv("BLIND_STT_PROVIDER", "whisper_cpp")
    whisper_model_path: str = os.getenv("WHISPER_MODEL_PATH", str(BASE_DIR / "data" / "models" / "ggml-base.bin"))

    # --- Wake Word (Palavra de Ativação) ---
    wake_word_enabled: bool = os.getenv("BLIND_WAKE_WORD_ENABLED", "true").lower() == "true"
    wake_word: str = "blind"  # Apenas o comando Blind
    wakewords_dir: str = str(BASE_DIR / "data" / "wakewords")

    # --- Canais de Mensageria (Ideia 4) ---
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    whatsapp_enabled: bool = os.getenv("WHATSAPP_ENABLED", "false").lower() == "true"

    def is_local_llm(self) -> bool:
        return self.llm_provider == "custom"

    def get_api_base(self) -> str:
        if self.is_local_llm():
            return self.local_endpoint_url
        if self.llm_provider == "openai":
            return "https://api.openai.com/v1"
        if self.llm_provider == "openrouter":
            return "https://openrouter.ai/api/v1"
        return ""

config = BlindConfig()
