"""As unicas ferramentas que o gateway remoto do Blind AI oferece ao Claude do celular e da web.

Regra desta lista: so leitura. Nenhuma ferramenta apaga, envia, grava, move arquivo, abre programa, comanda o mouse
ou o teclado, le um arquivo do computador por caminho, abre o cofre ou mexe em WhatsApp, Telegram, e-mail e Drive.
Tudo isso continua no Blind local (voz, no computador), nunca atras de uma URL.

Para incluir uma ferramenta, ela precisa passar nas tres perguntas de `PERGUNTAS` e entrar aqui, com o motivo,
numa revisao. O gateway recusa qualquer nome que nao esteja nesta lista, mesmo que o servidor o tenha.

Ficam FORA do remoto, por pedido da revisao da casa (24/11/2026): `memory_recall` e `session_search`. Junto com a leitura de
links (web_read), elas deixariam uma pagina maliciosa levar a memoria da pessoa. Continuam no Blind local, por voz.
"""

from __future__ import annotations

from pathlib import Path

PERGUNTAS = (
    "Ela apaga ou troca algo no computador ou na conta da pessoa?",
    "Ela envia algo a alguem (mensagem, e-mail, arquivo, fala)?",
    "Ela le algo que a pessoa nao pediu para mostrar (arquivo por caminho, cofre, conversa)?",
)

# nome qualificado ("servidor__ferramenta", como o MCPManager o publica) -> por que e so leitura
REMOTE_READ_ONLY = {
    "blind-docs__web_search": "busca na web; nao toca no computador",
    "blind-docs__web_read": "le uma pagina da web que a pessoa pediu",
    "blind-schedule__blindschedule_list": "lista os lembretes; nao cria nem apaga",
    "blind-speech__list_voices": "lista as vozes instaladas",
    "blind-docs__read_document": "le o texto de um PDF que a pessoa manda em base64 ou por link publico da web (nunca por caminho)",
    "blind-docs__describe_image": "entrega uma imagem (base64 ou link publico da web) ao Claude para ele descrever; sem chave de IA, nunca por caminho",
}

# argumentos que o gateway fixa e o Claude nao escolhe: o OCR de PDF escaneado usaria a chave de IA do dono (inclusive quando o
# PDF chega por link no web_read). Em vez disso as paginas escaneadas voltam como imagem e quem le e o proprio Claude da pessoa.
_PDF_FIXO = {"ocr_scanned": False, "devolver_imagens": True}
REMOTE_FORCED_ARGS = {"blind-docs__read_document": dict(_PDF_FIXO), "blind-docs__web_read": dict(_PDF_FIXO)}

# argumentos que o gateway remoto nunca aceita, nem lista no esquema: um caminho de arquivo leria o computador
REMOTE_FORBIDDEN_ARGS = frozenset({"file_path", "path", "caminho", "output_path", "save_path", "api_key", "provider", "model"})


def forbidden_args(arguments) -> list:
    """Os argumentos proibidos que uma chamada trouxe (lista vazia: pode seguir)."""
    return sorted(k for k in (arguments or {}) if k in REMOTE_FORBIDDEN_ARGS)


def with_forced(qualified: str, arguments) -> dict:
    """Os argumentos da chamada com os fixos do gateway por cima."""
    return {**(arguments or {}), **REMOTE_FORCED_ARGS.get(qualified, {})}


URL_TOOLS = frozenset({"blind-docs__read_document", "blind-docs__describe_image"})
BLINDAUDIO = "blindaudio"  # ferramenta do proprio gateway (como o comecar): audio em texto, so por base64 ou link publico
AUDIO_MAX_BYTES = 3_000_000  # o corpo do pedido ao gateway para em 4 MiB (SDK do MCP): em base64 isso e ~3 MB de audio; mais que isso so por link
BLINDAUDIO_SCHEMA = {
    "type": "object",
    "properties": {
        "audio_base64": {"type": "string", "description": "O audio (WAV, MP3, M4A, OGG, FLAC, WebM) em base64. Curto; para audio longo use url."},
        "url": {"type": "string", "description": "Link publico (http ou https) do audio na web. Alternativa ao base64."},
        "language": {"type": "string", "description": "pt (padrao), en, ... ou auto para o Whisper descobrir."},
    },
}
URL_PROP = {"url": {"type": "string", "description": "Link publico (http ou https) do arquivo na web. Alternativa ao base64."}}


def clean_schema(schema: dict, qualified: str = "") -> dict:
    """O esquema da ferramenta sem os argumentos proibidos nem os fixos, para o Claude nem ver que existem."""
    hidden = REMOTE_FORBIDDEN_ARGS | set(REMOTE_FORCED_ARGS.get(qualified, {}))
    out = dict(schema or {})
    props = {k: v for k, v in (out.get("properties") or {}).items() if k not in hidden}
    if qualified in URL_TOOLS:
        props = {**props, **URL_PROP}
    out["properties"] = props
    if out.get("required"):
        out["required"] = [r for r in out["required"] if r not in hidden]
    return out


def allowed(qualified: str) -> bool:
    return qualified in REMOTE_READ_ONLY


HABILIDADES = Path(__file__).resolve().parent / "habilidades"
# so as habilidades que valem sem as ferramentas locais; linhas que citam ferramentas que o remoto nao oferece saem
_FORA = ("ver_imagem", "document_outline", "channel_describe_image", "documento_acessibilidade", "falar_em_segredo", "continuar")


def _habilidade(nome: str, secao: str = "") -> str:
    """O texto de uma habilidade do Blind, sem o cabecalho e sem as linhas que citam ferramentas que o remoto nao tem."""
    arq = HABILIDADES / f"{nome}.md"
    if not arq.is_file():
        return ""
    texto = arq.read_text(encoding="utf-8")
    if texto.startswith("---"):
        texto = texto.split("---", 2)[2]
    if secao:
        achou = texto.split(f"## {secao}", 1)
        if len(achou) < 2:
            return ""
        texto = achou[1].split(chr(10) + "## ", 1)[0]
    return chr(10).join(l for l in texto.strip().splitlines() if not any(f in l for f in _FORA))


def guia() -> str:
    """O que `comecar` responde no gateway remoto: as ferramentas desta lista e o jeito de falar do Blind para pessoa cega."""
    nl = chr(10)
    linhas = nl.join([*(f"- {nome}: {motivo}" for nome, motivo in sorted(REMOTE_READ_ONLY.items())),
                      "- blindaudio: transcreve audio em texto com Whisper no computador do Blind (base64 ou link publico; nunca por caminho)"])
    partes = [
        "Blind AI, conector remoto (so leitura).",
        "Este conector nao apaga, envia nem grava nada, e nao mexe no computador. "
        "Se a pessoa pedir algo assim, diga que isso se faz no Blind do computador, por voz.",
        "Imagens e PDFs entram por conteudo em base64 ou por link publico da web (url). Nunca por caminho do computador. "
        "PDF escaneado (so imagem): as paginas voltam como imagem e voce mesmo le, sem outro modelo nem chave de IA; diga que a leitura e sua e pode errar, e confirme valores, datas e nomes. "
        "Audio (voz, mensagem de voz) vira texto em blindaudio, por base64 curto ou, melhor, por link publico (url); leia o texto e diga a duracao. "
        "Um arquivo anexado na conversa voce mesmo ja le: nao precisa de ferramenta.",
        "OBRIGATORIO: a pessoa pode ser cega e ouve a resposta. Siga estas regras de fala, de descricao de imagens e de leitura de documentos.",
        "## Jeito de falar" + nl + _habilidade("jeito-de-falar"),
        "## Descrevendo imagens" + nl + _habilidade("descrevendo-imagens"),
        "## Lendo documentos" + nl + _habilidade("lendo-documentos", "Ler"),
        "Ferramentas deste conector:",
        linhas,
    ]
    return nl.join(p for p in partes if p.strip())
