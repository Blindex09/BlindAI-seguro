"""
Ponte nativa para o binário 'agent-desktop' (Vercel Labs - C:\\repos ia\\agent-desktop).
Expõe os comandos oficiais do CLI agent-desktop com saída JSON estruturada (@ref IDs),
implementando o ciclo Observe -> Act on @ref -> Verify sem inventar recursos fora do projeto.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger("blind.agent_desktop")


LAUNCH_TIMEOUT_SEC = 60.0


class AgentDesktopBridge:
    """Wrapper Python fiel ao CLI oficial agent-desktop."""

    def __init__(self, timeout_sec: float = 15.0):
        self.timeout_sec = timeout_sec
        self._exe_path: Optional[str] = self._resolve_executable()

    def _resolve_executable(self) -> Optional[str]:
        arch = "arm64" if "arm" in platform.machine().lower() else "x64"
        appdata = os.getenv("APPDATA", "")
        candidates = []
        if appdata:
            candidates.append(
                os.path.join(
                    appdata,
                    "npm",
                    "node_modules",
                    "agent-desktop",
                    "bin",
                    f"agent-desktop-win32-{arch}.exe",
                )
            )
            candidates.append(
                os.path.join(
                    appdata,
                    "npm",
                    "node_modules",
                    "agent-desktop",
                    "bin",
                    "agent-desktop-win32-x64.exe",
                )
            )
        for path in candidates:
            if path and os.path.isfile(path):
                return path
        return shutil.which("agent-desktop.cmd") or shutil.which("agent-desktop")

    def is_available(self) -> bool:
        return bool(self._exe_path and os.path.exists(self._exe_path))

    def _run(self, args: List[str], stdin_text: Optional[str] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
        if not self.is_available():
            return {
                "ok": False,
                "error": {"code": "NOT_INSTALLED", "message": "Binário agent-desktop não encontrado."},
            }
        cmd = [self._exe_path] + args
        try:
            proc = subprocess.run(
                cmd,
                input=stdin_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.timeout_sec,
            )
            raw = (proc.stdout or "").strip()
            if not raw:
                err_txt = (proc.stderr or "").strip()
                return {
                    "ok": False,
                    "error": {
                        "code": "EMPTY_OUTPUT",
                        "message": err_txt or f"agent-desktop retornou saída vazia (exit {proc.returncode})",
                    },
                }
            for line in reversed(raw.splitlines()):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    return json.loads(line)
            return {"ok": False, "error": {"code": "INVALID_JSON", "message": raw[:300]}}
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": {"code": "TIMEOUT", "message": f"Timeout após {timeout or self.timeout_sec}s em {' '.join(args)}"},
            }
        except Exception as e:
            logger.debug(f"Falha ao executar agent-desktop {args}: {e}")
            return {"ok": False, "error": {"code": "EXEC_ERROR", "message": str(e)}}

    # --- Diagnóstico e Descoberta ---
    def status(self) -> Dict[str, Any]:
        return self._run(["status"])

    def permissions(self) -> Dict[str, Any]:
        return self._run(["permissions"])

    def version(self) -> Dict[str, Any]:
        return self._run(["version"])

    def list_windows(self, app: Optional[str] = None) -> Dict[str, Any]:
        args = ["list-windows"]
        if app:
            args.extend(["--app", app])
        return self._run(args)

    def list_apps(self, app: Optional[str] = None) -> Dict[str, Any]:
        args = ["list-apps"]
        if app:
            args.extend(["--app", app])
        return self._run(args)

    def list_displays(self) -> Dict[str, Any]:
        return self._run(["list-displays"])

    def list_surfaces(self, app: Optional[str] = None, window_id: Optional[str] = None) -> Dict[str, Any]:
        args = ["list-surfaces"]
        if app:
            args.extend(["--app", app])
        if window_id:
            args.extend(["--window-id", window_id])
        return self._run(args)

    def open_system_surface(self, surface: str) -> Dict[str, Any]:
        return self._run(["open-system-surface", surface])

    # --- Observação (Snapshot, Find, Get, Is, Screenshot) ---
    def snapshot(
        self,
        app: Optional[str] = None,
        window_id: Optional[str] = None,
        interactive_only: bool = True,
        compact: bool = True,
        skeleton: bool = False,
        root: Optional[str] = None,
        max_depth: int = 8,
        surface: str = "window",
        include_bounds: bool = False,
    ) -> Dict[str, Any]:
        args = ["snapshot", "--surface", surface, "--max-depth", str(max_depth)]
        if app:
            args.extend(["--app", app])
        if window_id:
            args.extend(["--window-id", window_id])
        if root:
            args.extend(["--root", root])
        if interactive_only:
            args.append("-i")
        if compact:
            args.append("--compact")
        if skeleton:
            args.append("--skeleton")
        if include_bounds:
            args.append("--include-bounds")
        return self._run(args)

    def find(
        self,
        name: Optional[str] = None,
        role: Optional[str] = None,
        app: Optional[str] = None,
        window_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        args = ["find"]
        if name:
            args.extend(["--name", name])
        if role:
            args.extend(["--role", role])
        if app:
            args.extend(["--app", app])
        if window_id:
            args.extend(["--window-id", window_id])
        return self._run(args)

    def get_prop(self, ref_id: str, prop: str = "text") -> Dict[str, Any]:
        return self._run(["get", "--property", prop, ref_id])

    def is_state(self, ref_id: str, prop: str = "visible") -> Dict[str, Any]:
        return self._run(["is", "--property", prop, ref_id])

    def screenshot(self, app: Optional[str] = None, window_id: Optional[str] = None, path: Optional[str] = None) -> Dict[str, Any]:
        args = ["screenshot"]
        if app:
            args.extend(["--app", app])
        if window_id:
            args.extend(["--window-id", window_id])
        if path:
            args.append(path)
        return self._run(args)

    # --- Ações em @ref ---
    def click_ref(self, ref_id: str, headed: bool = False) -> Dict[str, Any]:
        args = ["click", ref_id]
        if headed:
            args.insert(0, "--headed")
        return self._run(args)

    def double_click_ref(self, ref_id: str) -> Dict[str, Any]:
        return self._run(["--headed", "double-click", ref_id])

    def triple_click_ref(self, ref_id: str) -> Dict[str, Any]:
        return self._run(["--headed", "triple-click", ref_id])

    def right_click_ref(self, ref_id: str, headed: bool = True) -> Dict[str, Any]:
        args = ["right-click", ref_id]
        if headed:
            args.insert(0, "--headed")
        return self._run(args)

    def type_ref(self, ref_id: str, text: str, headed: bool = True) -> Dict[str, Any]:
        args = ["type", ref_id, "--stdin"]
        if headed:
            args.insert(0, "--headed")
        return self._run(args, stdin_text=text)

    def set_value_ref(self, ref_id: str, text: str) -> Dict[str, Any]:
        return self._run(["set-value", ref_id, "--stdin"], stdin_text=text)

    def clear_ref(self, ref_id: str) -> Dict[str, Any]:
        return self._run(["clear", ref_id])

    def focus_ref(self, ref_id: str) -> Dict[str, Any]:
        return self._run(["focus", ref_id])

    def select_ref(self, ref_id: str, value: str) -> Dict[str, Any]:
        return self._run(["select", ref_id, value])

    def toggle_ref(self, ref_id: str) -> Dict[str, Any]:
        return self._run(["toggle", ref_id])

    def check_ref(self, ref_id: str) -> Dict[str, Any]:
        return self._run(["check", ref_id])

    def uncheck_ref(self, ref_id: str) -> Dict[str, Any]:
        return self._run(["uncheck", ref_id])

    def expand_ref(self, ref_id: str) -> Dict[str, Any]:
        return self._run(["expand", ref_id])

    def collapse_ref(self, ref_id: str) -> Dict[str, Any]:
        return self._run(["collapse", ref_id])

    def scroll_ref(self, ref_id: str, direction: str = "down", amount: int = 3) -> Dict[str, Any]:
        return self._run(["scroll", ref_id, "--direction", direction, "--amount", str(amount)])

    def scroll_to_ref(self, ref_id: str) -> Dict[str, Any]:
        return self._run(["scroll-to", ref_id])

    def press_keys(self, keys: str, headed: bool = True) -> Dict[str, Any]:
        args = ["press", keys]
        if headed:
            args.insert(0, "--headed")
        return self._run(args)

    def hover_ref(self, ref_id: str) -> Dict[str, Any]:
        return self._run(["--headed", "hover", ref_id])

    def drag_ref(self, source_ref: str, target_ref: str) -> Dict[str, Any]:
        return self._run(["--headed", "drag", source_ref, target_ref])

    # --- Controle de Aplicativos e Janelas ---
    def launch_app(self, target: str, activate: bool = True) -> Dict[str, Any]:
        args = ["launch", target]
        if activate:
            args.append("--activate")
        # O CLI espera a janela aparecer e leva ~30 s no Windows 11; o limite padrao (15 s) dava falso erro.
        return self._run(args, timeout=LAUNCH_TIMEOUT_SEC)

    def close_app(self, app: str, force: bool = False) -> Dict[str, Any]:
        args = ["close-app", app]
        if force:
            args.append("--force")
        res = self._run(args, timeout=LAUNCH_TIMEOUT_SEC)
        err = (res.get("error") or {}) if isinstance(res, dict) else {}
        if not res.get("ok") and err.get("code") == "APP_NOT_FOUND":
            # Apps UWP (Calculadora, Fotos...) rodam num processo que o close-app nao reconhece por nome.
            # Fecha a janela correspondente (titulo ou app_name) com Alt+F4, que e o fechamento normal.
            return self._close_window_fallback(app, res)
        return res

    def _close_window_fallback(self, app: str, original: Dict[str, Any]) -> Dict[str, Any]:
        wanted = (app or "").strip().lower()
        if wanted.endswith(".exe"):
            wanted = wanted[:-4]
        listing = self.list_windows()
        windows = listing.get("data") if isinstance(listing, dict) else None
        if not wanted or not isinstance(windows, list):
            return original
        matches = [
            w
            for w in windows
            if w.get("visible", True)
            and (
                wanted in (w.get("title") or "").lower()
                or wanted in (w.get("app_name") or "").lower().removesuffix(".exe")
            )
        ]
        if not matches:
            return original
        if len(matches) > 1:
            titles = ", ".join(f"{w.get('title')!r} ({w.get('id')})" for w in matches)
            return {
                "ok": False,
                "error": {
                    "code": "AMBIGUOUS_WINDOW",
                    "message": f"Mais de uma janela corresponde a '{app}': {titles}. Nada foi fechado; use window_id.",
                },
            }
        target = matches[0]
        focus = self.focus_window(window_id=target["id"])
        if not focus.get("ok"):
            return focus
        # So age se a janela que ganhou foco e mesmo a escolhida (nunca fecha outra janela por engano).
        after = self.list_windows().get("data") or []
        focused = next((w for w in after if w.get("is_focused")), None)
        if not focused or focused.get("id") != target["id"]:
            return {
                "ok": False,
                "error": {"code": "FOCUS_MISMATCH", "message": f"A janela '{target.get('title')}' nao recebeu o foco; nada foi fechado."},
            }
        # O agent-desktop bloqueia Alt+F4 por seguranca. O fechamento normal e o botao Fechar da janela.
        for label in ("Fechar", "Close"):
            found = self.find(name=label, role="button", window_id=target["id"])
            matches = (found.get("data") or {}).get("matches") if isinstance(found, dict) else None
            ref = next((m.get("ref_id") for m in matches or [] if m.get("ref_id")), None)
            if ref:
                clicked = self.click_ref(ref)
                if not clicked.get("ok"):
                    return clicked
                return {
                    "ok": True,
                    "command": "close-app",
                    "data": {"app": target.get("app_name"), "window": target.get("title"), "method": "botao Fechar da janela (app UWP)"},
                }
        return {
            "ok": False,
            "error": {"code": "CLOSE_BUTTON_NOT_FOUND", "message": f"Nao achei o botao Fechar da janela '{target.get('title')}'."},
        }

    def focus_window(self, window_id: Optional[str] = None, app: Optional[str] = None) -> Dict[str, Any]:
        args = ["focus-window"]
        if window_id:
            args.extend(["--window-id", window_id])
        elif app:
            args.extend(["--app", app])
        return self._run(args)

    def minimize_window(self, app: Optional[str] = None, window_id: Optional[str] = None) -> Dict[str, Any]:
        args = ["minimize"]
        if window_id:
            args.extend(["--window-id", window_id])
        elif app:
            args.extend(["--app", app])
        return self._run(args)

    def maximize_window(self, app: Optional[str] = None, window_id: Optional[str] = None) -> Dict[str, Any]:
        args = ["maximize"]
        if window_id:
            args.extend(["--window-id", window_id])
        elif app:
            args.extend(["--app", app])
        return self._run(args)

    def restore_window(self, app: Optional[str] = None, window_id: Optional[str] = None) -> Dict[str, Any]:
        args = ["restore"]
        if window_id:
            args.extend(["--window-id", window_id])
        elif app:
            args.extend(["--app", app])
        return self._run(args)

    def resize_window(self, width: int, height: int, app: Optional[str] = None, window_id: Optional[str] = None) -> Dict[str, Any]:
        args = ["resize-window", str(width), str(height)]
        if window_id:
            args.extend(["--window-id", window_id])
        elif app:
            args.extend(["--app", app])
        return self._run(args)

    def move_window(self, x: int, y: int, app: Optional[str] = None, window_id: Optional[str] = None) -> Dict[str, Any]:
        args = ["move-window", str(x), str(y)]
        if window_id:
            args.extend(["--window-id", window_id])
        elif app:
            args.extend(["--app", app])
        return self._run(args)

    # --- Notificações e Clipboard ---
    def list_notifications(self) -> Dict[str, Any]:
        return self._run(["list-notifications"])

    def dismiss_notification(self, index: int) -> Dict[str, Any]:
        return self._run(["dismiss-notification", str(index)])

    def dismiss_all_notifications(self, app: Optional[str] = None) -> Dict[str, Any]:
        args = ["dismiss-all-notifications"]
        if app:
            args.extend(["--app", app])
        return self._run(args)

    def notification_action(self, index: int, action_name: str) -> Dict[str, Any]:
        return self._run(["notification-action", str(index), action_name])

    def clipboard_get(self) -> Dict[str, Any]:
        return self._run(["clipboard-get"])

    def clipboard_set(self, text: str) -> Dict[str, Any]:
        return self._run(["clipboard-set", "--stdin"], stdin_text=text)

    def clipboard_clear(self) -> Dict[str, Any]:
        return self._run(["clipboard-clear"])

    # --- Wait & Batch ---
    def wait_for(
        self,
        ms: Optional[int] = None,
        element: Optional[str] = None,
        text: Optional[str] = None,
        window: Optional[str] = None,
        app: Optional[str] = None,
        timeout_ms: int = 10000,
    ) -> Dict[str, Any]:
        args = ["wait", "--timeout", str(timeout_ms)]
        if element:
            args.extend(["--element", element])
        elif text:
            args.extend(["--text", text])
        elif window:
            args.extend(["--window", window])
        elif ms is not None:
            args = ["wait", str(ms)]
        if app:
            args.extend(["--app", app])
        return self._run(args, timeout=(timeout_ms / 1000.0) + 5.0)

    def batch(self, commands: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self._run(["batch", json.dumps(commands, ensure_ascii=False)])

    def format_snapshot_for_llm(self, snap_res: Dict[str, Any], max_items: int = 60) -> str:
        """Formata a árvore JSON do agent-desktop com @ref_id para leitura direta pela IA."""
        if not snap_res or not snap_res.get("ok"):
            return ""
        data = snap_res.get("data") or {}
        tree = data.get("tree")
        if not tree:
            return ""

        lines: List[str] = []
        app_name = data.get("app") or "Janela"
        snap_id = data.get("snapshot_id") or ""
        lines.append(f"Árvore agent-desktop ({app_name} | snapshot={snap_id}):")

        def walk(node: Dict[str, Any], depth: int = 0):
            if len(lines) >= max_items + 1 or not isinstance(node, dict):
                return
            role = node.get("role") or ""
            name = (node.get("name") or node.get("value") or "").strip()
            ref_id = node.get("ref_id") or ""
            if ref_id or name:
                indent = "  " * min(depth, 4)
                ref_tag = f" -> {ref_id}" if ref_id else ""
                label = f'"{name[:80]}"' if name else "(sem nome)"
                lines.append(f"{indent}- [{role}] {label}{ref_tag}")
            for child in node.get("children") or []:
                walk(child, depth + 1)

        walk(tree)
        return "\n".join(lines)


agent_desktop_bridge = AgentDesktopBridge()
