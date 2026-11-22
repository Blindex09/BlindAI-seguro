"""
Módulo de Automação e Interação com a Tela (Desktop Controller) - Blind AI
Clonado e adaptado da arquitetura do 'agent-desktop' (Vercel Labs / Windows UIA).
Permite que o assistente interaja de forma semântica com qualquer aplicativo desktop
(clicar em botões, selecionar itens de lista, digitar textos e focar janelas)
através da Árvore de Acessibilidade nativa da Microsoft (UI Automation).
"""

from __future__ import annotations

import ctypes
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("blind.desktop")

_INPUT_DISABLED_MSG = (
    "Entrada por teclado e mouse reais esta DESATIVADA neste projeto (o teclado do usuario travou 3 vezes em 16/11/2026). "
    "Use agent-desktop por @ref (acessibilidade) ou peca ao usuario para executar a acao."
)

try:
    from core.desktop.agent_desktop_bridge import agent_desktop_bridge
except Exception:
    agent_desktop_bridge = None

# Carrega bibliotecas nativas do Windows
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

try:
    import uiautomation as auto
    UIA_AVAILABLE = True
except ImportError:
    UIA_AVAILABLE = False
    logger.warning("Biblioteca 'uiautomation' não encontrada. Automação de tela ficará restrita.")


def _ensure_desktop():
    """Garante que a thread atual esteja anexada ao desktop interativo 'Default'."""
    try:
        hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
    except Exception as e:
        logger.debug(f"Erro ao anexar ao desktop Default: {e}")


class DesktopController:
    """Controlador de Ações e Inspeção de Janelas Desktop via UI Automation."""

    def __init__(self):
        self._ensure_env()

    def _ensure_env(self):
        _ensure_desktop()
        if UIA_AVAILABLE:
            auto.SetGlobalSearchTimeout(2.0)

    def list_windows(self) -> List[Dict[str, Any]]:
        """Lista todas as janelas visíveis no desktop interativo."""
        self._ensure_env()
        windows: List[Dict[str, Any]] = []

        hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if not hdesk:
            return windows

        user32.SetThreadDesktop(hdesk)
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.strip()
                    # Ignora janelas utilitárias vazias do sistema
                    if title and title not in ("Program Manager", "Experiência de Entrada do Windows"):
                        rect = (ctypes.c_long * 4)()
                        user32.GetWindowRect(hwnd, ctypes.byref(rect))
                        windows.append({
                            "hwnd": hwnd,
                            "title": title,
                            "rect": [rect[0], rect[1], rect[2], rect[3]]
                        })
            return True

        user32.EnumDesktopWindows(hdesk, WNDENUMPROC(cb), 0)
        return windows

    def find_window(self, title_query: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Localiza uma janela pelo título (exato ou parcial) ou retorna a janela ativa."""
        windows = self.list_windows()
        if not windows:
            return None

        if title_query:
            if isinstance(title_query, int):
                for w in windows:
                    if w["hwnd"] == title_query:
                        return w
            else:
                query_lower = str(title_query).lower()
                # 1. Busca correspondência exata ou que contenha o texto
                for w in windows:
                    if query_lower in w["title"].lower():
                        return w

        # 2. Se nenhuma busca foi especificada, tenta a janela em primeiro plano
        fg_hwnd = user32.GetForegroundWindow()
        for w in windows:
            if w["hwnd"] == fg_hwnd:
                return w

        # Fallback: primeira janela visível que não seja o próprio navegador Blind AI
        for w in windows:
            if "blind" not in w["title"].lower():
                return w

        return windows[0]

    def inspect_window(self, window_query: Optional[str] = None) -> Dict[str, Any]:
        """
        Inspeciona a árvore de acessibilidade da janela e retorna todos os elementos interativos
        (botões, campos de texto, itens de lista, caixas de seleção, abas).
        """
        if not UIA_AVAILABLE:
            return {"status": "error", "message": "Módulo UIA não instalado."}

        self._ensure_env()
        target = self.find_window(window_query)
        if not target:
            return {"status": "error", "message": f"Nenhuma janela encontrada para '{window_query}'."}

        hwnd = target["hwnd"]
        ctrl = auto.ControlFromHandle(hwnd)
        if not ctrl:
            return {"status": "error", "message": f"Não foi possível acessar a árvore da janela '{target['title']}'."}

        interactive_elements: List[Dict[str, Any]] = []
        element_counter = 1

        # Tipos de controle com os quais o agente pode interagir (padrão agent-desktop)
        INTERACTIVE_ROLES = {
            "ButtonControl": "button",
            "EditControl": "edit",
            "ListItemControl": "listitem",
            "RadioButtonControl": "radio",
            "CheckBoxControl": "checkbox",
            "MenuItemControl": "menuitem",
            "TabItemControl": "tab",
            "ComboBoxControl": "combobox",
            "HyperlinkControl": "link"
        }

        def walk(node, depth=0):
            nonlocal element_counter
            if depth > 6 or element_counter > 60:
                return

            try:
                children = node.GetChildren()
            except Exception:
                return

            for c in children:
                try:
                    c_type = c.ControlTypeName
                    c_name = c.Name.strip() if c.Name else ""
                    
                    if c_type in INTERACTIVE_ROLES and c_name:
                        rect = c.BoundingRectangle
                        # Ignora controles com tamanho zero (invisíveis)
                        if rect and (rect.right - rect.left > 0) and (rect.bottom - rect.top > 0):
                            interactive_elements.append({
                                "ref": f"@e{element_counter}",
                                "name": c_name,
                                "type": INTERACTIVE_ROLES[c_type],
                                "raw_type": c_type,
                                "rect": [rect.left, rect.top, rect.right, rect.bottom]
                            })
                            element_counter += 1
                    walk(c, depth + 1)
                except Exception:
                    continue

        walk(ctrl)

        # Se a janela ativa não possui controles interativos (ex: console de script), tenta as demais janelas
        if not interactive_elements and not window_query:
            for w in self.list_windows():
                if w["hwnd"] != hwnd:
                    c = auto.ControlFromHandle(w["hwnd"])
                    if c:
                        element_counter = 1
                        walk(c)
                        if interactive_elements:
                            target = w
                            hwnd = w["hwnd"]
                            break

        return {
            "status": "success",
            "window": target["title"],
            "hwnd": hwnd,
            "total_elements": len(interactive_elements),
            "elements": interactive_elements
        }

    def find_element_everywhere(self, element_query: str) -> Optional[Dict[str, Any]]:
        """
        Busca um elemento interativo em TODAS as janelas visíveis da área de trabalho,
        incluindo janelas de aplicativos, bandeja do sistema e overflow de notificações.
        """
        if not UIA_AVAILABLE:
            return None

        self._ensure_env()
        query_lower = element_query.lower().strip()

        hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if not hdesk:
            return None
        user32.SetThreadDesktop(hdesk)

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        windows: List[Tuple[int, str]] = []

        def cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.strip()
                    if title and "blind" not in title.lower():
                        windows.append((hwnd, title))
            return True

        user32.EnumDesktopWindows(hdesk, WNDENUMPROC(cb), 0)

        # Prioriza a janela de bandeja do sistema / overflow se o usuário estiver na barra de tarefas
        windows.sort(key=lambda w: 0 if any(k in w[1].lower() for k in ["bandeja", "overflow", "tray"]) else 1)

        for hwnd, title in windows:
            ctrl = auto.ControlFromHandle(hwnd)
            if not ctrl:
                continue

            def walk_search(node, depth=0):
                if depth > 5:
                    return None
                try:
                    children = node.GetChildren()
                except Exception:
                    return None

                for c in children:
                    c_name = (c.Name or "").strip()
                    if c_name and query_lower in c_name.lower():
                        rect = c.BoundingRectangle
                        if rect and (rect.right - rect.left > 0) and (rect.bottom - rect.top > 0):
                            return {
                                "hwnd": hwnd,
                                "window": title,
                                "element": {
                                    "name": c_name,
                                    "type": c.ControlTypeName,
                                    "rect": [rect.left, rect.top, rect.right, rect.bottom]
                                }
                            }
                    found = walk_search(c, depth + 1)
                    if found:
                        return found
                return None

            res = walk_search(ctrl)
            if res:
                return res

        return None

    def click_element(self, element_query: str, window_query: Optional[str] = None, is_double: bool = False) -> Dict[str, Any]:
        """
        Clica semântica ou fisicamente em um elemento da tela pelo nome (ex: 'Google Drive', 'Nova conversa', 'Mozão').
        Se window_query for omitido ou não contiver o elemento, busca em todas as janelas do sistema (incluindo a bandeja).
        """
        # DESATIVADO (17/11/2026): cliques fisicos (SetCursorPos/mouse_event) foram removidos porque o teclado/mouse do
        # usuario travou 3 vezes. Use agent-desktop por @ref (acessibilidade), que nao injeta entrada.
        return {"status": "error", "message": _INPUT_DISABLED_MSG}

        if not UIA_AVAILABLE:  # noqa: unreachable - mantido so como referencia
            return {"status": "error", "message": "Módulo UIA não instalado."}

        self._ensure_env()
        matched = None
        target_hwnd = None
        target_window = None

        # 1. Tenta encontrar na janela especificada se houver
        if window_query:
            inspection = self.inspect_window(window_query)
            if inspection.get("status") == "success":
                target_hwnd = inspection["hwnd"]
                target_window = inspection["window"]
                for el in inspection.get("elements", []):
                    if element_query.lower() in el["name"].lower():
                        matched = el
                        break

        # 2. Se não encontrou, busca em TODAS as janelas visíveis do sistema (bandeja, aplicativos, etc.)
        if not matched:
            everywhere = self.find_element_everywhere(element_query)
            if everywhere:
                target_hwnd = everywhere["hwnd"]
                target_window = everywhere["window"]
                matched = everywhere["element"]

        if not matched:
            return {
                "status": "error",
                "message": f"Elemento '{element_query}' não foi localizado na tela nem na bandeja do sistema."
            }

        # Traz a janela para o foco antes do clique (exceto janelas de bandeja transparentes)
        if target_hwnd and "bandeja" not in (target_window or "").lower():
            try:
                user32.SetForegroundWindow(target_hwnd)
                time.sleep(0.15)
            except Exception:
                pass

        # Executa o clique através do centro da caixa delimitadora do elemento
        rect = matched["rect"]
        center_x = (rect[0] + rect[2]) // 2
        center_y = (rect[1] + rect[3]) // 2

        # Detecta se é ícone de bandeja para aplicar duplo clique automaticamente se necessário
        is_tray = target_window and any(k in target_window.lower() for k in ["bandeja", "overflow", "tray"])
        should_double_click = is_double or is_tray

        try:
            user32.SetCursorPos(center_x, center_y)
            time.sleep(0.05)
            # Primeiro clique
            user32.mouse_event(0x0002, center_x, center_y, 0, 0)
            time.sleep(0.04)
            user32.mouse_event(0x0004, center_x, center_y, 0, 0)

            if should_double_click:
                time.sleep(0.06)
                user32.mouse_event(0x0002, center_x, center_y, 0, 0)
                time.sleep(0.04)
                user32.mouse_event(0x0004, center_x, center_y, 0, 0)
                action_desc = "Clique duplo"
            else:
                action_desc = "Clique"

            msg = f"{action_desc} realizado com sucesso em '{matched['name']}' na janela '{target_window}'."
            return {
                "status": "success",
                "message": msg,
                "element": matched,
                "window": target_window,
                "action": "double_click" if should_double_click else "click"
            }
        except Exception as e:
            return {"status": "error", "message": f"Falha física ao clicar no elemento: {e}"}

    def type_into_element(self, element_query: str, text: str, window_query: Optional[str] = None) -> Dict[str, Any]:
        """DESATIVADO: digitava com teclas reais (SendKeys). Use agent-desktop type_text/set_value por @ref."""
        return {"status": "error", "message": _INPUT_DISABLED_MSG}
        click_res = self.click_element(element_query, window_query)  # noqa: unreachable
        if click_res.get("status") != "success":
            return click_res

        time.sleep(0.1)
        try:
            if UIA_AVAILABLE:
                auto.SendKeys(text)
            return {
                "status": "success",
                "message": f"Texto digitado com sucesso no campo '{element_query}'.",
                "text": text
            }
        except Exception as e:
            return {"status": "error", "message": f"Falha ao digitar texto: {e}"}

    def press_shortcut(self, shortcut: str, window_query: Optional[str] = None) -> Dict[str, Any]:
        """DESATIVADO: enviava atalhos com teclas reais (SendKeys). Peca ao usuario para apertar o atalho."""
        return {"status": "error", "message": _INPUT_DISABLED_MSG}
        self._ensure_env()  # noqa: unreachable
        target = self.find_window(window_query)
        if target:
            try:
                user32.SetForegroundWindow(target["hwnd"])
                time.sleep(0.1)
            except Exception:
                pass

        try:
            if UIA_AVAILABLE:
                auto.SendKeys(shortcut)
            return {"status": "success", "message": f"Atalho '{shortcut}' enviado com sucesso."}
        except Exception as e:
            return {"status": "error", "message": f"Falha ao enviar atalho: {e}"}

    def bring_window_to_front(self, target: Any) -> Dict[str, Any]:
        """
        Restaura e traz uma janela para o primeiro plano (foreground) no Windows.
        Baseado no padrão nativo de ativação e verificação de propriedade do agent-desktop (window_activate.rs).
        Suporta HWND direto ou busca por título.
        """
        self._ensure_env()
        hwnd = None
        title = ""

        if isinstance(target, int):
            hwnd = target
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            title = buf.value.strip() or f"Janela HWND {hwnd}"
        elif isinstance(target, str):
            w = self.find_window(target)
            if w:
                hwnd = w["hwnd"]
                title = w["title"]
            else:
                windows = self.list_windows()
                for item in windows:
                    if target.lower() in item["title"].lower():
                        hwnd = item["hwnd"]
                        title = item["title"]
                        break

        if not hwnd or not user32.IsWindow(hwnd):
            return {
                "status": "error",
                "message": f"Janela correspondente a '{target}' não foi localizada na tela."
            }

        try:
            # 1. (removido) o "Alt tap" via keybd_event: injetava tecla real e pode deixar o Alt preso.

            # 2. Se estiver minimizada (iconic), restaura via SW_RESTORE (9)
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            else:
                user32.ShowWindow(hwnd, 5)  # SW_SHOW

            # 3. Anexa input de threads para contornar LockSetForegroundWindow
            fg_hwnd = user32.GetForegroundWindow()
            fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
            target_tid = user32.GetWindowThreadProcessId(hwnd, None)
            cur_tid = kernel32.GetCurrentThreadId()

            if fg_tid and fg_tid != cur_tid:
                user32.AttachThreadInput(cur_tid, fg_tid, True)
            if target_tid and target_tid != cur_tid:
                user32.AttachThreadInput(cur_tid, target_tid, True)

            user32.ShowWindow(hwnd, 9)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            try:
                user32.SwitchToThisWindow(hwnd, True)
            except Exception:
                pass

            if fg_tid and fg_tid != cur_tid:
                user32.AttachThreadInput(cur_tid, fg_tid, False)
            if target_tid and target_tid != cur_tid:
                user32.AttachThreadInput(cur_tid, target_tid, False)

            time.sleep(0.15)
            is_fg = (user32.GetForegroundWindow() == hwnd)

            return {
                "status": "success",
                "hwnd": hwnd,
                "title": title,
                "is_foreground": is_fg,
                "message": f"Janela '{title}' trazida para a frente com sucesso."
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Falha ao trazer janela para a frente: {e}"
            }

    def click_and_bring_to_front(self, element_query: str, window_query: Optional[str] = None) -> Dict[str, Any]:
        """
        Executa um clique duplo no elemento (útil para ícones da bandeja como Google Drive, Ollama, WinZapp)
        e imediatamente localiza e traz a janela correspondente para o primeiro plano.
        """
        self._ensure_env()
        click_res = self.click_element(element_query, window_query, is_double=True)
        if click_res.get("status") != "success":
            return click_res

        el_name = click_res.get("element", {}).get("name", element_query)
        time.sleep(0.35)

        target_name_clean = el_name.split("|")[0].split("-")[0].strip()
        win = self.find_window(target_name_clean)
        if not win and element_query:
            win = self.find_window(element_query)

        if win:
            self.bring_window_to_front(win["hwnd"])
            return {
                "status": "success",
                "action": "click_and_bring_to_front",
                "element": click_res.get("element"),
                "window": win["title"],
                "message": f"Cliquei em '{el_name}' e trouxe a janela '{win['title']}' para o primeiro plano."
            }

        return {
            "status": "success",
            "action": "click_and_bring_to_front",
            "element": click_res.get("element"),
            "window": click_res.get("window"),
            "message": f"Clique duplo realizado em '{el_name}' com sucesso."
        }

    def list_tray_elements(self) -> List[Dict[str, Any]]:
        """
        Lista todos os botões e ícones da bandeja do sistema (tray e janela de estouro)
        usando UI Automation, capturando nomes reais sem adivinhação.
        """
        if not UIA_AVAILABLE:
            return []

        self._ensure_env()
        hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if not hdesk:
            return []
        user32.SetThreadDesktop(hdesk)

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        tray_hwnds: List[Tuple[int, str]] = []

        def cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.strip()
                    if any(k in title.lower() for k in ["bandeja", "overflow", "notifica", "tray"]):
                        tray_hwnds.append((hwnd, title))
            return True

        user32.EnumDesktopWindows(hdesk, WNDENUMPROC(cb), 0)

        tray_elements: List[Dict[str, Any]] = []
        for hwnd, title in tray_hwnds:
            ctrl = auto.ControlFromHandle(hwnd)
            if not ctrl:
                continue

            def walk_tray(node, depth=0):
                if depth > 5:
                    return
                for ch in node.GetChildren():
                    if ch.ControlTypeName == "ButtonControl":
                        c_name = (ch.Name or "").strip()
                        rect = ch.BoundingRectangle
                        if c_name and rect and (rect.right - rect.left > 0):
                            tray_elements.append({
                                "name": c_name,
                                "window": title,
                                "rect": [rect.left, rect.top, rect.right, rect.bottom]
                            })
                    walk_tray(ch, depth + 1)

            walk_tray(ctrl)

        # Windows 11: a barra de tarefas (Shell_TrayWnd) nao tem titulo, entao a busca por titulo acima nao acha nada.
        # Os icones da area de notificacao sao botoes de classe "SystemTray.*"; os da lista de tarefas sao outra classe.
        if not tray_elements:
            tray_elements.extend(self._scan_system_tray())

        return tray_elements

    @staticmethod
    def _scan_system_tray() -> List[Dict[str, Any]]:
        found: List[Dict[str, Any]] = []
        roots = []
        for cls in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow",
                    "TopLevelWindowForOverflowXamlIsland"):
            try:
                node = auto.Control(ClassName=cls, searchDepth=1)
                if node.Exists(0):
                    roots.append((cls, node))
            except Exception:  # noqa: BLE001
                continue

        def walk(node, cls, depth=0):
            if depth > 8:
                return
            for ch in node.GetChildren():
                if ch.ControlTypeName == "ButtonControl":
                    c_class = ch.ClassName or ""
                    name = " ".join(((ch.Name or "").replace("\u200e", "")).split()).strip()
                    words = name.split()
                    half = len(words) // 2
                    if len(words) % 2 == 0 and half and [w.lower() for w in words[:half]] == [w.lower() for w in words[half:]]:
                        name = " ".join(words[:half])  # "Mostrar X Mostrar x" -> "Mostrar X"
                    rect = ch.BoundingRectangle
                    in_tray = c_class.startswith("SystemTray.") or ch.AutomationId == "NotifyItemIcon" or cls != "Shell_TrayWnd"
                    if name and in_tray and rect and (rect.right - rect.left > 0):
                        found.append({"name": name, "window": "Bandeja do sistema",
                                      "rect": [rect.left, rect.top, rect.right, rect.bottom]})
                walk(ch, cls, depth + 1)

        for cls, node in roots:
            walk(node, cls)
        return found

    def get_ground_truth_screen_context(self) -> str:
        """
        Resumo curto e seguro do desktop: janelas abertas (a em foco marcada) e icones da bandeja.
        NAO le o conteudo das janelas (conversas, documentos): para isso a pessoa pede um snapshot do app.
        """
        lines: List[str] = []
        windows = self.list_windows()
        try:
            foreground = user32.GetForegroundWindow()
        except Exception:  # noqa: BLE001
            foreground = None
        seen = set()
        shown = []
        for w in windows:
            title = (w.get("title") or "").strip()
            if not title or title in seen or title.startswith("Cua.") or "Overlay" in title:
                continue
            seen.add(title)
            shown.append((title, bool(foreground) and w.get("hwnd") == foreground))
        if shown:
            lines.append("Janelas abertas (a marcada [em foco] e a ativa):")
            for title, focused in shown[:10]:
                lines.append(f"- {title}" + (" [em foco]" if focused else ""))
            if len(shown) > 10:
                lines.append(f"... e mais {len(shown) - 10} janelas")

        tray = self.list_tray_elements()
        if tray:
            lines.append("\nBandeja do sistema:")
            for item in tray:
                lines.append(f"- {item['name']}")

        lines.append("\nPara ver o conteudo de uma janela, use list_windows para pegar o id e depois snapshot com window_id.")
        return "\n".join(lines)

    def snapshot_active_or_app(self, app_query: Optional[str] = None, interactive_only: bool = True) -> Dict[str, Any]:
        """
        Captura a árvore de acessibilidade real via binário 'agent-desktop' com @ref IDs.
        Se o binário falhar no ambiente atual, faz fallback limpo para inspect_window (UIA Python).
        """
        if agent_desktop_bridge and agent_desktop_bridge.is_available():
            snap = agent_desktop_bridge.snapshot(app=app_query, interactive_only=interactive_only, compact=True)
            if snap.get("ok"):
                return {
                    "success": True,
                    "engine": "agent-desktop",
                    "snapshot": snap,
                    "formatted": agent_desktop_bridge.format_snapshot_for_llm(snap),
                }
        fallback = self.inspect_window(app_query)
        is_success = fallback.get("status") == "success"
        return {
            "success": is_success,
            "engine": "uiautomation-fallback",
            "fallback": fallback,
            "formatted": self._format_fallback_snapshot(fallback) if is_success else "",
        }

    def _format_fallback_snapshot(self, snapshot: Dict[str, Any]) -> str:
        """Formata o snapshot de fallback do UIA Python para consumo do LLM."""
        if not snapshot or snapshot.get("status") != "success":
            return ""
        lines = [f"Window: {snapshot.get('window', 'Unknown')}"]
        for el in snapshot.get("elements", []):
            ref = el.get("ref", "")
            name = el.get("name", "")
            el_type = el.get("type", el.get("raw_type", "unknown"))
            rect = el.get("rect", [])
            bounds = ""
            if len(rect) >= 4:
                x, y, r, b = rect
                bounds = f" bounds={x},{y},{r - x},{b - y}"
            lines.append(f"{ref} [{el_type}] \"{name}\"{bounds}")
        return "\n".join(lines)

    def act_on_ref(
        self,
        action: str,
        ref_id: str = "",
        text: Optional[str] = None,
        direction: str = "down",
        amount: int = 3,
        verify_app: Optional[str] = None,
        prop: str = "text",
    ) -> Dict[str, Any]:
        """
        Executa uma ação no padrão oficial agent-desktop (Observe -> Act on @ref -> Verify).
        Se o ref_id for do fallback UIA (@eN sem snapshot_id), resolve via UIA Python.
        """
        import re as _re
        act = (action or "").strip().lower().replace("-", "_")

        # Suporte direto a refs @eN gerados pelo fallback UIA
        if ref_id and _re.match(r"^@e\d+$", ref_id.strip(), _re.IGNORECASE):
            snap = self.inspect_window(verify_app)
            target_el = next((el for el in snap.get("elements", []) if el.get("ref", "").lower() == ref_id.strip().lower()), None)
            if not target_el:
                return {"success": False, "engine": "uiautomation-fallback", "error": f"Ref {ref_id} não encontrado na janela."}
            target_name = target_el.get("name", "")
            win_title = snap.get("window")
            if act in ("click", "focus", "toggle", "check", "uncheck", "expand", "collapse"):
                fb_res = self.click_element(target_name, win_title)
            elif act == "double_click":
                fb_res = self.click_element(target_name, win_title, is_double=True)
            elif act == "right_click":
                self.click_element(target_name, win_title)
                fb_res = self.press_shortcut("shift+f10", win_title)
            elif act in ("type", "set_value"):
                fb_res = self.type_into_element(target_name, text or "", win_title)
            elif act == "press":
                fb_res = self.press_shortcut(text or target_name, win_title)
            else:
                return {"success": False, "engine": "uiautomation-fallback", "error": f"Ação '{act}' requer agent-desktop ativo."}
            post = self.snapshot_active_or_app(app_query=verify_app, interactive_only=True)
            return {
                "success": fb_res.get("status") == "success",
                "engine": "uiautomation-fallback",
                "action": act,
                "ref_id": ref_id,
                "result": fb_res,
                "verified_snapshot": post.get("formatted", ""),
            }

        if not (agent_desktop_bridge and agent_desktop_bridge.is_available()):
            return {"success": False, "error": "agent-desktop não disponível neste ambiente."}

        dispatch = {
            "click": lambda: agent_desktop_bridge.click_ref(ref_id),
            "right_click": lambda: agent_desktop_bridge.right_click_ref(ref_id, headed=False),
            "type": lambda: agent_desktop_bridge.set_value_ref(ref_id, text or ""),
            "set_value": lambda: agent_desktop_bridge.set_value_ref(ref_id, text or ""),
            "clear": lambda: agent_desktop_bridge.clear_ref(ref_id),
            "focus": lambda: agent_desktop_bridge.focus_ref(ref_id),
            "select": lambda: agent_desktop_bridge.select_ref(ref_id, text or ""),
            "toggle": lambda: agent_desktop_bridge.toggle_ref(ref_id),
            "check": lambda: agent_desktop_bridge.check_ref(ref_id),
            "uncheck": lambda: agent_desktop_bridge.uncheck_ref(ref_id),
            "expand": lambda: agent_desktop_bridge.expand_ref(ref_id),
            "collapse": lambda: agent_desktop_bridge.collapse_ref(ref_id),
            "scroll": lambda: agent_desktop_bridge.scroll_ref(ref_id, direction=direction, amount=amount),
            "scroll_to": lambda: agent_desktop_bridge.scroll_to_ref(ref_id),
            "get": lambda: agent_desktop_bridge.get_prop(ref_id, prop=prop or "text"),
            "is": lambda: agent_desktop_bridge.is_state(ref_id, prop=prop or "visible"),
        }
        handler = dispatch.get(act)
        if not handler:
            return {"success": False, "error": f"Ação agent-desktop desconhecida: {action}"}

        res = handler()
        if not res.get("ok"):
            err = res.get("error") or {}
            return {
                "success": False,
                "engine": "agent-desktop",
                "error": err.get("message") or str(err),
                "code": err.get("code"),
                "raw": res,
            }

        # Loop de verificação pós-ação (Observe again to verify)
        post_snap = agent_desktop_bridge.snapshot(app=verify_app, interactive_only=True, compact=True)
        return {
            "success": True,
            "engine": "agent-desktop",
            "action": act,
            "ref_id": ref_id,
            "result": res.get("data"),
            "verified_snapshot": agent_desktop_bridge.format_snapshot_for_llm(post_snap, max_items=30)
            if post_snap.get("ok")
            else "",
        }


# Instância singleton global do controlador
desktop_controller = DesktopController()

