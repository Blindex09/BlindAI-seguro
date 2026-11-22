"""Servidor MCP `blind-system`: diagnostico SOMENTE LEITURA do computador, pensado para uma pessoa cega.

Nada aqui aperta tecla, move o mouse ou muda configuracao. Ferramentas:
- acoes_recentes: o diario do que as ferramentas do Blind fizeram (para achar a causa de um travamento).
- saude_teclado: teclas presas, Teclas de Aderencia/Filtragem, quantas copias do Windows-MCP rodam.
- trabalho_nao_salvo: janelas com titulo de documento nao salvo (para a regra "pergunte se quer salvar").
"""

from __future__ import annotations

import ctypes
import re
from ctypes import wintypes
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from . import _audit
from ._common import run_blocking

mcp = FastMCP("blind-system")


@mcp.tool()
async def acoes_recentes(limite: int = 15, servidor: str = "") -> Dict[str, Any]:
    """Mostra o que as ferramentas do Blind fizeram por ultimo (mais recente primeiro): servidor, ferramenta, hora,
    se deu certo e quanto demorou. 'sem_fim' = comecou e nao terminou (pode ser a causa de um travamento).
    Use quando a pessoa perguntar 'o que voce fez?' ou depois de o teclado travar. `servidor` filtra (ex: agent-desktop)."""
    rows = await run_blocking(_audit.read_recent, limite, servidor)
    sem_fim = [r for r in rows if r.get("sem_fim")]
    return {
        "ok": True,
        "total": len(rows),
        "acoes": rows,
        "aviso": ("Algumas acoes nao tem fim registrado: o servidor pode ter sido fechado no meio, ou ainda estar rodando."
                  if sem_fim else ""),
        "nota": "So registra ferramentas proprias do Blind. windows e blind-commander sao de terceiros e nao entram aqui.",
        "arquivo": str(_audit.AUDIT_FILE),
    }


# --------------------------- saude do teclado ---------------------------

_VK = {"Shift": 0x10, "Ctrl": 0x11, "Alt": 0x12, "Windows esquerda": 0x5B, "Windows direita": 0x5C}


class _STICKY(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD)]


class _FILTER(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD), ("iWaitMSec", wintypes.DWORD),
                ("iDelayMSec", wintypes.DWORD), ("iRepeatMSec", wintypes.DWORD), ("iBounceMSec", wintypes.DWORD)]


class _LASTINPUT(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def _keyboard_health_sync() -> Dict[str, Any]:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    problemas: List[str] = []

    presas = [nome for nome, vk in _VK.items() if user32.GetAsyncKeyState(vk) & 0x8000]
    if presas:
        problemas.append("Tecla(s) pressionada(s) agora: " + ", ".join(presas)
                         + ". Se voce nao esta segurando, aperte e solte cada uma para liberar.")

    sticky, filt = _STICKY(ctypes.sizeof(_STICKY), 0), _FILTER(ctypes.sizeof(_FILTER), 0, 0, 0, 0, 0)
    user32.SystemParametersInfoW(0x003A, ctypes.sizeof(sticky), ctypes.byref(sticky), 0)  # SPI_GETSTICKYKEYS
    user32.SystemParametersInfoW(0x0032, ctypes.sizeof(filt), ctypes.byref(filt), 0)  # SPI_GETFILTERKEYS
    teclas_aderencia = bool(sticky.dwFlags & 0x1)
    filtragem = bool(filt.dwFlags & 0x1)
    if teclas_aderencia:
        problemas.append("Teclas de Aderencia ligadas: Shift, Ctrl ou Alt podem ficar presas.")
    if filtragem:
        problemas.append("Filtragem de Teclas ligada: o Windows ignora ou atrasa teclas (segurar Shift 8 segundos liga isso).")

    # Mouse: botoes presos, botoes trocados, Teclas do Mouse (teclado numerico vira mouse) e cursor preso em uma area.
    botoes = {"esquerdo": 0x01, "direito": 0x02, "meio": 0x04}
    mouse_presos = [n for n, vk in botoes.items() if user32.GetAsyncKeyState(vk) & 0x8000]
    if mouse_presos:
        problemas.append("Botao(oes) do mouse pressionado(s) agora: " + ", ".join(mouse_presos) + ".")
    botoes_trocados = bool(user32.GetSystemMetrics(23))  # SM_SWAPBUTTON
    class _MOUSEKEYS(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD), ("iMaxSpeed", wintypes.DWORD),
                    ("iTimeToMaxSpeed", wintypes.DWORD), ("iCtrlSpeed", wintypes.DWORD), ("dwReserved1", wintypes.DWORD),
                    ("dwReserved2", wintypes.DWORD)]
    mkeys = _MOUSEKEYS(ctypes.sizeof(_MOUSEKEYS), 0, 0, 0, 0, 0, 0)
    user32.SystemParametersInfoW(0x0036, ctypes.sizeof(mkeys), ctypes.byref(mkeys), 0)  # SPI_GETMOUSEKEYS
    teclas_do_mouse = bool(mkeys.dwFlags & 0x1)
    if teclas_do_mouse:
        problemas.append("Teclas do Mouse ligadas: o teclado numerico move o cursor e pode 'comer' numeros.")
    rect = wintypes.RECT()
    cursor_preso = False
    if user32.GetClipCursor(ctypes.byref(rect)):
        w, h = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)  # tela virtual inteira
        cursor_preso = (rect.right - rect.left) < w or (rect.bottom - rect.top) < h
    if cursor_preso:
        problemas.append("O cursor do mouse esta preso a uma area menor que a tela (algum programa usou ClipCursor).")

    li = _LASTINPUT(ctypes.sizeof(_LASTINPUT), 0)
    ultima_entrada_s = None
    if user32.GetLastInputInfo(ctypes.byref(li)):
        ultima_entrada_s = round((kernel32.GetTickCount() - li.dwTime) / 1000.0, 1)

    # Copias do Windows-MCP e se o controle de teclado/mouse delas esta ligado.
    copias: List[Dict[str, Any]] = []
    try:
        import psutil

        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            cmd = " ".join(p.info.get("cmdline") or [])
            low = cmd.lower()
            if "windows-mcp" in low and " serve" in low:  # so o servidor; nao um comando que apenas cita o nome
                # Conta so o processo Python que de fato roda o servidor (e instala ganchos): ignora uv, o lancador
                # windows-mcp.exe e shells cujo texto de comando apenas cita o nome.
                if (p.info.get("name") or "").lower() not in {"python.exe", "pythonw.exe"}:
                    continue
                controle = "desconhecido"
                excl = ""
                try:
                    env = p.environ()
                    controle = env.get("WINDOWS_MCP_CONTROL", "(padrao: ligado)")
                    excl = env.get("WINDOWS_MCP_EXCLUDE_TOOLS", "")
                except Exception:  # noqa: BLE001
                    pass
                origem = ""
                try:  # quem abriu: sobe a cadeia ate achar o app (Claude.exe, claude.exe, node, etc.)
                    q = p.parent()
                    while q is not None and q.name().lower() in {"uv.exe", "windows-mcp.exe", "cmd.exe", "python.exe"}:
                        q = q.parent()
                    origem = q.name() if q is not None else ""
                except Exception:  # noqa: BLE001
                    pass
                import datetime as _dt

                copias.append({
                    "pid": p.info["pid"],
                    "aberto_por": origem,
                    "desde": _dt.datetime.fromtimestamp(p.create_time()).strftime("%d/%m %H:%M"),
                    "WINDOWS_MCP_CONTROL": controle,
                    "ferramentas_excluidas": excl,
                })
    except Exception:  # noqa: BLE001
        copias = []
    com_controle = [c for c in copias if str(c["WINDOWS_MCP_CONTROL"]).lower() not in {"false", "0", "no", "off"}]
    if com_controle:
        problemas.append(f"{len(com_controle)} copia(s) do Windows-MCP com controle de teclado/mouse LIGADO "
                         "(ganchos globais que ja foram suspeitos de travar o teclado). Provavelmente abertas antes da "
                         "configuracao segura: feche e abra o Claude de novo (pelo icone da bandeja > Sair).")

    ok = not problemas
    return {
        "ok": True,
        "tudo_certo": ok,
        "resumo": "Teclado e mouse sem sinais de problema." if ok else " ".join(problemas),
        "botoes_mouse_pressionados": mouse_presos,
        "botoes_do_mouse_trocados": botoes_trocados,
        "teclas_do_mouse": teclas_do_mouse,
        "cursor_preso_em_area": cursor_preso,
        "teclas_pressionadas": presas,
        "teclas_de_aderencia": teclas_aderencia,
        "filtragem_de_teclas": filtragem,
        "segundos_desde_a_ultima_entrada": ultima_entrada_s,
        "copias_windows_mcp": copias,
        "limite": "Nao da para listar todos os ganchos de teclado do Windows; so as copias conhecidas do Windows-MCP.",
        "se_travar": "Aperte e solte Shift, Ctrl, Alt e a tecla Windows, uma de cada vez. Depois Ctrl+Alt+Del. "
                     "Depois diga qual ferramenta foi usada por ultimo (acoes_recentes).",
    }


@mcp.tool()
async def saude_teclado() -> Dict[str, Any]:
    """Confere, sem alterar nada, se ha sinais de problema no teclado E no mouse: teclas e botoes presos, Teclas de
    Aderencia, Filtragem de Teclas, Teclas do Mouse, botoes trocados, cursor preso numa area e copias do Windows-MCP com
    controle ligado. Use quando a pessoa disser que o teclado ou o mouse esta estranho."""
    return await run_blocking(_keyboard_health_sync)


# --------------------------- trabalho nao salvo ---------------------------

_UNSAVED = re.compile(r"^\s*\*|\*\s*$|modificad|n[aã]o salv|unsaved|\(modified\)|•\s*$", re.IGNORECASE)
_IGNORE_TITLES = {"", "program manager", "settings", "windows input experience"}


def _unsaved_sync() -> Dict[str, Any]:
    user32 = ctypes.windll.user32
    found: List[Dict[str, Any]] = []
    all_titles = 0
    pid_name: Dict[int, str] = {}
    try:
        import psutil
    except Exception:  # noqa: BLE001
        psutil = None  # type: ignore[assignment]

    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd: int, _lp: int) -> bool:
        nonlocal all_titles
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        if title.strip().lower() in _IGNORE_TITLES:
            return True
        all_titles += 1
        if _UNSAVED.search(title):
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            app = pid_name.get(pid.value)
            if app is None and psutil is not None:
                try:
                    app = psutil.Process(pid.value).name()
                except Exception:  # noqa: BLE001
                    app = ""
                pid_name[pid.value] = app
            found.append({"titulo": title, "app": app or "", "pid": pid.value})
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return {
        "ok": True,
        "janelas_verificadas": all_titles,
        "encontradas": len(found),
        "janelas": found,
        "resumo": (f"{len(found)} janela(s) com trabalho que parece nao salvo: " + "; ".join(f['titulo'] for f in found)
                   if found else "Nenhuma janela com sinal de trabalho nao salvo no titulo."),
        "limite": ("So le o titulo da janela (asterisco, 'Modificado', 'nao salvo'). Abas em segundo plano, como no Bloco de "
                   "Notas do Windows 11, nao aparecem no titulo: o Bloco de Notas restaura abas nao salvas ao abrir."),
        "regra": "Se houver trabalho nao salvo: pergunte se quer salvar. Sim = salvar; nao = descartar so esse. Pergunte a cada vez.",
    }


@mcp.tool()
async def trabalho_nao_salvo() -> Dict[str, Any]:
    """Procura janelas abertas cujo titulo indica documento nao salvo (asterisco, 'Modificado', 'nao salvo'). So le.
    Chame antes de fechar apps ou abrir uma sessao nova em um editor, e siga a regra de perguntar se quer salvar."""
    return await run_blocking(_unsaved_sync)


# --------------------------- vigia automatico ---------------------------

@mcp.tool()
async def vigia_status() -> Dict[str, Any]:
    """Mostra o vigia automatico de teclado e mouse: o que ele corrigiu sozinho (teclas soltas, recursos desligados, copias
    inseguras do Windows-MCP encerradas). Ele roda em silencio; so consulte se a pessoa perguntar."""
    from . import _vigia

    v = _vigia._INSTANCE
    cfg = _vigia.load_config()
    return {
        "ok": True,
        "rodando": v is not None,
        "verificacoes_feitas": v.ticks if v else 0,
        "configuracao": cfg,
        "eventos_recentes": list(reversed(v.events))[:15] if v else [],
        "o_que_faz": [
            "Tudo em silencio e em segundo plano: nunca fala, nunca abre janela, nunca interrompe a pessoa.",
            "Shift/Ctrl/Alt/Windows ou botao do mouse preso: solta sozinho (so envia o 'soltar').",
            "Aderencia, Filtragem de Teclas ou Teclas do Mouse que ligaram sozinhas na sessao: desliga de volta.",
            "Windows-MCP com controle de teclado/mouse ligado: encerra a copia.",
        ],
        "limite": "Protege enquanto o blind-system estiver rodando. Nao conserta gancho de teclado de outro programa que engole teclas.",
    }


@mcp.tool()
async def vigia_configurar(
    ligado: Optional[bool] = None,
    avisar_por_voz: Optional[bool] = None,
    liberar_teclas_presas: Optional[bool] = None,
    encerrar_copias_inseguras: Optional[bool] = None,
    restaurar_recursos_de_acessibilidade: Optional[bool] = None,
) -> Dict[str, Any]:
    """Muda o vigia automatico (so quando a pessoa pedir; ela decide). Por padrao ele corrige tudo em silencio; `avisar_por_voz`
    (desligado) faria ele falar, o que interrompe a pessoa. Valores omitidos nao mudam."""
    from . import _vigia

    cfg = await run_blocking(_vigia.save_config, {"ligado": ligado, "avisar_por_voz": avisar_por_voz,
                                                  "liberar_teclas_presas": liberar_teclas_presas,
                                                  "encerrar_copias_inseguras": encerrar_copias_inseguras,
                                                  "restaurar_recursos_de_acessibilidade": restaurar_recursos_de_acessibilidade})
    return {"ok": True, "configuracao": cfg}


if __name__ == "__main__":
    from . import _vigia

    _vigia.start()
    _audit.install_audit(mcp, "blind-system")
    mcp.run()
