import pytest
import asyncio
from core.providers.smart_router import FallbackRouter, infer_required_capability, get_model_metadata
from blind_mcp.context_engine import build_compressed_history, prune_tool_messages
from blind_mcp.agent_loop import select_relevant_servers

@pytest.mark.asyncio
async def test_fallback_router_prefers_primary():
    router = FallbackRouter()

    async def mock_exec(prov, model, prompt):
        return f"OK from {prov}/{model}"

    res = await router.execute_with_failover(
        prompt="Olá",
        preferred_provider="opencode",
        preferred_model="opencode/deepseek-v4.1-flash-free",
        executor_fn=mock_exec
    )

    assert res["fallback_used"] is False
    assert res["provider"] == "opencode"
    assert "OK" in res["result"]

@pytest.mark.asyncio
async def test_fallback_router_switches_on_error():
    router = FallbackRouter()

    async def mock_exec(prov, model, prompt):
        if prov == "opencode" and "deepseek" in model:
            raise ConnectionError("Rate limit exceeded")
        return f"OK fallback from {prov}/{model}"

    res = await router.execute_with_failover(
        prompt="Olá",
        preferred_provider="opencode",
        preferred_model="opencode/deepseek-v4.1-flash-free",
        executor_fn=mock_exec
    )

    assert res["fallback_used"] is True
    assert "OK fallback" in res["result"]


def test_capability_inference_and_context_window():
    assert infer_required_capability("Analise passo a passo esta escolha", needs_tools=False) == "reasoning"
    assert infer_required_capability("Resuma a fatura de energia PDF completa", needs_tools=False) == "long_context"
    assert infer_required_capability("Clique no botão Enviar", needs_tools=True) == "tools"
    assert get_model_metadata("gemini", "gemini-2.5-pro")["context_window"] == 1000000


def test_head_tail_context_compression_never_loses_first_message():
    msgs = [{"is_user": False, "text": "Audiodescrição inicial: Programa WinZap aberto, fatura R$ 247,80."}]
    for i in range(25):
        msgs.append({"is_user": i % 2 == 0, "text": f"Turno intermediário {i} sobre configurações e detalhes."})
    msgs.append({"is_user": True, "text": "Qual era o valor da fatura lá do começo?"})

    compressed = build_compressed_history(msgs, protect_head=2, protect_tail=6)
    assert len(compressed) == 9  # 2 head + 1 summary + 6 tail
    assert "R$ 247,80" in compressed[0]["content"]
    assert "Resumo compactado" in compressed[2]["content"]
    assert compressed[-1]["content"] == "Qual era o valor da fatura lá do começo?"


def test_proactive_tool_result_pruning_dedup_and_compact():
    big_snapshot = "Janela Principal\n" + ("Botão Item de Menu " * 60)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "abra"},
        {"role": "tool", "tool_call_id": "1", "content": big_snapshot},
        {"role": "tool", "tool_call_id": "2", "content": "Outro resultado grande " * 50},
        {"role": "tool", "tool_call_id": "3", "content": big_snapshot},
        {"role": "tool", "tool_call_id": "4", "content": "Recente 1"},
        {"role": "tool", "tool_call_id": "5", "content": "Recente 2"},
    ]
    pruned = prune_tool_messages(messages, protect_last_rounds=2, max_old_tool_chars=300)
    # Tool 1 era duplicata exata do Tool 3: deve ser substituída por referência curta
    assert "identico" in pruned[2]["content"]
    # Tool 2 era antiga e grande: deve ter sido compactada
    assert "compactados" in pruned[3]["content"]
    # Tool 3 (cópia mais nova da duplicata, mas antiga) foi compactada preservando início e fim
    assert "Janela Principal" in pruned[4]["content"]


def test_tool_scoping_by_intent():
    s_doc = select_relevant_servers("Leia esta fatura PDF e resuma")
    assert "blind-docs" in s_doc and "windows" not in s_doc
    s_desk = select_relevant_servers("Clique no botão fechar da janela")
    assert "agent-desktop" in s_desk and "windows" in s_desk


@pytest.mark.asyncio
async def test_opencode_zero_key_mcp_loop():
    from blind_mcp.agent_loop import run_opencode_loop, _extract_json_tool_call

    tc = _extract_json_tool_call('{"tool_call": {"name": "blind-memory__memory_save", "arguments": {"key": "nome", "value": "Olive"}}}')
    assert tc == {"name": "blind-memory__memory_save", "arguments": {"key": "nome", "value": "Olive"}}

    class FakeBridge:
        def __init__(self):
            self.calls = 0

        async def prompt(self, text, model=None):
            self.calls += 1
            if self.calls == 1:
                return {"reply": '{"tool_call": {"name": "blind-memory__memory_save", "arguments": {"key": "idioma", "value": "pt-BR"}}}'}
            return {"reply": "Memória salva com sucesso no seu perfil."}

    class FakeManager:
        def openai_tools(self, servers=None):
            return [
                {
                    "type": "function",
                    "function": {
                        "name": "blind-memory__memory_save",
                        "description": "Salva fato na memória",
                        "parameters": {"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}}},
                    },
                }
            ]

        async def call_qualified(self, name, args, from_model=True):
            return {"ok": True, "is_error": False, "content": f"Salvo {args}", "images": 0, "tool": "memory_save", "server": "blind-memory"}

    reply, actions = await run_opencode_loop(
        FakeBridge(),
        ["opencode/deepseek-v4.1-flash-free"],
        "Você é o Blind AI.",
        [],
        "Lembre que meu idioma é pt-BR",
        FakeManager(),
        use_tools=True,
    )
    assert "Memória salva com sucesso" in reply
    assert len(actions) == 1
    assert actions[0]["tool"] == "memory_save"
    assert actions[0]["status"] == "success"


