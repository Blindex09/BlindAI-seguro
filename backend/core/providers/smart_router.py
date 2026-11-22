"""
Roteador Inteligente Baseado em Capacidades, Janela de Contexto e Saúde de Rota
(Inspirado em `models_dev.py`, `route_verdicts.py` e `credential_pool_model_cooldowns.py` do Hermes Agent).

Classifica cada modelo por suas capacidades reais ('text', 'vision', 'tools', 'reasoning', 'long_context'),
tamanho exato de janela de contexto ('context_window'), e roteia automaticamente a interação para o
modelo mais potente disponível para a tarefa, mantendo memória temporária (cooldown) de rotas que falharam.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("blind.router")

# Registro central de modelos, capacidades reais e janela de contexto (em tokens)
MODEL_CAPABILITY_REGISTRY: List[Dict[str, Any]] = [
    # Ollama Cloud (Modelos de ponta para código, agentes MCP e visão)
    {"provider": "ollama_cloud", "model": "kimi-k2.7-code", "capabilities": {"text", "vision", "tools", "reasoning", "long_context"}, "context_window": 256000, "priority": 8},
    {"provider": "ollama_cloud", "model": "deepseek-v4.1-flash", "capabilities": {"text", "tools", "reasoning", "long_context"}, "context_window": 128000, "priority": 10},
    {"provider": "ollama_cloud", "model": "glm-5:cloud", "capabilities": {"text", "tools", "reasoning"}, "context_window": 128000, "priority": 14},
    # OpenAI
    {"provider": "openai", "model": "gpt-4o", "capabilities": {"text", "vision", "tools", "reasoning", "long_context"}, "context_window": 128000, "priority": 20},
    {"provider": "openai", "model": "gpt-4o-mini", "capabilities": {"text", "vision", "tools"}, "context_window": 128000, "priority": 25},
    # Anthropic
    {"provider": "anthropic", "model": "claude-3-5-sonnet-latest", "capabilities": {"text", "vision", "tools", "reasoning", "long_context"}, "context_window": 200000, "priority": 30},
    {"provider": "anthropic", "model": "claude-3-5-haiku-latest", "capabilities": {"text", "tools"}, "context_window": 200000, "priority": 35},
    # Google Gemini (Janela de 1 milhão de tokens para documentos/PDFs extensos)
    {"provider": "gemini", "model": "gemini-2.5-flash", "capabilities": {"text", "vision", "tools", "long_context"}, "context_window": 1000000, "priority": 40},
    {"provider": "gemini", "model": "gemini-2.5-pro", "capabilities": {"text", "vision", "tools", "reasoning", "long_context"}, "context_window": 1000000, "priority": 42},
    # OpenRouter
    {"provider": "openrouter", "model": "anthropic/claude-3.5-sonnet", "capabilities": {"text", "vision", "tools", "reasoning", "long_context"}, "context_window": 200000, "priority": 50},
    {"provider": "openrouter", "model": "deepseek/deepseek-r1", "capabilities": {"text", "reasoning", "long_context"}, "context_window": 128000, "priority": 55},
    # Rota HTTPS Direta Gratuita Sem Chave e Sem Binario Externo (reserva automatica para PCs limpos)
    {"provider": "free_cloud", "model": "openai", "capabilities": {"text", "vision", "tools"}, "context_window": 128000, "priority": 75},
]

_LONG_DOC_HINT = re.compile(r"\b(pdf|fatura\w*|boleto\w*|contrato\w*|relat[oó]rio\w*|documento\w*|resum\w*|inteir[oa]|complet[oa])\b", re.IGNORECASE)
_REASONING_HINT = re.compile(r"\b(analis\w*|compar\w*|planej\w*|calcul\w*|explic\w+ detalhad\w*|passo a passo|por que)\b", re.IGNORECASE)


def infer_required_capability(prompt: str = "", needs_tools: bool = False, has_image: bool = False) -> str:
    """Detecta a capacidade principal exigida pela tarefa."""
    if has_image:
        return "vision"
    if needs_tools:
        return "tools"
    text = prompt or ""
    if len(text) > 4000 or _LONG_DOC_HINT.search(text):
        return "long_context"
    if _REASONING_HINT.search(text):
        return "reasoning"
    return "text"


def get_model_metadata(provider: str, model: str) -> Dict[str, Any]:
    """Retorna os metadados e tamanho de janela de contexto (`context_window`) do modelo."""
    prov = (provider or "").lower()
    mod = (model or "").strip()
    for entry in MODEL_CAPABILITY_REGISTRY:
        if entry["provider"] == prov and entry["model"] == mod:
            return dict(entry)
    for entry in MODEL_CAPABILITY_REGISTRY:
        if entry["provider"] == prov:
            return dict(entry)
    return {"provider": prov, "model": mod, "capabilities": {"text"}, "context_window": 128000, "priority": 99}


def _has_credentials_or_local(prov: str, config_obj: Any = None) -> bool:
    p = (prov or "").lower()
    if p == "ollama_cloud":
        return bool((getattr(config_obj, "ollama_api_key", None) or os.getenv("OLLAMA_API_KEY", "")).strip())
    if p == "openai":
        return bool((getattr(config_obj, "openai_api_key", None) or os.getenv("OPENAI_API_KEY", "")).strip())
    if p == "anthropic":
        return bool((getattr(config_obj, "anthropic_api_key", None) or os.getenv("ANTHROPIC_API_KEY", "")).strip())
    if p == "gemini":
        return bool((getattr(config_obj, "gemini_api_key", None) or os.getenv("GEMINI_API_KEY", "")).strip())
    if p == "openrouter":
        return bool((getattr(config_obj, "openrouter_api_key", None) or os.getenv("OPENROUTER_API_KEY", "")).strip())
    return True


def select_best_model(
    provider: str,
    needs_tools: bool = False,
    requested_model: Optional[str] = None,
    required_capability: Optional[str] = None,
) -> str:
    """Seleciona automaticamente o melhor modelo do provedor para a capacidade exigida."""
    prov = (provider or "auto").lower()
    req = (requested_model or "").strip()
    if req and req.lower() != "auto":
        return req

    cap = required_capability or ("tools" if needs_tools else "text")
    matches = [
        e for e in MODEL_CAPABILITY_REGISTRY
        if e["provider"] == prov and cap in e["capabilities"]
    ]
    if matches:
        matches.sort(key=lambda e: e["priority"])
        return matches[0]["model"]

    any_prov = [e for e in MODEL_CAPABILITY_REGISTRY if e["provider"] == prov]
    if any_prov:
        any_prov.sort(key=lambda e: e["priority"])
        return any_prov[0]["model"]
    return ""


class FallbackRouter:
    """Roteador resiliente por capacidade ('text', 'vision', 'tools', 'reasoning', 'long_context'),
    janela de contexto e memória de saúde de rota (cooldown)."""

    def __init__(self, cooldown_seconds: float = 90.0) -> None:
        self._cooldown_seconds = cooldown_seconds
        self._cooldown_until: Dict[Tuple[str, str], float] = {}

    def mark_route_failed(self, provider: str, model: str) -> None:
        self._cooldown_until[(provider.lower(), model)] = time.monotonic() + self._cooldown_seconds

    def mark_route_healthy(self, provider: str, model: str) -> None:
        self._cooldown_until.pop((provider.lower(), model), None)

    def is_in_cooldown(self, provider: str, model: str) -> bool:
        until = self._cooldown_until.get((provider.lower(), model), 0.0)
        if until and time.monotonic() < until:
            return True
        if until:
            self._cooldown_until.pop((provider.lower(), model), None)
        return False

    def get_models_by_capability(self, capability: str, config_obj: Any = None, only_available: bool = False) -> List[Dict[str, Any]]:
        cap = (capability or "text").lower()
        items = [e for e in MODEL_CAPABILITY_REGISTRY if cap in e["capabilities"]]
        if not items and cap in ("reasoning", "long_context"):
            items = [e for e in MODEL_CAPABILITY_REGISTRY if "text" in e["capabilities"]]
        if only_available:
            items = [e for e in items if _has_credentials_or_local(e["provider"], config_obj)]
        items.sort(key=lambda e: e["priority"])
        return [
            {
                "provider": e["provider"],
                "model": e["model"],
                "capabilities": sorted(e["capabilities"]),
                "context_window": e.get("context_window", 128000),
                "priority": e["priority"],
            }
            for e in items
        ]

    def list_capability_matrix(self, config_obj: Any = None) -> Dict[str, Any]:
        return {
            "text": self.get_models_by_capability("text", config_obj=config_obj),
            "vision": self.get_models_by_capability("vision", config_obj=config_obj),
            "tools": self.get_models_by_capability("tools", config_obj=config_obj),
            "reasoning": self.get_models_by_capability("reasoning", config_obj=config_obj),
            "long_context": self.get_models_by_capability("long_context", config_obj=config_obj),
        }

    def build_candidate_chain(
        self,
        preferred_provider: str,
        preferred_model: Optional[str] = None,
        needs_tools: bool = False,
        required_capability: Optional[str] = None,
        config_obj: Any = None,
    ) -> List[Dict[str, str]]:
        """Monta a cadeia de fallback filtrando apenas modelos que possuem a capacidade exigida."""
        cap = (required_capability or ("tools" if needs_tools else "text")).lower()
        pref = (preferred_provider or "auto").lower()
        pref_mod = (preferred_model or "").strip()

        capable_entries = sorted(
            [e for e in MODEL_CAPABILITY_REGISTRY if cap in e["capabilities"]],
            key=lambda e: e["priority"],
        )
        if not capable_entries:
            capable_entries = sorted(
                [e for e in MODEL_CAPABILITY_REGISTRY if "text" in e["capabilities"]],
                key=lambda e: e["priority"],
            )

        candidates: List[Dict[str, str]] = []
        seen: Set[tuple] = set()

        # 1. Se o provedor preferido for específico (não 'auto') e possuir modelo capaz, tenta ele primeiro
        if pref != "auto":
            pref_capable = [e for e in capable_entries if e["provider"] == pref]
            if pref_capable:
                chosen_mod = select_best_model(pref, needs_tools=needs_tools, requested_model=pref_mod, required_capability=cap)
                candidates.append({"provider": pref, "model": chosen_mod})
                seen.add((pref, chosen_mod))
            elif pref_mod and pref_mod.lower() != "auto":
                candidates.append({"provider": pref, "model": pref_mod})
                seen.add((pref, pref_mod))

        # 2. Adiciona todos os demais modelos capazes com credencial/motor disponível (priorizando os mais potentes)
        for e in capable_entries:
            c_prov = e["provider"]
            c_mod = e["model"]
            if not _has_credentials_or_local(c_prov, config_obj):
                continue
            key = (c_prov, c_mod)
            if key not in seen:
                candidates.append({"provider": c_prov, "model": c_mod})
                seen.add(key)

        # 3. Se ainda restarem modelos de texto disponíveis, adiciona no fim da cadeia como último recurso
        if cap != "text":
            for e in sorted(MODEL_CAPABILITY_REGISTRY, key=lambda x: x["priority"]):
                c_prov, c_mod = e["provider"], e["model"]
                if not _has_credentials_or_local(c_prov, config_obj):
                    continue
                if (c_prov, c_mod) not in seen:
                    candidates.append({"provider": c_prov, "model": c_mod})
                    seen.add((c_prov, c_mod))

        # 4. Reordena colocando rotas saudáveis antes de rotas em cooldown (mas sem descartar nenhuma se todas falharem)
        healthy = [c for c in candidates if not self.is_in_cooldown(c["provider"], c["model"])]
        cooling = [c for c in candidates if self.is_in_cooldown(c["provider"], c["model"])]
        return healthy + cooling

    async def execute_with_failover(
        self,
        prompt: str,
        preferred_provider: str,
        preferred_model: Optional[str],
        executor_fn: Any,
        needs_tools: bool = False,
        required_capability: Optional[str] = None,
        config_obj: Any = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Roteia automaticamente para o melhor modelo capaz da interação e faz fallback entre eles."""
        cap = (required_capability or infer_required_capability(prompt, needs_tools=needs_tools)).lower()
        chain = self.build_candidate_chain(
            preferred_provider=preferred_provider,
            preferred_model=preferred_model,
            needs_tools=needs_tools,
            required_capability=cap,
            config_obj=config_obj,
        )
        errors: List[str] = []
        pref_norm = (preferred_provider or "").lower()

        for idx, cand in enumerate(chain):
            c_prov = cand["provider"]
            c_mod = cand["model"]
            try:
                logger.info(f"Tentando [{cap}] {c_prov}/{c_mod}")
                res = await executor_fn(c_prov, c_mod, prompt, **kwargs)
                self.mark_route_healthy(c_prov, c_mod)
                is_fallback = idx > 0 or (pref_norm not in ("", "auto") and c_prov != pref_norm)
                return {
                    "provider": c_prov,
                    "model": c_mod,
                    "capability": cap,
                    "context_window": get_model_metadata(c_prov, c_mod).get("context_window", 128000),
                    "result": res,
                    "fallback_used": is_fallback,
                    "routed_from": f"{preferred_provider}/{preferred_model or 'auto'}" if is_fallback else None,
                }
            except Exception as err:
                self.mark_route_failed(c_prov, c_mod)
                logger.warning(f"[{cap}] {c_prov}/{c_mod} falhou ({err}). Indo para o próximo modelo capaz.")
                errors.append(f"{c_prov}/{c_mod}: {err}")

        raise RuntimeError(f"Todos os modelos capazes ({cap}) falharam: {' | '.join(errors)}")


smart_router = FallbackRouter()
