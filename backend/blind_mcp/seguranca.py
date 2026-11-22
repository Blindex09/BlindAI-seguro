"""Regras de seguranca do Blind (decisao do usuario, 18/11/2026). Valem para TODAS as ferramentas do Blind, no Claude
(lazy_proxy) e no Electron (manager), e dentro do blind-docs (gravacao).

O Blind NUNCA pode:
- apagar, mover ou sobrescrever nada em C:\\Windows nem em Program Files (Program Files, Program Files (x86), ProgramW6432);
- gravar no Registro (criar, alterar ou apagar chave ou valor). Ler continua livre;
- desligar ou reiniciar o computador;
- deixar o computador sem som (mudo, ou volume abaixo de 15%) nem apagar a tela (tela desligada, brilho abaixo de 20%).
  Abaixar um pouco e aumentar pode.
- gravar arquivos com o blind-docs fora de Downloads, Documentos, Musicas e Videos (subpastas dentro delas pode).

Limite honesto: um comando livre de PowerShell pode ser escrito de muitos jeitos. A conferencia abaixo pega os jeitos comuns e
recusa na duvida (volume ou brilho que nao da para conferir), mas nao e uma muralha contra quem se esforce para burlar.
"""

from __future__ import annotations

import ctypes
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

VOLUME_MINIMO = 15  # por cento
BRILHO_MINIMO = 20  # por cento


class BloqueioDeSeguranca(RuntimeError):
    """A chamada foi recusada por uma regra de seguranca do Blind."""


# ------------------------------------------------------------------------------ caminhos
def _norm(p: str | os.PathLike) -> str:
    s = os.path.expandvars(os.path.expanduser(str(p)))
    try:
        s = os.path.realpath(s)  # resolve .., junctions e nomes curtos (PROGRA~1)
    except OSError:
        s = os.path.abspath(s)
    return os.path.normcase(os.path.normpath(s))


def _sob(caminho: str, raiz: str) -> bool:
    return caminho == raiz or caminho.startswith(raiz.rstrip("\\/") + os.sep)


def _pastas_protegidas() -> List[str]:
    raizes: List[str] = []
    for var in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        v = os.environ.get(var)
        if v:
            raizes.append(_norm(v))
    drive = os.environ.get("SystemDrive") or "C:"
    raizes += [_norm(drive + "\\Windows"), _norm(drive + "\\Program Files"), _norm(drive + "\\Program Files (x86)")]
    return sorted(set(raizes))


def _known_folder(guid: str) -> Optional[str]:
    """Pasta conhecida do Windows (acompanha OneDrive e nome traduzido)."""
    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes

        class _GUID(ctypes.Structure):
            _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

        u = uuid.UUID(guid)
        g = _GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        ptr = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(ptr)) != 0:
            return None
        try:
            return ptr.value
        finally:
            ctypes.windll.ole32.CoTaskMemFree(ptr)
    except Exception:  # noqa: BLE001
        return None


_KNOWN = {
    "Documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "Downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "Music": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "Videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
}


def pastas_de_gravacao() -> List[Path]:
    """Downloads, Documentos, Musicas e Videos da pessoa (mais BLIND_PASTAS_EXTRAS, separado por ';', para testes)."""
    achadas: List[str] = []
    home = Path.home()
    for nome, guid in _KNOWN.items():
        kf = _known_folder(guid)
        if kf:
            achadas.append(kf)
        achadas.append(str(home / nome))
    extras = os.environ.get("BLIND_PASTAS_EXTRAS", "")
    achadas += [e for e in extras.split(";") if e.strip()]
    vistas: List[Path] = []
    for a in achadas:
        pa = Path(a)
        if pa not in vistas:
            vistas.append(pa)
    return vistas


def caminho_protegido(caminho: str | os.PathLike) -> bool:
    """True se o caminho esta em C:\\Windows ou Program Files (ou e uma dessas pastas)."""
    n = _norm(caminho)
    return any(_sob(n, r) for r in _pastas_protegidas())


def conferir_gravacao_blind_docs(caminho: str | os.PathLike) -> None:
    """Levanta BloqueioDeSeguranca se o blind-docs for gravar fora de Downloads, Documentos, Musicas ou Videos."""
    if not str(caminho).strip():
        raise BloqueioDeSeguranca("Faltou o caminho do arquivo a gravar.")
    n = _norm(caminho)
    if caminho_protegido(n):
        raise BloqueioDeSeguranca("Regra de segurança do Blind: não gravo nada em Windows nem em Arquivos de Programas.")
    if not any(_sob(n, _norm(r)) for r in pastas_de_gravacao()):
        raise BloqueioDeSeguranca(
            "Regra de segurança do Blind: só gravo documentos em Downloads, Documentos, Músicas e Vídeos "
            "(ou em pastas dentro delas). Escolha uma dessas.")


# ------------------------------------------------------------------------------ texto de comando
_PROT = (
    r"(?:[a-z]:\\+windows(?![\w.-])|[a-z]:\\+program\s*files|[a-z]:\\+progra~\d|"
    r"%(?:systemroot|windir|programfiles(?:\(x86\))?|programw6432)%|"
    r"\$env:(?:systemroot|windir|programfiles(?:\(x86\))?|programw6432)|\$\{env:(?:systemroot|windir|programfiles|programw6432)|"
    r"\\systemroot\b|\\\\\?\\[a-z]:\\windows|\\\\\?\\[a-z]:\\program)"
)
_RE_PROT = re.compile(_PROT, re.IGNORECASE)
_RE_DESTRUTIVO = re.compile(
    r"(?<![\w-])(?:remove-item|ri|rm|del|erase|rd|rmdir|move-item|mi|mv|move|ren|rename|rename-item|rni|set-content|add-content|"
    r"clear-content|out-file|new-item|ni|set-acl|takeown|icacls|attrib|format|cipher|robocopy|sdelete|"
    r"\[io\.(?:file|directory)\]::(?:delete|move|write\w*|create\w*|replace)|\.delete\(|\.moveto\(|writeall\w+)(?![\w-])|>>?\s*[\"']?[a-z]:",
    re.IGNORECASE,
)
_RE_DESLIGAR = re.compile(
    r"(?<![\w-])(?:shutdown(?:\.exe)?|stop-computer|restart-computer|tsshutdn|psshutdown|win32shutdown|initiatesystemshutdown\w*|"
    r"exitwindowsex|slidetoshutdown|wmic\b[^|;&\n]*\b(?:reboot|shutdown))(?![\w-])",
    re.IGNORECASE,
)
_RE_REG_CMD = re.compile(r"(?<![\w-])(?:reg(?:\.exe)?\s+(?:add|delete|import|load|unload|restore|copy)|regedit(?:32)?(?:\.exe)?|regini|regedt32)(?![\w-])", re.IGNORECASE)
_RE_REG_PS = re.compile(
    r"(?:(?:new|set|remove|rename|copy|move|clear)-item(?:property)?|\bsp\b|\bsi\b|\bri\b|\bni\b|\brp\b|\bnp\b)[^\n;|]*"
    r"(?:hk(?:lm|cu|cr|u|cc)\s*:|hkey_|registry::)", re.IGNORECASE)
_RE_REG_NET = re.compile(r"(?:setvalue|deletevalue|deletesubkey\w*|createsubkey|openremotebasekey)\s*\(", re.IGNORECASE)
_RE_MUDO = re.compile(r"setmute|mutesysvolume|\[char\]\s*173|vk_volume_mute|0xad\b|\bmute\b|volume_?mute|silenciar|\bmudo\b", re.IGNORECASE)
_RE_TELA_OFF = re.compile(
    r"sc_monitorpower|0xf170|monitorpower|nircmd(?:c)?(?:\.exe)?\s+monitor\s+(?:off|async_off)|monitor\s*off|"
    r"powercfg\b[^\n;|]*(?:monitor-timeout|video-timeout|videoidle|vidaidle)|turnoffdisplay|set-displaypower", re.IGNORECASE)
_RE_VOL_SET = re.compile(r"(?:setmastervolumelevelscalar|setsysvolume|changesysvolume|setmastervolumelevel\b|master\.?volume|\bvolume\s*=)\s*[\(\s:=]*(-?\d+(?:[.,]\d+)?)", re.IGNORECASE)
_RE_VOL_API = re.compile(r"setmastervolumelevel\w*|setsysvolume|changesysvolume|iaudioendpointvolume|audioendpointvolume|\[audio\]::volume|set-volume", re.IGNORECASE)
_RE_BRILHO = re.compile(r"wmisetbrightness\s*\(\s*[^,)]*,\s*(-?\d+)|setmonitorbrightness|setbrightness\w*|setdevicegammaramp|brightnesslevel\s*=\s*(-?\d+)", re.IGNORECASE)


def _achatar(args: Any) -> str:
    """Todos os textos dos argumentos, juntos (com / virando \\ para casar caminhos)."""
    if isinstance(args, dict):
        partes = [_achatar(v) for v in args.values()]
    elif isinstance(args, (list, tuple)):
        partes = [_achatar(v) for v in args]
    elif args is None:
        partes = []
    else:
        partes = [str(args)]
    return "\n".join(partes)


def _volume_pct(valor: float, nome: str) -> float:
    if "setsysvolume" in nome.lower() or valor > 1.0:
        return valor / 655.35 if valor > 100 else valor
    return valor * 100.0


def conferir_texto_de_comando(texto: str) -> None:
    """Confere um comando de shell/PowerShell/CMD. Levanta BloqueioDeSeguranca se quebrar uma regra."""
    if not texto or not texto.strip():
        return
    t = texto.replace("/", "\\")
    if _RE_DESLIGAR.search(texto):
        raise BloqueioDeSeguranca("Regra de segurança do Blind: não desligo nem reinicio o computador.")
    if _RE_REG_CMD.search(texto) or _RE_REG_PS.search(texto) or _RE_REG_NET.search(texto):
        raise BloqueioDeSeguranca("Regra de segurança do Blind: não crio, altero nem apago nada no Registro. Ler pode.")
    if _RE_PROT.search(t) and _RE_DESTRUTIVO.search(t):
        raise BloqueioDeSeguranca("Regra de segurança do Blind: não apago, movo nem altero arquivos de Windows ou de Arquivos de Programas.")
    if _RE_MUDO.search(texto):
        raise BloqueioDeSeguranca("Regra de segurança do Blind: não deixo o computador sem som.")
    if _RE_TELA_OFF.search(texto):
        raise BloqueioDeSeguranca("Regra de segurança do Blind: não apago nem desligo a tela.")
    if _RE_VOL_API.search(texto) or _RE_VOL_SET.search(texto):
        achou = list(_RE_VOL_SET.finditer(texto))
        if not achou:
            raise BloqueioDeSeguranca("Regra de segurança do Blind: não consigo conferir esse ajuste de volume, então não faço.")
        for m in achou:
            v = float(m.group(1).replace(",", "."))
            nome = m.group(0)
            if "change" in nome.lower():  # delta: so abaixar um pouco (ate 20%)
                if v < -0.2 * (65535 if abs(v) > 100 else 1):
                    raise BloqueioDeSeguranca("Regra de segurança do Blind: só abaixo o volume um pouco por vez.")
            elif _volume_pct(v, nome) < VOLUME_MINIMO:
                raise BloqueioDeSeguranca(f"Regra de segurança do Blind: o volume nunca fica abaixo de {VOLUME_MINIMO} por cento.")
    for m in _RE_BRILHO.finditer(texto):
        n = m.group(1) or m.group(2)
        if n is None or int(n) < BRILHO_MINIMO:
            raise BloqueioDeSeguranca(f"Regra de segurança do Blind: o brilho nunca fica abaixo de {BRILHO_MINIMO} por cento.")


def _conferir_teclas(keys: str, repetir: int = 1) -> None:
    k = (keys or "").lower().replace(" ", "").replace("-", "_")
    if "volumemute" in k or "volume_mute" in k or "audiomute" in k:
        raise BloqueioDeSeguranca("Regra de segurança do Blind: não deixo o computador sem som.")
    if ("volumedown" in k or "volume_down" in k) and (k.count("volume") > 3 or repetir > 3):
        raise BloqueioDeSeguranca("Regra de segurança do Blind: só abaixo o volume um pouco por vez (até três toques).")
    if re.search(r"brightness(?:down)?|monitorbrightness", k) and k.count("brightness") > 3:
        raise BloqueioDeSeguranca("Regra de segurança do Blind: só diminuo o brilho um pouco por vez.")


# ------------------------------------------------------------------------------ ponto de entrada das chamadas
_ESCRITA_COMMANDER = {"write_file": ("path",), "edit_block": ("file_path",), "write_pdf": ("path", "outputPath"),
                      "create_directory": ("path",), "move_file": ("source", "destination")}
_TEXTO_COMMANDER = {"start_process": "command", "interact_with_process": "input"}


def verificar_chamada(server: str, tool: str, args: Optional[Dict[str, Any]]) -> None:
    """Chame antes de qualquer ferramenta. Levanta BloqueioDeSeguranca com a frase que a pessoa deve ouvir."""
    a: Dict[str, Any] = args or {}
    srv, nome = (server or "").lower(), tool or ""
    if srv == "windows":
        if nome == "Registry" and str(a.get("mode", "get")).lower() not in ("get", "list"):
            raise BloqueioDeSeguranca("Regra de segurança do Blind: não crio, altero nem apago nada no Registro. Ler pode.")
        if nome == "FileSystem":
            modo = str(a.get("mode", "")).lower()
            alvos = []
            if modo in ("write", "move", "delete"):
                alvos.append(a.get("path"))  # copiar DE la e leitura; mover, gravar e apagar nao
            if modo in ("write", "copy", "move"):
                alvos.append(a.get("destination"))
            if any(x and caminho_protegido(x) for x in alvos):
                raise BloqueioDeSeguranca(
                    "Regra de segurança do Blind: não apago, movo nem altero arquivos de Windows ou de Arquivos de Programas.")
        if nome in ("PowerShell", "App"):
            conferir_texto_de_comando(_achatar({k: v for k, v in a.items() if k in ("command", "name", "executable", "args", "cwd")}))
    elif srv == "blind-commander":
        for campo in _ESCRITA_COMMANDER.get(nome, ()):
            if a.get(campo) and caminho_protegido(a[campo]):
                raise BloqueioDeSeguranca("Regra de segurança do Blind: não apago, movo nem altero arquivos de Windows ou de Arquivos de Programas.")
        if nome in _TEXTO_COMMANDER:
            conferir_texto_de_comando(_achatar(a.get(_TEXTO_COMMANDER[nome])))
    elif srv == "agent-desktop":
        if nome == "press_keys":
            _conferir_teclas(str(a.get("keys", "")), int(a.get("repeat", 1) or 1))
        elif nome == "launch_app":
            conferir_texto_de_comando(str(a.get("target", "")))
