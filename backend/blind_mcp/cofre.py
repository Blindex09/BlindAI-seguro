"""Cofre do Blind: segredos que a pessoa cega precisa ouvir, mas que nao podem ficar expostos.

Ideia: "fala, mas nao expoe". O segredo e guardado criptografado (DPAPI do Windows: so esta conta de usuario, neste computador,
consegue abrir), e sai por VOZ ou pela AREA DE TRANSFERENCIA (que se limpa sozinha), nunca no texto devolvido a quem chamou a
ferramenta, nem no diario de acoes, nem na memoria, nem no historico de conversas.

Limite honesto: o que o modelo de IA (a nuvem) ja leu ou recebeu nao some. O cofre protege o que fica guardado e por onde o
dado sai. Para o segredo nunca passar pelo modelo, a pessoa copia o valor e diz "guarde no cofre" (da_area_de_transferencia).
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DATA_DIR = Path(os.environ.get("BLIND_DATA_DIR") or (Path(__file__).resolve().parent.parent / "data"))
COFRE_FILE = DATA_DIR / "cofre.json"
_LOCK = threading.Lock()
PENDENTES: Dict[str, Dict[str, Any]] = {}
PENDENTE_TTL = 300


# ---------------------------------------------------------------- criptografia (DPAPI)
def _proteger(dados: bytes) -> bytes:
    import win32crypt

    return win32crypt.CryptProtectData(dados, "Blind cofre", None, None, None, 0)


def _abrir(dados: bytes) -> bytes:
    import win32crypt

    return win32crypt.CryptUnprotectData(dados, None, None, None, 0)[1]


def _norm(nome: str) -> str:
    return re.sub(r"\s+", " ", (nome or "").strip().lower())


def _carregar() -> Dict[str, Any]:
    try:
        return json.loads(COFRE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"itens": {}}


def _gravar(d: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = COFRE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, COFRE_FILE)


def guardar(nome: str, segredo: str) -> Dict[str, Any]:
    n = _norm(nome)
    if not n or not segredo:
        raise ValueError("Informe o nome do item e o segredo.")
    if detectar(n):
        raise ValueError("O nome do item não pode ser o próprio segredo. Use um nome como 'cartão do banco' ou 'senha do wifi'.")
    tipos = detectar(segredo)
    with _LOCK:
        d = _carregar()
        d["itens"][n] = {"dados": base64.b64encode(_proteger(segredo.encode("utf-8"))).decode("ascii"),
                         "tipo": tipos[0] if tipos else "", "criado": time.strftime("%Y-%m-%dT%H:%M:%S")}
        _gravar(d)
    return {"nome": n, "tipo": tipos[0] if tipos else "", "tamanho": len(segredo)}


def ler(nome: str) -> str:
    n = _norm(nome)
    item = _carregar()["itens"].get(n)
    if not item:
        achados = [k for k in _carregar()["itens"] if n and n in k]
        if len(achados) == 1:
            item = _carregar()["itens"][achados[0]]
        elif len(achados) > 1:
            raise ValueError("Mais de um item com esse nome: " + "; ".join(achados[:6]) + ". Diga qual.")
        else:
            raise ValueError(f"Não há item '{nome}' no cofre. Use cofre_listar.")
    return _abrir(base64.b64decode(item["dados"])).decode("utf-8")


def listar() -> List[Dict[str, str]]:
    return [{"nome": k, "tipo": v.get("tipo", ""), "criado": v.get("criado", "")} for k, v in sorted(_carregar()["itens"].items())]


def apagar(nome: str) -> bool:
    n = _norm(nome)
    with _LOCK:
        d = _carregar()
        if n not in d["itens"]:
            return False
        del d["itens"][n]
        _gravar(d)
    return True


# ---------------------------------------------------------------- confirmacao em duas etapas
def novo_codigo(acao: str, nome: str) -> str:
    for k in [k for k, v in PENDENTES.items() if time.time() - v["criado"] > PENDENTE_TTL]:
        del PENDENTES[k]
    cod = secrets.token_hex(2)
    PENDENTES[cod] = {"acao": acao, "nome": _norm(nome), "criado": time.time()}
    return cod


def confirmar(codigo: Optional[str], acao: str, nome: str) -> bool:
    p = PENDENTES.get((codigo or "").strip())
    if p and p["acao"] == acao and p["nome"] == _norm(nome) and time.time() - p["criado"] <= PENDENTE_TTL:
        del PENDENTES[(codigo or "").strip()]
        return True
    return False


# ---------------------------------------------------------------- deteccao e mascara
def _luhn(num: str) -> bool:
    s, alt = 0, False
    for ch in reversed(num):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        s += d
        alt = not alt
    return s % 10 == 0


def _cpf_ok(c: str) -> bool:
    if len(c) != 11 or len(set(c)) == 1:
        return False
    for i in (9, 10):
        soma = sum(int(c[k]) * (i + 1 - k) for k in range(i))
        if int(c[i]) != (soma * 10 % 11) % 10:
            return False
    return True


def _cnpj_ok(c: str) -> bool:
    if len(c) != 14 or len(set(c)) == 1:
        return False
    for i, pesos in ((12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]), (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])):
        soma = sum(int(c[k]) * pesos[k] for k in range(i))
        r = soma % 11
        if int(c[i]) != (0 if r < 2 else 11 - r):
            return False
    return True


_NUM = re.compile(r"(?<![\d])(?:\d[ .\-/]?){11,48}(?![\d])")
_CHAVE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_\-]{20,}|AIza[0-9A-Za-z_\-]{35}|gh[pousr]_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16}|"
    r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})\b|Bearer\s+[A-Za-z0-9._\-]{20,}")
_SENHA = re.compile(
    r"\b(senha|password|passwd|pwd|pin|cvv|cvc|c[oó]digo de seguran[cç]a|token|segredo)\b(\s*(?:[:=]|\bé\b|\beh\b|\bis\b))\s*(\S{3,})",
    re.IGNORECASE)


def _achados_numericos(texto: str) -> List[Tuple[int, int, str]]:
    out = []
    for m in _NUM.finditer(texto):
        bruto = m.group(0)
        d = re.sub(r"\D", "", bruto)
        if len(d) in (47, 48):
            out.append((m.start(), m.end(), "boleto"))
        elif len(d) == 14 and _cnpj_ok(d):
            out.append((m.start(), m.end(), "CNPJ"))
        elif len(d) == 11 and _cpf_ok(d):
            out.append((m.start(), m.end(), "CPF"))
        elif 13 <= len(d) <= 19 and _luhn(d):
            out.append((m.start(), m.end(), "cartão"))
    return out


def detectar(texto: str) -> List[str]:
    """Tipos de dado sensivel no texto, do mais grave para o menos: senha, chave, cartão, boleto, CPF, CNPJ."""
    t = texto or ""
    achou: List[str] = []
    if _SENHA.search(t):
        achou.append("senha")
    if _CHAVE.search(t):
        achou.append("chave")
    for _, _, tipo in _achados_numericos(t):
        if tipo not in achou:
            achou.append(tipo)
    return achou


def mascarar(texto: str) -> str:
    """Troca dado sensivel por um marcador que nao revela o valor (ex.: 'cartão terminado em 1234')."""
    t = texto or ""
    t = _CHAVE.sub("[chave oculta]", t)
    t = _SENHA.sub(lambda m: f"{m.group(1)}{m.group(2)} [oculto]", t)
    achados = sorted(_achados_numericos(t), key=lambda a: -a[0])
    for ini, fim, tipo in achados:
        digs = re.sub(r"\D", "", t[ini:fim])
        fimdig = digs[-4:] if tipo in ("cartão", "boleto") else digs[-2:]
        t = t[:ini] + f"[{tipo} terminado em {fimdig}]" + t[fim:]
    return t


# ---------------------------------------------------------------- como falar sem soletrar errado
_SIMBOLOS = {"@": "arroba", "#": "jogo da velha", "$": "cifrão", "%": "por cento", "&": "e comercial", "*": "asterisco", "-": "hífen",
             "_": "sublinhado", "+": "mais", "=": "igual", "/": "barra", "\\": "barra invertida", ".": "ponto", ",": "vírgula",
             ":": "dois pontos", ";": "ponto e vírgula", "!": "exclamação", "?": "interrogação", "(": "abre parênteses",
             ")": "fecha parênteses", " ": "espaço", "'": "aspas simples", '"': "aspas", "<": "menor", ">": "maior",
             "[": "abre colchetes", "]": "fecha colchetes", "{": "abre chaves", "}": "fecha chaves", "|": "barra vertical",
             "~": "til", "^": "circunflexo", "`": "crase"}


def para_voz(segredo: str, modo: str = "auto") -> str:
    """Texto para a voz ler: numeros em grupos com pausa; senhas e chaves letra por letra, dizendo maiusculas e simbolos."""
    s = segredo
    solo = re.sub(r"[\s.\-/]", "", s)
    if modo == "auto":
        modo = "grupos" if solo.isdigit() else "letras"
    if modo == "grupos" and solo.isdigit():
        tam = 4 if len(solo) in (13, 14, 15, 16, 17, 18, 19, 8, 12, 47, 48) or len(solo) > 11 else 3
        grupos = [solo[i:i + tam] for i in range(0, len(solo), tam)]
        return ", ".join(" ".join(g) for g in grupos) + "."
    partes = []
    for ch in s:
        if ch.isdigit():
            partes.append(ch)
        elif ch.isalpha():
            partes.append(f"{ch.upper()} maiúsculo" if ch.isupper() else ch)
        else:
            partes.append(_SIMBOLOS.get(ch, "símbolo"))
    return ", ".join(partes) + "."


# ---------------------------------------------------------------- saidas seguras: voz e area de transferencia
async def falar(texto: str, devagar: bool = True) -> None:
    from blind_mcp.servers import speech

    await speech.speak(texto, -3 if devagar else 0)


def _ler_area() -> str:
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        return ""
    finally:
        win32clipboard.CloseClipboard()


def _escrever_area(texto: str) -> None:
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        if texto:
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, texto)
    finally:
        win32clipboard.CloseClipboard()


def ler_e_limpar_area() -> str:
    """Pega o que a pessoa copiou e limpa a area de transferencia, para o segredo nao ficar la."""
    t = _ler_area()
    if t:
        _escrever_area("")
    return t


def copiar_e_limpar_depois(segredo: str, segundos: int = 20) -> None:
    """Poe o segredo na area de transferencia para a pessoa colar e limpa sozinho depois, se ninguem copiou outra coisa."""
    _escrever_area(segredo)

    def limpar() -> None:
        try:
            if _ler_area() == segredo:
                _escrever_area("")
        except Exception:  # noqa: BLE001
            pass

    t = threading.Timer(max(5, min(int(segundos), 120)), limpar)
    t.daemon = True
    t.start()
