"""Vigia automatico de teclado e mouse (roda sozinho dentro de `blind-system`; a pessoa nao precisa chamar nada).

REGRA: nunca interromper a pessoa. Tudo e corrigido em silencio, em segundo plano (sem voz, sem janela, sem aviso); so vai
para o diario de acoes. A cada 2 segundos, so LENDO o estado, e corrigindo:
- Tecla modificadora (Shift, Ctrl, Alt, Windows) ou botao do mouse parado "apertado" por muito tempo = tecla presa:
  LIBERA (envia so o "soltar" daquela tecla/botao, nunca um aperto).
- Teclas de Aderencia / Filtragem de Teclas / Teclas do Mouse que LIGARAM sozinhas durante a sessao (estavam desligadas
  quando o vigia comecou): desliga de volta. Se ja estavam ligadas no inicio, e escolha da pessoa e nao mexe.
- Copia do Windows-MCP com controle de teclado/mouse ligado (ganchos globais que engolem teclas): encerra.
Limites honestos: protege so enquanto o servidor blind-system esta rodando (Claude aberto) e nao consegue consertar um gancho
de teclado de outro programa desconhecido. Configuracao em <BLIND_DATA_DIR>/vigia.json.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from ._audit import write_entry
from ._common import BACKEND_DIR

DATA_DIR = Path(os.environ.get("BLIND_DATA_DIR") or (BACKEND_DIR / "data"))
CONFIG_FILE = DATA_DIR / "vigia.json"

DEFAULTS: Dict[str, Any] = {
    "ligado": True,
    "avisar_por_voz": False,  # a pessoa nao pode ser interrompida: so voz se ela pedir
    "liberar_teclas_presas": True,
    "encerrar_copias_inseguras": True,
    "restaurar_recursos_de_acessibilidade": True,
    "segundos_aviso_modificador": 12.0,
    "segundos_liberar_modificador": 25.0,
    "segundos_aviso_mouse": 30.0,
    "segundos_liberar_mouse": 45.0,
    "intervalo_s": 2.0,
}

_MODIFIERS = {"Shift": (0x10, 0xA0, 0xA1), "Ctrl": (0x11, 0xA2, 0xA3), "Alt": (0x12, 0xA4, 0xA5), "Windows": (0x5B, 0x5C)}
_MOUSE = {"esquerdo": 0x01, "direito": 0x02, "meio": 0x04}


def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    try:
        cfg.update({k: v for k, v in json.loads(CONFIG_FILE.read_text(encoding="utf-8")).items() if k in DEFAULTS})
    except Exception:  # noqa: BLE001
        pass
    return cfg


def save_config(changes: Dict[str, Any]) -> Dict[str, Any]:
    cfg = load_config()
    for k, v in changes.items():
        if k in DEFAULTS and v is not None:
            cfg[k] = type(DEFAULTS[k])(v)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


# ------------------------------ acesso ao Windows (substituivel nos testes) ------------------------------

class WinApi:
    """So leitura, exceto release_*: que envia o SOLTAR (key-up / button-up) de algo que ja esta apertado."""

    def __init__(self) -> None:
        self.user32 = ctypes.windll.user32

    def pressed(self) -> Set[str]:
        out: Set[str] = set()
        for name, vks in _MODIFIERS.items():
            if any(self.user32.GetAsyncKeyState(vk) & 0x8000 for vk in vks):
                out.add(name)
        for name, vk in _MOUSE.items():
            if self.user32.GetAsyncKeyState(vk) & 0x8000:
                out.add("mouse " + name)
        return out

    def release(self, name: str) -> None:
        if name.startswith("mouse "):
            flags = {"esquerdo": 0x0004, "direito": 0x0010, "meio": 0x0040}[name[6:]]  # MOUSEEVENTF_*UP
            self.user32.mouse_event(flags, 0, 0, 0, 0)
            return
        for vk in _MODIFIERS[name]:
            self.user32.keybd_event(vk, 0, 0x0002, 0)  # KEYEVENTF_KEYUP

    def accessibility_flags(self) -> Dict[str, bool]:
        from ctypes import wintypes

        class S(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD)]

        class F(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD), ("a", wintypes.DWORD), ("b", wintypes.DWORD),
                        ("c", wintypes.DWORD), ("d", wintypes.DWORD)]

        class M(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD), ("a", wintypes.DWORD), ("b", wintypes.DWORD),
                        ("c", wintypes.DWORD), ("d", wintypes.DWORD), ("e", wintypes.DWORD)]

        s, f, m = S(ctypes.sizeof(S), 0), F(ctypes.sizeof(F), 0, 0, 0, 0, 0), M(ctypes.sizeof(M), 0, 0, 0, 0, 0, 0)
        self.user32.SystemParametersInfoW(0x003A, ctypes.sizeof(s), ctypes.byref(s), 0)
        self.user32.SystemParametersInfoW(0x0032, ctypes.sizeof(f), ctypes.byref(f), 0)
        self.user32.SystemParametersInfoW(0x0036, ctypes.sizeof(m), ctypes.byref(m), 0)
        return {"Teclas de Aderencia": bool(s.dwFlags & 1), "Filtragem de Teclas": bool(f.dwFlags & 1),
                "Teclas do Mouse": bool(m.dwFlags & 1)}

    def disable_flag(self, flag: str) -> bool:
        """Desliga Aderencia/Filtragem/Teclas do Mouse (le a estrutura, limpa so o bit 'ligado', grava de volta)."""
        from ctypes import wintypes

        get, setp, extra = {"Teclas de Aderencia": (0x003A, 0x003B, 0), "Filtragem de Teclas": (0x0032, 0x0033, 4),
                            "Teclas do Mouse": (0x0036, 0x0037, 5)}[flag]
        fields = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD)] + [(f"x{i}", wintypes.DWORD) for i in range(extra)]
        S = type("S", (ctypes.Structure,), {"_fields_": fields})
        st = S()
        st.cbSize = ctypes.sizeof(S)
        if not self.user32.SystemParametersInfoW(get, ctypes.sizeof(S), ctypes.byref(st), 0):
            return False
        st.dwFlags &= ~1
        return bool(self.user32.SystemParametersInfoW(setp, ctypes.sizeof(S), ctypes.byref(st), 3))  # UPDATEINIFILE|SENDCHANGE

    def unsafe_windows_mcp(self) -> List[Dict[str, Any]]:
        import psutil

        out = []
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            low = " ".join(p.info.get("cmdline") or []).lower()
            if "windows-mcp" in low and " serve" in low and (p.info.get("name") or "").lower() in {"python.exe", "pythonw.exe"}:
                try:
                    control = str(p.environ().get("WINDOWS_MCP_CONTROL", "")).lower()
                except Exception:  # noqa: BLE001
                    continue
                if control not in {"false", "0", "no", "off"}:
                    out.append({"pid": p.info["pid"]})
        return out

    def terminate_tree_of(self, pid: int) -> bool:
        import psutil

        try:
            p = psutil.Process(pid)
            top = p
            while top.parent() is not None and top.parent().name().lower() in {"uv.exe", "windows-mcp.exe", "python.exe"}:
                top = top.parent()
            tree = top.children(recursive=True) + [top]
            for t in tree:
                try:
                    t.terminate()
                except Exception:  # noqa: BLE001
                    pass
            psutil.wait_procs(tree, timeout=6)
            return True
        except Exception:  # noqa: BLE001
            return False


def speak_sapi(text: str) -> None:
    clean = text.replace("'", " ").replace('"', " ")
    cmd = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
           f"$s.Speak('{clean}')")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, timeout=25,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:  # noqa: BLE001
        pass


# ------------------------------ logica ------------------------------

class Vigia:
    def __init__(self, api: Any = None, clock: Callable[[], float] = time.monotonic,
                 speak: Callable[[str], None] = speak_sapi, log: Callable[[Dict[str, Any]], None] = write_entry,
                 config: Callable[[], Dict[str, Any]] = load_config, leader: Any = None) -> None:
        self.leader = leader  # so a copia dona age (varias copias do servidor podem rodar ao mesmo tempo)
        self.api = api or WinApi()
        self.clock = clock
        self.speak = speak
        self.log = log
        self.config = config
        self.since: Dict[str, float] = {}
        self.warned: Set[str] = set()
        self.alerted_flags: Set[str] = set()
        try:
            self.baseline_on: Set[str] = {k for k, on in self.api.accessibility_flags().items() if on}
        except Exception:  # noqa: BLE001
            self.baseline_on = set()
        self.alerted_pids: Set[int] = set()
        self.events: List[Dict[str, Any]] = []
        self._last_unsafe_check = -1e9
        self.ticks = 0

    def _say(self, msg: str, cfg: Dict[str, Any]) -> None:
        if cfg["avisar_por_voz"]:
            threading.Thread(target=self.speak, args=(msg,), daemon=True).start()

    def _event(self, kind: str, detail: str, cfg: Dict[str, Any], voice: Optional[str] = None) -> None:
        ev = {"quando": time.strftime("%Y-%m-%dT%H:%M:%S"), "tipo": kind, "detalhe": detail}
        self.events = (self.events + [ev])[-30:]
        self.log({"id": f"vigia-{time.time_ns() // 1000}", "server": "vigia", "tool": kind, "args": {"detalhe": detail},
                  "evento": "fim", "ok": True, "quando": ev["quando"]})
        if voice:
            self._say(voice, cfg)

    def tick(self) -> None:
        cfg = self.config()
        if not cfg["ligado"]:
            return
        if self.leader is not None and not self.leader.try_acquire():
            return
        self.ticks += 1
        now = self.clock()
        pressed = self.api.pressed()
        for gone in [k for k in self.since if k not in pressed]:
            self.since.pop(gone, None)
            self.warned.discard(gone)
        for name in pressed:
            self.since.setdefault(name, now)
            held = now - self.since[name]
            mouse = name.startswith("mouse ")
            t_warn = cfg["segundos_aviso_mouse" if mouse else "segundos_aviso_modificador"]
            t_rel = cfg["segundos_liberar_mouse" if mouse else "segundos_liberar_modificador"]
            label = "Botao do mouse " + name[6:] if mouse else "Tecla " + name
            if held >= t_warn and name not in self.warned:
                self.warned.add(name)
                self._event("tecla_presa_aviso", f"{label} apertada ha {int(held)} s", cfg,
                            f"Atencao: {label} parece presa.")
            if held >= t_rel and cfg["liberar_teclas_presas"]:
                try:
                    self.api.release(name)
                    self._event("tecla_presa_liberada", f"{label} liberada apos {int(held)} s", cfg, f"{label} liberada.")
                except Exception as exc:  # noqa: BLE001
                    self._event("tecla_presa_falha", f"{label}: {exc}", cfg)
                self.since[name] = now  # recomeca a contar
                self.warned.discard(name)

        for flag, on in self.api.accessibility_flags().items():
            if flag in self.baseline_on:
                continue  # ja estava ligado quando o vigia comecou: escolha da pessoa
            if on and flag not in self.alerted_flags:
                self.alerted_flags.add(flag)
                if cfg["restaurar_recursos_de_acessibilidade"]:
                    ok = self.api.disable_flag(flag)
                    self._event("recurso_desligado" if ok else "recurso_falha", f"{flag} ligou sozinho; "
                                + ("desligado de volta" if ok else "nao consegui desligar"), cfg)
                else:
                    self._event("recurso_ligado", f"{flag} esta ligado", cfg)
            elif not on:
                self.alerted_flags.discard(flag)

        if now - self._last_unsafe_check >= 30:
            self._last_unsafe_check = now
            for item in self.api.unsafe_windows_mcp():
                pid = item["pid"]
                if pid in self.alerted_pids:
                    continue
                self.alerted_pids.add(pid)
                if cfg["encerrar_copias_inseguras"]:
                    ok = self.api.terminate_tree_of(pid)
                    self._event("windows_mcp_inseguro_encerrado" if ok else "windows_mcp_inseguro_falha", f"pid {pid}", cfg)
                else:
                    self._event("windows_mcp_inseguro_aviso", f"pid {pid} com controle de teclado e mouse ligado", cfg)

    def run_forever(self) -> None:
        try:  # prioridade minima: o vigia nunca pode competir com o que a pessoa esta fazendo
            k = ctypes.windll.kernel32
            k.SetThreadPriority(k.GetCurrentThread(), -2)  # THREAD_PRIORITY_LOWEST
        except Exception:  # noqa: BLE001
            pass
        while True:
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - o vigia nunca pode cair nem derrubar o servidor
                pass
            time.sleep(max(0.5, float(self.config().get("intervalo_s", 2.0))))


_INSTANCE: Optional[Vigia] = None


def start() -> Vigia:
    global _INSTANCE
    if _INSTANCE is None:
        from core.leader import leader_for

        _INSTANCE = Vigia(leader=leader_for("vigia"))
        threading.Thread(target=_INSTANCE.run_forever, name="blind-vigia", daemon=True).start()
    return _INSTANCE
