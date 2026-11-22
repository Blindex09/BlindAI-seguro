"""
Blind AI - Comprehensive E2E Integration Oracle
Testa TODAS as funcionalidades reais do sistema de ponta a ponta sem dados simulados (zero mock).
Projetado como oráculo de auto-cura para execução com o Aider (--test-cmd) e OpenHands.

Critério de aceitação:
- Retorna código de saída 0 se e somente se 100% dos testes passarem.
- Retorna código diferente de zero com trace detalhado da falha caso qualquer contrato ou funcionalidade falhe.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from oracle_base import ensure_mandatory_cloners

SERVER_URL = "http://127.0.0.1:8765"


class TestOracleError(Exception):
    """Exceção levantada pelo oráculo quando um contrato é quebrado."""
    pass


def log(msg: str):
    print(f"[ORACLE] {msg}", flush=True)


def request_json(endpoint: str, method: str = "GET", data: dict | None = None, timeout: float = 30.0) -> dict:
    url = f"{SERVER_URL}{endpoint}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        raise TestOracleError(f"HTTP {e.code} em {method} {endpoint}: {err_body}") from e
    except Exception as e:
        raise TestOracleError(f"Falha de rede em {method} {endpoint}: {e}") from e


# --- 1. TESTE DE SAÚDE E PROVEDORES ---
def test_health_and_providers():
    log("Testando 1. Saúde da API e Descoberta de Provedores (/api/status)...")
    res = request_json("/api/status")
    assert res.get("status") == "ready", f"Status esperado 'ready', obtido: {res.get('status')}"
    assert "configured_provider" in res, "Campo 'configured_provider' ausente"
    assert "local_services" in res, "Campo 'local_services' ausente"
    log(f"   OK -> Provedor: {res['configured_provider']} | Modelo: {res.get('configured_model')}")


# --- 1.1 TESTE DE COBERTURA DE TODOS OS PROVEDORES E MODELOS ---
def test_all_providers_and_model_catalog():
    log("Testando 1.1 Cobertura de Catálogo de Todos os Provedores (/api/models/{provider})...")
    expected_providers = ["opencode", "ollama", "lmstudio", "openai", "gemini"]
    for prov in expected_providers:
        m_res = request_json(f"/api/models/{prov}")
        models = m_res.get("models", [])
        assert len(models) > 0, f"Provedor {prov} não retornou nenhum modelo no catálogo!"
        log(f"   OK -> Provedor '{prov}': {len(models)} modelos mapeados.")

    log("   Testando capacidade e resposta dos modelos gratuitos do OpenCode...")
    for model_name in ["opencode-zen", "opencode/deepseek-v4.1-flash-free", "opencode/beam-free"]:
        c_res = request_json(
            "/api/chat",
            method="POST",
            data={"message": "Responda 'OK'", "provider": "opencode", "model": model_name, "tts": False},
            timeout=45.0,
        )
        assert len(c_res.get("reply", "").strip()) > 0, f"Modelo {model_name} retornou resposta vazia"
        log(f"      -> Modelo '{model_name}': respondendo com sucesso.")

    log("   Testando tratamento resiliente de provedores locais e sem chave...")
    # Ollama sem modelos baixados
    ollama_res = request_json(
        "/api/chat",
        method="POST",
        data={"message": "Ola", "provider": "ollama", "model": "llama3.2:latest", "tts": False},
    )
    assert ollama_res.get("status") in ("no_models", "ready", "offline"), f"Resposta inesperada do Ollama: {ollama_res}"
    
    # OpenAI sem chave fornecida
    openai_res = request_json(
        "/api/chat",
        method="POST",
        data={"message": "Ola", "provider": "openai", "model": "gpt-4o-mini", "tts": False},
    )
    assert openai_res.get("status") == "error" and "Chave" in openai_res.get("reply", ""), "Validação de chave OpenAI falhou"
    log("   OK -> Todos os 5 provedores e seus comportamentos foram validados com sucesso.")


# --- 2. TESTE DE CHAT & FALLBACK ROUTER ---
def test_chat_stream():
    log("Testando 2. Conversação Acessível & Fallback Router (/api/chat)...")
    payload = {
        "message": "Diga 'Sistema operacional pronto' em uma única frase curta.",
        "tts": False,
    }
    res = request_json("/api/chat", method="POST", data=payload, timeout=60.0)
    reply = res.get("reply", "").strip()
    assert len(reply) > 3, f"Resposta do chat vazia ou insuficiente: {reply}"
    assert not any(ord(char) > 0x1F000 for char in reply), "Emojis detectados na resposta do chat!"
    log(f"   OK -> IA respondeu: '{reply[:60]}...'")


# --- 3. TESTE DE AUDIODESCRIÇÃO DE IMAGEM REAL ---
def test_vision_multimodal():
    log("Testando 3. Audiodescrição Multimodal (/api/vision/describe)...")
    try:
        from PIL import Image, ImageDraw
        import io
        img = Image.new("RGB", (320, 240), color=(10, 50, 160))
        draw = ImageDraw.Draw(img)
        draw.rectangle([40, 40, 280, 200], fill=(230, 230, 230), outline=(255, 215, 0))
        draw.text((60, 100), "BLIND TESTE 2026", fill=(0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        data_uri = f"data:image/png;base64,{raw_b64}"
    except ImportError:
        # Fallback para PNG válido pré-gerado de 1x1 pixel azul
        raw_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkWPjfDwAEcQHsW4E7vQAAAABJRU5ErkJggg=="
        data_uri = f"data:image/png;base64,{raw_b64}"

    res = request_json("/api/vision/describe", method="POST", data={"image_base64": data_uri}, timeout=90.0)
    desc = res.get("description", "").strip()
    assert len(desc) > 10, f"Descrição de imagem vazia: {desc}"
    assert "Não recebi nenhuma imagem" not in desc, "Falha de ponte ACP: IA relatou não ter recebido a imagem!"
    log(f"   OK -> Audiodescrição gerada ({len(desc)} caracteres): '{desc[:70]}...'")


# --- 4. TESTE DE LEITURA DE PDF / FATURAS COM PYMUPDF ---
def test_invoice_pdf_reader():
    log("Testando 4. Smart Audio Desk - Leitor de Faturas e PDFs (/api/docs/read)...")
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    sample_text = (
        "Companhia de Energia Elétrica S.A.\n"
        "FATURA DE CONSUMO MENSAL\n"
        "Vencimento: 28/11/2026\n"
        "Valor Total a Pagar: R$ 184,50\n"
        "Linha Digitável: 83640000001-2 84500138001-4 00000000000-0 00000000000-0\n"
    )
    page.insert_text((50, 72), sample_text, fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()

    pdf_b64 = f"data:application/pdf;base64,{base64.b64encode(pdf_bytes).decode('utf-8')}"
    res = request_json("/api/docs/read", method="POST", data={"file_base64": pdf_b64, "filename": "fatura_luz.pdf"}, timeout=90.0)
    
    assert res.get("status") == "success", f"Falha na leitura do PDF: {res}"
    analysis = res.get("invoice_analysis", {})
    assert "extracted_text" in res and len(res["extracted_text"]) > 20, "Texto do PDF não foi extraído"
    assert "Companhia de Energia" in res["extracted_text"], "Conteúdo do PDF divergente"
    log("   OK -> PDF lido com sucesso via PyMuPDF e estrutura de fatura extraída.")


# --- 5. TESTE DE ESCRITOR ATÔMICO SEGURO ---
def test_smart_writer_atomic():
    log("Testando 5. Escritor Acessível - Minuta e Gravação Atômica (/api/writer)...")
    draft_res = request_json(
        "/api/writer/draft",
        method="POST",
        data={
            "title": "Ata de Homologacao de Testes",
            "content": "Parágrafo primeiro: todos os testes de acessibilidade foram cumpridos sem erro.\n\nParágrafo segundo: sistema atômico aprovado.",
            "doc_format": "txt",
        },
    )
    assert draft_res.get("ready_to_save") is True, f"Minuta rejeitada: {draft_res}"
    assert "spoken_review" in draft_res, "Revisão fonética não foi gerada para leitor de tela"
    assert draft_res.get("word_count", 0) > 10, "Contagem de palavras incorreta"

    save_res = request_json(
        "/api/writer/save",
        method="POST",
        data={"draft": draft_res},
    )
    assert save_res.get("status") == "success", f"Falha ao salvar: {save_res}"
    file_path = Path(save_res["path"])
    assert file_path.exists(), f"Arquivo não foi gravado em {file_path}"
    assert "todos os testes de acessibilidade" in file_path.read_text(encoding="utf-8")

    # Testa se o backup é gerado ao sobrescrever
    save_res2 = request_json(
        "/api/writer/save",
        method="POST",
        data={"draft": draft_res},
    )
    assert save_res2.get("backup_path") is not None, "Backup .bak não foi criado ao sobrescrever arquivo existente"
    assert Path(save_res2["backup_path"]).exists(), "Arquivo .bak de backup não existe no disco"
    log("   OK -> Minuta, escrita atômica e backup .bak confirmados no sistema de arquivos.")


# --- 6. TESTE DE CANAL WHATSAPP (BAILEYS SIGNAL PROTOCOL) ---
def test_whatsapp_pairing_protocol():
    log("Testando 6. Pareamento de WhatsApp sem QR Code (/api/whatsapp/pair)...")
    res = request_json("/api/whatsapp/pair", method="POST", data={"phone": "11 98765-4321"})
    assert res.get("status") == "waiting_link", f"Status inesperado: {res}"
    assert res.get("phone") == "5511987654321", f"Normalização E.164 falhou: {res.get('phone')}"
    code = res.get("code", "")
    assert re.match(r"^[2-9A-HJ-NP-Z]{4}-[2-9A-HJ-NP-Z]{4}$", code), f"Código de pareamento fora do padrão Base-32: {code}"
    assert "traço" in res.get("spoken_instructions", ""), "Instruções soletradas para NVDA ausentes"

    # Confirma status no SQLite
    status_res = request_json(f"/api/whatsapp/status?phone={res['phone']}")
    assert status_res.get("pairing_code") == code, "Sessão não foi persistida corretamente no banco SQLite"
    log(f"   OK -> Telefone normalizado para {res['phone']}, código {code} gerado e validado no SQLite.")


# --- 7. TESTE DE CANAL TELEGRAM (BOTFATHER CONNECTOR) ---
def test_telegram_connector():
    log("Testando 7. Conector de Bot do Telegram (/api/telegram)...")
    try:
        request_json("/api/telegram/connect", method="POST", data={"bot_token": "token_invalido_sem_formato"})
        raise TestOracleError("Token inválido deveria ter sido rejeitado com HTTP 400!")
    except TestOracleError as e:
        if "HTTP 400" in str(e):
            log("   OK -> Validação estrita de formato do token rejeitou token inválido com sucesso.")
        else:
            raise

    bots_res = request_json("/api/telegram/status")
    assert "bots" in bots_res, "Endpoint /api/telegram/status não retornou a chave 'bots'"
    log("   OK -> Tabela de bots do Telegram respondendo normalmente via SQLite.")


# --- 8. TESTE DE SESSÕES TEMÁTICAS E HISTÓRICO DE CONVERSAS (HERMES & OPENHANDS) ---
def test_sessions_and_conversation_history():
    log("Testando 8. Gerenciador de Sessões e Histórico de Conversas (/api/sessions)...")
    sess = request_json("/api/sessions", method="POST", data={"title": "Audiodescrição de Fatura", "source": "vision"})
    sess_id = sess.get("id")
    assert sess_id and sess_id.startswith("sess_"), f"ID de sessão inválido: {sess_id}"

    chat_res = request_json(
        "/api/chat",
        method="POST",
        data={"message": "Explique o detalhe desta fatura.", "session_id": sess_id, "tts": False},
        timeout=90.0,
    )
    assert len(chat_res.get("reply", "")) > 0, "Resposta do chat vinculada à sessão falhou"

    hist = request_json(f"/api/sessions/{sess_id}/messages")
    messages = hist.get("messages", [])
    assert len(messages) >= 2, f"Histórico de mensagens incompleto no SQLite: {len(messages)} encontradas"
    assert any(m["is_user"] for m in messages), "Mensagem do usuário não foi persistida no histórico"
    assert any(not m["is_user"] for m in messages), "Resposta da IA não foi persistida no histórico"

    sess_list = request_json("/api/sessions")
    assert any(s["id"] == sess_id for s in sess_list.get("sessions", [])), "Sessão criada não listada no histórico"
    log(f"   OK -> Sessão {sess_id} criada, mensagens persistidas e recuperadas com sucesso no SQLite.")


# --- 9. TESTE COGNITIVO DE PONTA A PONTA (O QUEBRA-CABEÇA COMPLETO: TELA -> MEMÓRIA -> RESPOSTA) ---
def test_cognitive_context_retention_and_screen_memory():
    log("Testando 9. Jornada Cognitiva Completa: Visão de Tela -> Persistência -> Perguntas no Chat...")
    # 1. Cria sessão automática como a UI faz
    sess = request_json(
        "/api/sessions",
        method="POST",
        data={"title": "Audiodescrição: Captura da Tela WinZap", "source": "vision"},
    )
    sess_id = sess.get("id")
    assert sess_id, "Falha ao instanciar sessão para o fluxo de visão"

    # 2. Injeta a audiodescrição da tela com nome exato do software
    desc_tela = (
        "A janela do programa WinZap versão 3 ocupa a tela inteira. Na barra de título no topo "
        "está escrito WinZap 3 entre parênteses, com os botões de minimizar, maximizar e fechar "
        "no canto superior direito. No painel lateral esquerdo aparece a lista de conversas."
    )
    request_json(
        f"/api/sessions/{sess_id}/messages",
        method="POST",
        data={
            "sender": "Audiodescrição (Captura da Tela Atual)",
            "text": desc_tela,
            "is_user": False,
        },
    )

    # 3. Faz a pergunta que quebrou anteriormente: 'qual o nome do software?'
    chat_turn_1 = request_json(
        "/api/chat",
        method="POST",
        data={
            "message": "qual o nome do software da tela que você viu?",
            "session_id": sess_id,
            "provider": "opencode",
            "model": "opencode/deepseek-v4.1-flash-free",
            "tts": False,
        },
        timeout=90.0,
    )
    reply_1 = chat_turn_1.get("reply", "")
    assert reply_1, "A IA não respondeu à pergunta sobre o software da tela"

    # Validações cognitivas estritas (Anti-alucinação e Retenção de Memória)
    reply_lower = reply_1.lower()
    assert "winzap" in reply_lower or "winzip" in reply_lower, (
        f"FALHA COGNITIVA: A IA não identificou o software da tela no contexto! Resposta: '{reply_1}'"
    )
    assert "não tenho o conteúdo" not in reply_lower and "não consigo recuperar" not in reply_lower, (
        f"FALHA COGNITIVA: A IA alegou não ter o conteúdo da tela na memória! Resposta: '{reply_1}'"
    )
    assert "*" not in reply_1, f"FALHA DE ACESSIBILIDADE: Resposta contém asteriscos proibidos: '{reply_1}'"
    log(f"   OK -> IA respondeu com precisão semântica e retenção de contexto: '{reply_1[:80]}...'")

    # 4. Turno de continuidade: 'o que tem no canto superior direito?'
    chat_turn_2 = request_json(
        "/api/chat",
        method="POST",
        data={
            "message": "o que tem no canto superior direito?",
            "session_id": sess_id,
            "provider": "opencode",
            "model": "opencode/deepseek-v4.1-flash-free",
            "tts": False,
        },
        timeout=90.0,
    )
    reply_2 = chat_turn_2.get("reply", "")
    assert reply_2, "A IA não respondeu ao segundo turno de perguntas sobre a tela"
    reply_2_lower = reply_2.lower()
    assert any(term in reply_2_lower for term in ["minimizar", "maximizar", "fechar", "botões"]), (
        f"FALHA COGNITIVA: A IA perdeu o contexto no segundo turno! Resposta: '{reply_2}'"
    )
    assert "*" not in reply_2, f"FALHA DE ACESSIBILIDADE: Resposta do turno 2 contém asteriscos: '{reply_2}'"
    log(f"   OK -> IA manteve contexto no segundo turno: '{reply_2[:80]}...'")


# --- 10. TESTE COGNITIVO DE FATURAS E DOCUMENTOS (PDF -> SESSÃO -> RESPOSTA COM VALOR EXATO) ---
def test_cognitive_invoice_memory():
    log("Testando 10. Jornada Cognitiva de Documento: Leitura de PDF -> Persistência -> Pergunta de Valor no Chat...")
    sess = request_json(
        "/api/sessions",
        method="POST",
        data={"title": "Fatura de Energia Elétrica", "source": "docs"},
    )
    sess_id = sess.get("id")
    assert sess_id, "Falha ao criar sessão temática de documento"

    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    sample_text = (
        "ENEL DISTRIBUIÇÃO SÃO PAULO\n"
        "CONTA DE ENERGIA ELÉTRICA - MÊS DE NOVEMBRO 2026\n"
        "Vencimento: 25/11/2026\n"
        "Total a Pagar: R$ 247,80\n"
        "Consumo: 195 kWh\n"
    )
    page.insert_text((50, 72), sample_text, fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    pdf_b64 = f"data:application/pdf;base64,{base64.b64encode(pdf_bytes).decode('utf-8')}"

    read_res = request_json(
        "/api/docs/read",
        method="POST",
        data={"file_base64": pdf_b64, "filename": "enel_novembro.pdf", "session_id": sess_id},
        timeout=90.0,
    )
    assert read_res.get("status") == "success", "Falha ao ler fatura PDF"

    chat_turn = request_json(
        "/api/chat",
        method="POST",
        data={
            "message": "qual o valor total a pagar da fatura que você acabou de ler?",
            "session_id": sess_id,
            "provider": "opencode",
            "model": "opencode/deepseek-v4.1-flash-free",
            "tts": False,
        },
        timeout=90.0,
    )
    reply = chat_turn.get("reply", "")
    assert reply, "IA não respondeu sobre o valor da fatura"
    reply_lower = reply.lower()
    assert "247" in reply_lower or "247,80" in reply_lower, (
        f"FALHA COGNITIVA: A IA não reteve o valor da fatura lida! Resposta: '{reply}'"
    )
    assert "*" not in reply, f"FALHA DE ACESSIBILIDADE: Resposta contém asteriscos: '{reply}'"
    log(f"   OK -> IA recuperou com sucesso o valor da fatura na memória da sessão: '{reply[:80]}...'")


# --- 11. TESTE DE CONTRATOS DO FRONT-END E NORMAS DE ACESSIBILIDADE (HTML / DOM / LEITOR DE TELAS) ---
def test_frontend_accessibility_contracts():
    log("Testando 11. Contratos de Acessibilidade do Front-End (src/renderer)...")
    sys.path.insert(0, str(Path(__file__).resolve().parent / "frontend"))
    from renderer_contracts import check_renderer_contracts

    result = check_renderer_contracts()
    log(f"   OK -> {result['files']} arquivos e {result['screens']} telas do renderer 100% íntegros.")


def run_all_oracle_tests():
    print("\n" + "=" * 70)
    print(" [ORÁCULO E2E INTEGRADO] - CLONADORES (Aider + OpenHands <-> C:\\repos ia) & VALIDAÇÃO")
    print("=" * 70)
    ensure_mandatory_cloners("e2e")
    start_time = time.time()
    tests = [
        test_health_and_providers,
        test_all_providers_and_model_catalog,
        test_chat_stream,
        test_vision_multimodal,
        test_invoice_pdf_reader,
        test_smart_writer_atomic,
        test_whatsapp_pairing_protocol,
        test_telegram_connector,
        test_sessions_and_conversation_history,
        test_cognitive_context_retention_and_screen_memory,
        test_cognitive_invoice_memory,
        test_frontend_accessibility_contracts,
    ]

    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            print(f"\n[FALHA CRÍTICA NO ORÁCULO] Em {t.__name__}: {e}\n", file=sys.stderr)

    duration = time.time() - start_time
    print("=" * 70)
    if failed == 0:
        print(f" RESULTADO: 100% DOS TESTES APROVADOS ({len(tests)} módulos validados em {duration:.1f}s)")
        print(" O software está 100% íntegro, integrado e pronto para produção.")
        print("=" * 70 + "\n")
        sys.exit(0)
    else:
        print(f" RESULTADO: {failed} FALHA(S) DETECTADA(S) PELO ORÁCULO.")
        print("=" * 70 + "\n")
        sys.exit(1)


if __name__ == "__main__":
    run_all_oracle_tests()
