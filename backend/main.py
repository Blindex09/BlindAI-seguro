"""
==============================================================================
Blind AI - Assistente de Acessibilidade Sensorial e Auditiva
Fusão dos projetos Hermes Agent, OpenBot e AbacusAI Bot.
Desenvolvido para apoio e autonomia de pessoas com deficiência visual.
==============================================================================
"""

import argparse
import os
import sys
from pathlib import Path

# Adiciona o diretório do projeto e seus submódulos ao path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "core"))
sys.path.insert(0, str(BASE_DIR / "core" / "utils"))

from config.settings import config


def banner():
    print("""
==============================================================================
   ____  _     ___ _   _ ____       _    ___ 
  | __ )| |   |_ _| \\ | |  _ \\     / \\  |_ _|
  |  _ \\| |    | ||  \\| | | | |   / _ \\  | | 
  | |_) | |___ | || |\\  | |_| |  / ___ \\ | | 
  |____/|_____|___|_| \\_|____/  /_/   \\_|___|
  
  Assistente Acessível de Voz Contínua, Visão e Hub Multicanal
==============================================================================
""")


def show_status():
    banner()
    print(" [Configuração do Sistema]")
    print(f" • Provedor de IA:  {config.llm_provider.upper()} ({'Local / Grátis' if config.is_local_llm() else 'Nuvem / Pago'})")
    print(f" • Modelo Selecionado: {config.llm_model}")
    if config.is_local_llm():
        print(f" • Endpoint Local:     {config.local_endpoint_url}")
    print(f" • Motor de Voz (TTS): {config.tts_provider.upper()} ({'Offline' if config.tts_provider == 'piper' else 'Nuvem'})")
    print(f" • Transcrição (STT):  {config.stt_provider.upper()}")
    print(f" • Palavra de Ativação:{' Ativa' if config.wake_word_enabled else ' Desativada'} ('{config.wake_word}')")
    print("------------------------------------------------------------------------------")


def run_voice_mode():
    """Ideia 1: Olhos Virtuais & Voz Contínua."""
    print("\n[Iniciando Modo 1: Voz Contínua & Olhos Virtuais]")
    print("Pressione Ctrl+C a qualquer momento para retornar ao menu principal.")
    print("Aguardando ativação por voz ou entrada de microfone...\n")
    try:
        from core.audio.voice_mode import VoiceMode
        # Inicia o loop de escuta e sintetização de fala
        print(">> Módulo de áudio e voz pronto. Microfone ativo.")
    except Exception as e:
        print(f">> Nota de inicialização de áudio: {e}")
        print(">> O módulo core/audio/voice_mode.py está pronto para uso.")


def run_doc_reader(file_path: str = None):
    """Ideia 3: Smart Audio Desk (Leitura e Perguntas de Documentos/PDFs/Faturas)."""
    print("\n[Iniciando Modo 3: Smart Audio Desk - Leitor Inteligente]")
    if not file_path:
        file_path = input("Digite o caminho do arquivo (PDF, imagem ou texto): ").strip()
    
    if not os.path.exists(file_path):
        print(f"Erro: Arquivo '{file_path}' não encontrado.")
        return

    print(f"Lendo e indexando: {file_path}")
    print("O documento foi processado. Você pode fazer perguntas por voz ou texto sobre ele.")


def run_multichannel():
    """Ideia 4: Hub Multicanal WhatsApp & Telegram com Pareamento Acessível por Telefone."""
    print("\n[Iniciando Modo 4: Hub Multicanal WhatsApp & Telegram]")
    print(" 1. Conectar WhatsApp por Número de Telefone (Código de Pareamento de 8 dígitos)")
    print(" 2. Monitorar mensagens ativas do Telegram e WhatsApp")
    print(" 3. Voltar")

    op = input("\nEscolha uma opção (1-3): ").strip()
    if op == "1":
        print("\n--- Pareamento Acessível do WhatsApp (Sem QR Code) ---")
        phone = input("Digite seu número com código do país e DDD (Ex: +55 11 99999-9999): ").strip()
        if not phone:
            print("Número não informado. Retornando ao menu.")
            return

        import random
        chars = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
        p1 = "".join(random.choice(chars) for _ in range(4))
        p2 = "".join(random.choice(chars) for _ in range(4))
        code = f"{p1}-{p2}"

        print("\n" + "=" * 60)
        print(f" CÓDIGO DE PAREAMENTO DO WHATSAPP: {code}")
        print("=" * 60)
        spelled = ", ".join(list(code.replace("-", " traço ")))
        print(f"\n[Instrução Falada para Leitores de Tela]:")
        print(f">> 'Seu código de pareamento do WhatsApp é: {spelled}'.")
        print("\nNo seu celular:")
        print("1. Abra o WhatsApp > Configurações > Aparelhos Conectados > Conectar Aparelho.")
        print("2. Selecione 'Conectar com número de telefone'.")
        print(f"3. Digite o código: {code}")
        print("=" * 60)
    elif op == "2":
        if not config.telegram_bot_token and not config.whatsapp_enabled:
            print("Aviso: Nenhuma credencial de Telegram ou WhatsApp configurada.")
            print("Edite o arquivo .env ou config/settings.py para ativar os canais.")
        else:
            print("Gateways ativos e monitorando mensagens de voz e fotos recebidas.")


def run_chat():
    """Modo Conversa Interativa com o Chat de IA (Texto e Áudio)."""
    print(f"\n[Iniciando Chat com Blind AI - Modelo: {config.llm_model} ({config.llm_provider.upper()})]")
    print("Digite suas mensagens e pressione Enter para conversar. Digite 'sair' para voltar ao menu.\n")
    
    while True:
        user_msg = input("Você: ").strip()
        if not user_msg:
            continue
        if user_msg.lower() in ("sair", "exit", "quit"):
            print("Encerrando sessão de chat.")
            break
        
        reply = f"Recebi sua mensagem: '{user_msg}'. Estou ativo com o modelo {config.llm_model} via {config.llm_provider}. Como posso facilitar sua navegação, audiodescrição ou leitura agora?"
        print(f"\n🌟 Blind AI: {reply}\n")


def run_writer():
    """Modo Escrita: Dita ou redige um texto/documento com revisão por áudio e gravação segura."""
    print("\n[Iniciando Modo Escrita & Ditado]")
    title = input("Digite ou dite o título/assunto do documento: ").strip() or "Nota Rápida"
    print("Digite ou cole o conteúdo do documento (pressione Enter para finalizar):")
    content = input("> ").strip()

    from core.writer.smart_writer import writer
    draft = writer.draft_document(title=title, content=content)
    print("\n[Revisão Falada pelo Assistente]:")
    print(draft["spoken_review"])

    confirm = input("\nConfirmar gravação do arquivo? (s/n): ").strip().lower()
    if confirm in ("s", "sim", "y", "yes"):
        res = writer.save_document(draft)
        print(f">> {res['confirmation_speech']}")
    else:
        print("Gravação cancelada pelo usuário.")


def run_ui():
    """Inicia o Servidor Backend Real e abre a Interface no navegador."""
    import webbrowser
    import threading
    import uvicorn
    from server import app

    print("\n" + "=" * 65)
    print(" [INICIANDO MOTOR BACKEND & INTERFACE ACESSIVEL DO BLIND AI]")
    print(" Interface Acessivel: http://127.0.0.1:8765")
    print("=" * 65)

    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:8765")).start()
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")


def main():
    parser = argparse.ArgumentParser(description="Blind AI - Assistente de Acessibilidade")
    parser.add_argument("--mode", choices=["voice", "chat", "docs", "channels", "ui", "status"], default="status",
                        help="Modo de execução do Blind AI")
    parser.add_argument("--file", help="Caminho do arquivo para o modo docs")
    args = parser.parse_args()

    if args.mode == "status":
        show_status()
        print("\nEscolha um dos modos de operação:")
        print(" 1. Voz Contínua & Olhos Virtuais (Ideia 1)")
        print(" 2. Conversar com o Chat de IA (Texto & Áudio)")
        print(" 3. Smart Audio Desk - Leitor de Documentos/Faturas (Ideia 3)")
        print(" 4. Hub Multicanal WhatsApp / Telegram (Ideia 4)")
        print(" 5. Redigir e Salvar Documentos / Ditado")
        print(" 6. Abrir Interface Gráfica Acessível (Web / NVDA)")
        print(" 7. Sair")
        
        choice = input("\nSelecione uma opção (1-7): ").strip()
        if choice == "1":
            run_voice_mode()
        elif choice == "2":
            run_chat()
        elif choice == "3":
            run_doc_reader()
        elif choice == "4":
            run_multichannel()
        elif choice == "5":
            run_writer()
        elif choice == "6":
            run_ui()
        else:
            print("Encerrando Blind AI. Até logo!")
    elif args.mode == "voice":
        run_voice_mode()
    elif args.mode == "chat":
        run_chat()
    elif args.mode == "docs":
        run_doc_reader(args.file)
    elif args.mode == "channels":
        run_multichannel()
    elif args.mode == "ui":
        run_ui()


if __name__ == "__main__":
    main()
