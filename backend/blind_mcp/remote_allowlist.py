"""As unicas ferramentas que o gateway remoto do Blind AI oferece ao Claude do celular e da web.

Regra desta lista: so leitura. Nenhuma ferramenta apaga, envia, grava, move arquivo, abre programa, comanda o mouse
ou o teclado, le um arquivo do computador por caminho, abre o cofre ou mexe em WhatsApp, Telegram, e-mail e Drive.
Tudo isso continua no Blind local (voz, no computador), nunca atras de uma URL.

Para incluir uma ferramenta, ela precisa passar nas tres perguntas de `PERGUNTAS` e entrar aqui, com o motivo,
numa revisao. O gateway recusa qualquer nome que nao esteja nesta lista, mesmo que o servidor o tenha.
"""

from __future__ import annotations

PERGUNTAS = (
    "Ela apaga ou troca algo no computador ou na conta da pessoa?",
    "Ela envia algo a alguem (mensagem, e-mail, arquivo, fala)?",
    "Ela le algo que a pessoa nao pediu para mostrar (arquivo por caminho, cofre, conversa)?",
)

# nome qualificado ("servidor__ferramenta", como o MCPManager o publica) -> por que e so leitura
REMOTE_READ_ONLY = {
    "blind-docs__web_search": "busca na web; nao toca no computador",
    "blind-docs__web_read": "le uma pagina da web que a pessoa pediu",
    "blind-memory__memory_recall": "le a memoria que a pessoa pediu para lembrar",
    "blind-memory__session_search": "busca nas conversas do proprio Blind",
    "blind-schedule__blindschedule_list": "lista os lembretes; nao cria nem apaga",
    "blind-system__saude_teclado": "estado do teclado, so leitura",
    "blind-system__vigia_status": "estado do vigia, so leitura",
    "blind-speech__list_voices": "lista as vozes instaladas",
}


def allowed(qualified: str) -> bool:
    return qualified in REMOTE_READ_ONLY


def guia() -> str:
    """O que `comecar` responde no gateway remoto: so as ferramentas desta lista, nada do Blind local."""
    nl = chr(10)
    linhas = nl.join(f"- {nome}: {motivo}" for nome, motivo in sorted(REMOTE_READ_ONLY.items()))
    return nl.join([
        "Blind AI, conector remoto (so leitura).",
        "Este conector nao apaga, envia nem grava nada, e nao mexe no computador. "
        "Se a pessoa pedir algo assim, diga que isso se faz no Blind do computador, por voz.",
        "Ferramentas deste conector:",
        linhas,
    ])
