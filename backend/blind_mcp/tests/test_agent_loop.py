"""Testes do loop de tool calling nativo, com provedor simulado (httpx.MockTransport) e MCP real."""

import asyncio
import json
import sys
from pathlib import Path

import httpx

from blind_mcp import MCPManager, ServerSpec
from blind_mcp.agent_loop import (
    NO_TOOL_HONEST,
    claims_action,
    run_anthropic_loop,
    run_openai_loop,
    wants_tools,
)

FAKE = str(Path(__file__).with_name("fake_server.py"))


def make_manager(tmp_path) -> MCPManager:
    spec = ServerSpec(
        name="fake",
        command=sys.executable,
        args=[FAKE],
        model_hidden_tools=["secret"],
        disabled_tools=["blocked_tool"],
        startup_timeout=30,
    )
    return MCPManager([spec], log_dir=tmp_path)


class Scripted:
    """Provedor simulado: devolve respostas em ordem e guarda cada requisicao recebida."""

    def __init__(self, responses, status=200):
        self.responses = list(responses)
        self.requests = []
        self.status = status

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        if callable(self.responses[0]):
            status, payload = self.responses.pop(0)(body)
            return httpx.Response(status, json=payload)
        return httpx.Response(self.status, json=self.responses.pop(0))

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def oa_text(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def oa_call(name, args, call_id="c1", raw=None):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": raw if raw is not None else json.dumps(args)},
                        }
                    ],
                }
            }
        ]
    }


def drive(tmp_path, scripted, user="abra o app", use_tools=True, **kw):
    async def go():
        mgr = make_manager(tmp_path)
        await mgr.start(wait=True, timeout=60)
        try:
            async with scripted.client() as client:
                return await run_openai_loop(
                    client,
                    "http://provider.test/v1/chat/completions",
                    {},
                    {"model": "m", "messages": [{"role": "user", "content": user}]},
                    mgr,
                    use_tools,
                    user,
                    **kw,
                )
        finally:
            await mgr.stop()

    return asyncio.run(go())


def test_tool_call_runs_on_mcp_and_result_goes_back_to_model(tmp_path):
    sp = Scripted([oa_call("fake__add", {"a": 2, "b": 40}), oa_text("A soma é 42.")])
    text, actions = drive(tmp_path, sp, user="some 2 e 40")
    assert text == "A soma é 42."
    assert len(actions) == 1 and actions[0]["status"] == "success" and actions[0]["server"] == "fake"
    # A segunda requisicao carrega o resultado REAL da ferramenta como mensagem de papel tool.
    tool_msg = [m for m in sp.requests[1]["messages"] if m["role"] == "tool"]
    assert tool_msg and tool_msg[0]["content"] == "42" and tool_msg[0]["tool_call_id"] == "c1"
    assert sp.requests[0]["tools"] and sp.requests[0]["tool_choice"] == "auto"


def test_claiming_action_without_tool_call_is_corrected_once(tmp_path):
    sp = Scripted(
        [
            oa_text("Pronto, abri o YouTube para você."),  # alucinacao: nenhuma ferramenta chamada
            oa_call("fake__echo", {"text": "youtube"}),  # apos a correcao, chama a ferramenta
            oa_text("Agora sim, executei e o resultado foi youtube."),
        ]
    )
    text, actions = drive(tmp_path, sp, user="abra o youtube")
    assert len(actions) == 1 and actions[0]["status"] == "success"
    assert "executei" in text
    assert "nao chamou nenhuma ferramenta" in sp.requests[1]["messages"][-1]["content"]


def test_persistent_hallucination_becomes_honest_answer(tmp_path):
    sp = Scripted([oa_text("Pronto, abri o YouTube."), oa_text("Feito! Abri sim.")])
    text, actions = drive(tmp_path, sp, user="abra o youtube")
    assert actions == []
    assert text == NO_TOOL_HONEST


def test_plain_answer_without_action_is_untouched(tmp_path):
    sp = Scripted([oa_text("Paris é a capital da França.")])
    text, actions = drive(tmp_path, sp, user="qual a capital da frança", use_tools=False)
    assert text == "Paris é a capital da França." and actions == []
    assert "tools" not in sp.requests[0]  # conversa comum nao paga o custo das ferramentas


def test_hidden_and_unknown_tools_are_refused_but_loop_continues(tmp_path):
    sp = Scripted(
        [
            oa_call("fake__secret", {"token": "abc"}, "c1"),
            oa_call("ferramenta_inventada", {}, "c2"),
            oa_text("Não consegui."),
        ]
    )
    text, actions = drive(tmp_path, sp)
    assert [a["status"] for a in actions] == ["error", "error"]
    errors = [m["content"] for r in sp.requests[1:] for m in r["messages"] if m["role"] == "tool"]
    assert all(e.startswith("ERRO:") for e in errors)
    assert text == "Não consegui."


def test_invalid_json_arguments_return_error_to_model(tmp_path):
    sp = Scripted([oa_call("fake__add", None, raw="{nao é json"), oa_text("Argumentos inválidos.")])
    text, actions = drive(tmp_path, sp)
    assert actions[0]["status"] == "error"
    tool_msg = [m for m in sp.requests[1]["messages"] if m["role"] == "tool"][0]
    assert "JSON" in tool_msg["content"]


def test_tool_error_from_server_is_reported_as_error(tmp_path):
    sp = Scripted([oa_call("fake__fail", {}), oa_text("A ferramenta falhou.")])
    text, actions = drive(tmp_path, sp)
    assert actions[0]["status"] == "error" and "boom" in actions[0]["message"]
    tool_msg = [m for m in sp.requests[1]["messages"] if m["role"] == "tool"][0]
    assert tool_msg["content"].startswith("ERRO:")


def test_provider_that_rejects_tools_falls_back_to_text(tmp_path):
    def reject_when_tools(body):
        if "tools" in body:
            return 400, {"error": "tools nao suportado"}
        return 200, oa_text("Resposta só em texto.")

    sp = Scripted([reject_when_tools, reject_when_tools])
    text, actions = drive(tmp_path, sp, user="oi")
    assert text == "Resposta só em texto." and actions == []


def test_provider_http_error_raises(tmp_path):
    sp = Scripted([{"error": "x"}], status=500)
    try:
        drive(tmp_path, sp)
    except RuntimeError as exc:
        assert "HTTP 500" in str(exc)
    else:
        raise AssertionError("deveria levantar RuntimeError")


def test_step_limit_stops_endless_tool_loops(tmp_path):
    sp = Scripted([oa_call("fake__echo", {"text": "x"}, f"c{i}") for i in range(10)])
    text, actions = drive(tmp_path, sp, max_steps=3)
    assert len(actions) == 3
    assert "limite de passos" in text


def test_anthropic_loop_uses_tool_use_and_tool_result_blocks(tmp_path):
    responses = [
        {"content": [{"type": "tool_use", "id": "tu1", "name": "fake__add", "input": {"a": 1, "b": 2}}]},
        {"content": [{"type": "text", "text": "Deu 3."}]},
    ]
    sp = Scripted(responses)

    async def go():
        mgr = make_manager(tmp_path)
        await mgr.start(wait=True, timeout=60)
        try:
            async with sp.client() as client:
                return await run_anthropic_loop(
                    client, {}, "claude", "sys", [{"role": "user", "content": "some 1 e 2"}], mgr, True
                )
        finally:
            await mgr.stop()

    text, actions = asyncio.run(go())
    assert text == "Deu 3." and actions[0]["status"] == "success"
    last = sp.requests[1]["messages"][-1]
    assert last["role"] == "user" and last["content"][0]["type"] == "tool_result"
    assert last["content"][0]["tool_use_id"] == "tu1" and last["content"][0]["content"] == "3"
    assert "fake__secret" not in {t["name"] for t in sp.requests[0]["tools"]}


def test_intent_heuristics():
    for msg in ["abra o bloco de notas", "clique em enviar", "mande uma mensagem no whatsapp",
                "o que tem na tela?", "toque uma música no youtube", "leia o arquivo", "descreva a tela"]:
        assert wants_tools(msg), msg
    for msg in ["olá, tudo bem?", "qual a capital da frança", "explique o que é fotossíntese"]:
        assert not wants_tools(msg), msg
    assert claims_action("Pronto, abri o aplicativo.") and not claims_action("Posso ajudar com isso.")
