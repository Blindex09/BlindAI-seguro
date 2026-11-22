"""
Oráculo da Capacidade: Provedores de IA e Catálogo de Modelos
Local: tests/providers/oracle_providers.py
Valida:
1. Status e descoberta de motores locais e nuvem (/api/status).
2. Catálogo completo dos 5 provedores (OpenCode, Ollama, LM Studio, OpenAI, Gemini).
3. Capacidade de resposta dos modelos locais gratuitos.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oracle_base import log, request_json


def run_providers_oracle():
    log("ORACULO-PROVEDORES", "1. Validando saúde do backend e provedor ativo (/api/status)...")
    res = request_json("/api/status")
    assert res.get("status") == "ready", f"Status inválido: {res}"
    assert "configured_provider" in res, "Campo 'configured_provider' ausente"
    log("ORACULO-PROVEDORES", f"   OK -> Provedor: {res.get('configured_provider')} | Modelo: {res.get('configured_model')}")

    log("ORACULO-PROVEDORES", "2. Validando catálogo e resposta dos modelos...")
    providers = ["opencode", "ollama", "lmstudio", "openai", "gemini", "anthropic", "openrouter"]
    for prov in providers:
        m_res = request_json(f"/api/models/{prov}")
        models = m_res.get("models", [])
        assert len(models) > 0, f"Catálogo vazio para o provedor {prov}"
        log("ORACULO-PROVEDORES", f"   OK -> Provedor '{prov}': {len(models)} modelos mapeados.")

    log("ORACULO-PROVEDORES", "3. Validando inferência real no /api/chat (apenas provider=opencode, modelo automático)...")
    chat_res = request_json(
        "/api/chat",
        method="POST",
        data={"message": "Responda apenas com a palavra: ATIVO", "provider": "opencode", "speak": False},
    )
    chat_reply = (chat_res.get("reply") or "").strip()
    assert chat_res.get("status") == "success" and chat_reply, f"Falha na inferência real: {chat_res}"
    assert "não retornou texto visível" not in chat_reply.lower(), f"Modelo retornou vazio: {chat_reply}"
    log("ORACULO-PROVEDORES", f"   OK -> Inferência real respondeu ({chat_res.get('model')}): '{chat_reply[:60]}'")

    log("ORACULO-PROVEDORES", "4. Validando failover automático quando provedor escolhido falha (apenas provider=openai com chave inválida)...")
    failover_res = request_json(
        "/api/chat",
        method="POST",
        data={
            "message": "Responda apenas com a palavra: ROTEADO",
            "provider": "openai",
            "api_key": "sk-invalid-oracle-test",
            "speak": False,
        },
    )
    fo_reply = (failover_res.get("reply") or "").strip()
    assert failover_res.get("status") == "success" and fo_reply, f"Failover automático falhou: {failover_res}"
    assert failover_res.get("fallback_used") is True, f"Esperava fallback_used=True, veio: {failover_res}"
    assert failover_res.get("provider") != "openai", f"Não roteou para fora do provedor inválido: {failover_res}"
    log("ORACULO-PROVEDORES", f"   OK -> Roteado automaticamente de openai para '{failover_res.get('provider')}' ({failover_res.get('model')}): '{fo_reply[:60]}'")

    log("ORACULO-PROVEDORES", "5. Validando failover automático para Anthropic com chave inválida (apenas provider=anthropic)...")
    ant_res = request_json(
        "/api/chat",
        method="POST",
        data={
            "message": "Responda apenas com a palavra: CLAUDE_ROTEADO",
            "provider": "anthropic",
            "api_key": "sk-ant-invalid-oracle-test",
            "speak": False,
        },
    )
    ant_reply = (ant_res.get("reply") or "").strip()
    assert ant_res.get("status") == "success" and ant_reply, f"Failover automático da Anthropic falhou: {ant_res}"
    assert ant_res.get("fallback_used") is True and ant_res.get("provider") != "anthropic", f"Não roteou fora de anthropic inválido: {ant_res}"
    log("ORACULO-PROVEDORES", f"   OK -> Roteado automaticamente de anthropic para '{ant_res.get('provider')}' ({ant_res.get('model')}): '{ant_reply[:60]}'")

    log("ORACULO-PROVEDORES", "6. Validando matriz de capacidades do roteador (/api/router/capabilities: text, vision, tools)...")
    cap_res = request_json("/api/router/capabilities")
    caps = cap_res.get("capabilities", {})
    assert len(caps.get("text", [])) > 0 and len(caps.get("vision", [])) > 0 and len(caps.get("tools", [])) > 0, (
        f"Matriz de capacidades incompleta: {cap_res}"
    )
    tool_models = {(m["provider"], m["model"]) for m in caps["tools"]}
    assert ("opencode", "opencode/deepseek-v4.1-flash-free") not in tool_models, (
        "Modelo somente-texto não deve estar no pool de tool calling!"
    )
    log(
        "ORACULO-PROVEDORES",
        f"   OK -> Pools mapeados: text={len(caps['text'])}, vision={len(caps['vision'])}, tools={len(caps['tools'])}.",
    )

    log("ORACULO-PROVEDORES", "STATUS: 100% APROVADO! Todos os provedores mapeados, roteamento por capacidade e failover funcionais.")


if __name__ == "__main__":
    try:
        run_providers_oracle()
        sys.exit(0)
    except Exception as e:
        print(f"\n[FALHA NO ORÁCULO PROVEDORES] {e}\n", file=sys.stderr)
        sys.exit(1)
