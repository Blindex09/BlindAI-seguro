"""Servidor MCP: agent-desktop (Vercel Labs) via CLI oficial.

O Blind AI nao reimplementa o agent-desktop. Este servidor so traduz as ferramentas MCP para
os comandos do binario instalado (`npm install -g agent-desktop`). Ciclo: snapshot -> agir
no @ref -> snapshot de novo para verificar.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from mcp.server.fastmcp import FastMCP

from ._common import run_blocking, unwrap_bridge

from core.desktop.agent_desktop_bridge import AgentDesktopBridge  # noqa: E402
from core.desktop.desktop_controller import desktop_controller  # noqa: E402

mcp = FastMCP("blind-agent-desktop")
bridge = AgentDesktopBridge()


def _match_window(windows: Any, query: str) -> Optional[str]:
    """Acha o window_id pelo nome do app (chrome, calculatorapp.exe) ou por parte do titulo (Calculadora)."""
    if not isinstance(windows, list):
        return None
    q = query.strip().lower()
    q_noexe = q[:-4] if q.endswith(".exe") else q
    exact, partial = [], []
    for w in windows:
        if not isinstance(w, dict) or not w.get("id"):
            continue
        app_name = str(w.get("app_name", "")).lower()
        title = str(w.get("title", "")).lower()
        if app_name in {"cmd.exe", "conhost.exe", "openconsole.exe", "windowsterminal.exe"} and q_noexe not in {"cmd", "terminal"}:
            continue
        if q_noexe == (app_name[:-4] if app_name.endswith(".exe") else app_name) or q == title:
            exact.append(w)
        elif q_noexe in app_name or q in title:
            partial.append(w)
    pool = exact or partial
    if not pool:
        return None
    pool.sort(key=lambda w: not w.get("is_focused"))  # prefere a janela em foco
    return str(pool[0]["id"])


async def _resolve(app: Optional[str], window_id: Optional[str]) -> tuple:
    """Aceita nome de app ou titulo de janela. Apps UWP (Calculadora, Configuracoes) so abrem por window_id."""
    if window_id or not app:
        return app, window_id
    try:
        listed = unwrap_bridge(await run_blocking(bridge.list_windows, None))
    except Exception:  # noqa: BLE001
        return app, window_id
    found = _match_window(listed, app)
    return (None, found) if found else (app, None)


@mcp.tool()
async def status() -> Any:
    """Estado do agent-desktop: plataforma, permissoes de acessibilidade e superficies suportadas."""
    return unwrap_bridge(await run_blocking(bridge.status))


@mcp.tool()
async def list_windows(app: Optional[str] = None) -> Any:
    """Lista as janelas abertas (opcionalmente de um aplicativo): titulo, app, se esta em foco ou minimizada e o id
    (window_id) para usar em snapshot/window_action."""
    data = unwrap_bridge(await run_blocking(bridge.list_windows, app))
    if isinstance(data, list):
        keep = ("title", "app_name", "is_focused", "minimized", "id")
        return [{k: w[k] for k in keep if k in w} for w in data if isinstance(w, dict)]
    return data


@mcp.tool()
async def list_apps(app: Optional[str] = None) -> Any:
    """Lista os aplicativos em execucao com janelas visiveis."""
    return unwrap_bridge(await run_blocking(bridge.list_apps, app))


@mcp.tool()
async def snapshot(
    app: Optional[str] = None,
    window_id: Optional[str] = None,
    interactive_only: bool = True,
    max_items: int = 60,
) -> str:
    """Le a arvore de acessibilidade da janela e devolve elementos com @ref_id para usar nas outras ferramentas.
    `app` aceita o nome do aplicativo ou parte do titulo da janela (ex: 'calculadora', 'chrome').
    Sempre chame de novo depois de agir para confirmar o resultado."""
    app, window_id = await _resolve(app, window_id)
    res = await run_blocking(bridge.snapshot, app=app, window_id=window_id, interactive_only=interactive_only)
    data = unwrap_bridge(res)
    text = bridge.format_snapshot_for_llm(res, max_items=max_items)
    return text or str(data)


@mcp.tool()
async def find(
    name: Optional[str] = None, role: Optional[str] = None, app: Optional[str] = None, window_id: Optional[str] = None
) -> Any:
    """Procura elementos por nome visivel e/ou papel (button, edit, listitem...). Devolve @ref_id."""
    app, window_id = await _resolve(app, window_id)
    return unwrap_bridge(await run_blocking(bridge.find, name=name, role=role, app=app, window_id=window_id))


@mcp.tool()
async def get_property(ref_id: str, prop: str = "text") -> Any:
    """Le uma propriedade de um elemento. prop aceita: text, value, title, bounds, role, states.
    Se der STALE_REF, a tela mudou: use find (por nome) ou snapshot para pegar um @ref novo."""
    return unwrap_bridge(await run_blocking(bridge.get_prop, ref_id, prop))


@mcp.tool()
async def screenshot(app: Optional[str] = None, window_id: Optional[str] = None, path: Optional[str] = None) -> Any:
    """Salva uma captura da janela e devolve o caminho do arquivo."""
    return unwrap_bridge(await run_blocking(bridge.screenshot, app, window_id, path))


async def _janelas_estado() -> Optional[Dict[str, tuple]]:
    """Foto leve das janelas abertas (id -> (titulo, app)). None se nao deu para ler."""
    try:
        listed = unwrap_bridge(await run_blocking(bridge.list_windows, None))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(listed, list):
        return None
    return {str(w["id"]): (str(w.get("title", "")), str(w.get("app_name", ""))) for w in listed if isinstance(w, dict) and w.get("id")}


def _diferenca(antes: Optional[Dict[str, tuple]], depois: Optional[Dict[str, tuple]]) -> Dict[str, Any]:
    """Resume o que mudou entre duas fotos das janelas, em frases curtas para ouvir."""
    if antes is None or depois is None:
        return {"verificado": False, "resumo": "Nao consegui comparar as janelas antes e depois; confira com snapshot."}
    novas = [depois[i] for i in depois if i not in antes]
    fechadas = [antes[i] for i in antes if i not in depois]
    renomeadas = [(antes[i][0], depois[i][0]) for i in depois if i in antes and antes[i][0] != depois[i][0]]
    partes: List[str] = []
    if novas:
        partes.append("Abriu: " + "; ".join(f"{t or '(sem titulo)'} ({a})" for t, a in novas))
    if fechadas:
        partes.append("Fechou: " + "; ".join(f"{t or '(sem titulo)'} ({a})" for t, a in fechadas))
    if renomeadas:
        partes.append("Titulo mudou: " + "; ".join(f"'{a}' virou '{b}'" for a, b in renomeadas))
    return {
        "verificado": True,
        "janelas_novas": [{"titulo": t, "app": a} for t, a in novas],
        "janelas_fechadas": [{"titulo": t, "app": a} for t, a in fechadas],
        "titulos_mudaram": [{"antes": a, "depois": b} for a, b in renomeadas],
        "resumo": " | ".join(partes) if partes else "Nenhuma janela nova, fechada ou renomeada. A mudanca, se houve, foi dentro da mesma janela: use snapshot para ver.",
    }


async def _com_mudancas(acao: Any) -> Dict[str, Any]:
    """Roda a acao (funcao sem argumentos que devolve o resultado) e anexa o que mudou nas janelas."""
    import asyncio

    antes = await _janelas_estado()
    resultado = await acao()
    await asyncio.sleep(0.6)  # da tempo de um dialogo ou janela aparecer
    depois = await _janelas_estado()
    return {"resultado": resultado, "mudancas": _diferenca(antes, depois)}


@mcp.tool()
async def click(ref_id: str, kind: Literal["click", "right"] = "click") -> Any:
    """Aciona um elemento pelo @ref_id pela acessibilidade (clique simples ou menu de contexto), sem mouse real.
    Devolve `resultado` e `mudancas` (janelas que abriram, fecharam ou mudaram de titulo): leia o resumo para a pessoa.
    Se o app nao aceitar a acao, devolve erro: nao ha como forcar com mouse ou teclado."""

    async def acao() -> Any:
        if kind == "right":
            res = await run_blocking(bridge.right_click_ref, ref_id, False)
        else:
            res = await run_blocking(bridge.click_ref, ref_id)
        return unwrap_bridge(res)

    return await _com_mudancas(acao)


@mcp.tool()
async def double_click(ref_id: str, triplo: bool = False) -> Any:
    """Duplo clique (ou triplo com triplo=true, que seleciona a linha) em um elemento pelo @ref_id. Devolve `mudancas`."""
    fn = bridge.triple_click_ref if triplo else bridge.double_click_ref
    return await _com_mudancas(lambda: _async_unwrap(fn, ref_id))


@mcp.tool()
async def hover(ref_id: str) -> Any:
    """Passa o ponteiro sobre um elemento (abre menus e dicas que so aparecem ao passar o mouse). Devolve `mudancas`."""
    return await _com_mudancas(lambda: _async_unwrap(bridge.hover_ref, ref_id))


@mcp.tool()
async def press_keys(keys: str, app: Optional[str] = None, window_id: Optional[str] = None) -> Any:
    """Aperta teclas ou atalhos EM UMA JANELA que voce escolhe (app ou window_id e obrigatorio), ex: 'enter', 'tab', 'ctrl+s',
    'alt+f4', 'f5'. A ferramenta da foco na janela, CONFIRMA que ela ficou em foco e so entao aperta; se nao conseguir, nao
    aperta nada e diz isso. Nunca aperta teclas na janela do proprio Claude. Use quando click/type_text nao bastam (Enter para
    enviar formulario, atalho de menu). Um guarda solta tecla presa logo depois. Antes de atalhos que fecham, enviam ou apagam,
    confirme com a pessoa. Devolve `mudancas`: leia o resumo e confira o resultado."""
    import asyncio

    if not (keys or "").strip():
        raise ValueError("Informe as teclas, ex: 'enter' ou 'ctrl+s'.")
    if not (app or window_id):
        raise ValueError("Diga em qual janela apertar (app ou window_id): sem isso as teclas poderiam cair na janela errada.")
    app_r, wid = await _resolve(app, window_id)
    if not wid:
        raise ValueError(f"Nao achei a janela '{app}'. Use list_windows.")
    listed = unwrap_bridge(await run_blocking(bridge.list_windows, None))
    alvo = next((w for w in listed if isinstance(w, dict) and w.get("id") == wid), None)
    if alvo is None:
        raise ValueError("Essa janela nao existe mais. Use list_windows.")
    if str(alvo.get("app_name", "")).lower() == "claude.exe":
        raise ValueError("Nao aperto teclas na janela do Claude: e onde a pessoa conversa comigo.")

    async def acao() -> Any:
        for _ in range(3):
            await run_blocking(bridge.focus_window, wid, None)
            await asyncio.sleep(0.35)
            atual = unwrap_bridge(await run_blocking(bridge.list_windows, None))
            if any(isinstance(w, dict) and w.get("id") == wid and w.get("is_focused") for w in atual):
                return unwrap_bridge(await run_blocking(bridge.press_keys, keys.strip(), True))
        raise RuntimeError(
            f"Nao consegui dar foco em '{alvo.get('title')}'. NAO apertei nenhuma tecla. Peca para a pessoa clicar nessa janela."
        )

    return await _com_mudancas(acao)


@mcp.tool()
async def type_text(ref_id: str, text: str, replace: bool = False) -> Any:
    """Escreve texto em um campo pelo @ref_id, direto pelo valor do campo (sem apertar teclas).
    Com replace=true troca o conteudo todo; com replace=false acrescenta ao fim do que ja existe.
    Devolve `confirmado` (o campo ficou mesmo com o texto?) e `mudancas`. So diga que escreveu se confirmado for true."""
    alvo = text

    async def acao() -> Any:
        nonlocal alvo
        if not replace:
            current = ""
            for prop in ("value", "text"):
                got = unwrap_bridge(await run_blocking(bridge.get_prop, ref_id, prop))
                val = got.get("value") if isinstance(got, dict) else got
                if isinstance(val, str):
                    current = val
                    break
            alvo = current + text
        return unwrap_bridge(await run_blocking(bridge.set_value_ref, ref_id, alvo))

    out = await _com_mudancas(acao)
    confirmado: Optional[bool] = None
    try:
        got = unwrap_bridge(await run_blocking(bridge.get_prop, ref_id, "value"))
        lido = got.get("value") if isinstance(got, dict) else got
        if isinstance(lido, str):
            confirmado = lido.replace("\r\n", "\n").strip() == alvo.replace("\r\n", "\n").strip()
    except Exception:  # noqa: BLE001
        confirmado = None
    out["confirmado"] = confirmado
    if confirmado is None:
        out["aviso"] = "Nao consegui reler o campo: confirme com get_property ou snapshot antes de dizer que escreveu."
    elif not confirmado:
        out["aviso"] = "O campo nao ficou com o texto esperado. Nao diga que deu certo; releia com get_property."
    return out


@mcp.tool()
async def element_action(
    ref_id: str,
    action: Literal["focus", "clear", "toggle", "check", "uncheck", "expand", "collapse", "scroll_to", "select"],
    value: Optional[str] = None,
) -> Any:
    """Acao simples em um elemento, pela acessibilidade: focar, limpar, alternar, marcar, expandir, rolar ate ele ou selecionar um valor."""
    table = {
        "focus": bridge.focus_ref,
        "clear": bridge.clear_ref,
        "toggle": bridge.toggle_ref,
        "check": bridge.check_ref,
        "uncheck": bridge.uncheck_ref,
        "expand": bridge.expand_ref,
        "collapse": bridge.collapse_ref,
        "scroll_to": bridge.scroll_to_ref,
    }
    if action == "select":
        if value is None:
            raise ValueError("A acao select exige 'value'.")
        return await _com_mudancas(lambda: _async_unwrap(bridge.select_ref, ref_id, value))
    return await _com_mudancas(lambda: _async_unwrap(table[action], ref_id))


async def _async_unwrap(fn: Any, *args: Any) -> Any:
    return unwrap_bridge(await run_blocking(fn, *args))


@mcp.tool()
async def descrever_janela(app: Optional[str] = None, window_id: Optional[str] = None, pergunta: Optional[str] = None) -> Any:
    """Plano B quando um app nao expoe seus elementos na acessibilidade: captura a janela e pede a um modelo de visao
    uma descricao falada (botoes, textos, mensagens de erro, onde esta cada coisa). So le a tela; nao clica nem digita.
    `pergunta` e opcional (ex: 'o que diz o aviso vermelho?'). Pode demorar alguns segundos e usa a chave de visao configurada."""
    import os

    from config.settings import config  # noqa: E402
    from core.vision.smart_vision_router import smart_vision_router  # noqa: E402

    app, window_id = await _resolve(app, window_id)
    shot = unwrap_bridge(await run_blocking(bridge.screenshot, app, window_id, None))
    path = shot.get("path") if isinstance(shot, dict) else shot
    if not isinstance(path, str) or not os.path.isfile(path):
        raise RuntimeError("Nao consegui capturar a janela para descrever.")
    key = (getattr(config, "gemini_api_key", "") or os.getenv("GEMINI_API_KEY", "")
           or getattr(config, "openai_api_key", "") or os.getenv("OPENAI_API_KEY", ""))
    prompt = pergunta or ("Descreva esta janela de aplicativo para uma pessoa cega: titulo, menus, botoes, campos, textos, "
                          "mensagens de erro e o que esta selecionado, na ordem em que aparecem.")
    descricao = await smart_vision_router.describe_multimodal(
        file_path=path, provider="auto", api_key=key, prompt_override=prompt)
    return {"ok": True, "captura": path, "descricao": descricao,
            "aviso": "Descricao feita por modelo de visao: pode errar. Para agir, ainda precisa de um @ref (snapshot)."}


@mcp.tool()
async def scroll(ref_id: str, direction: Literal["up", "down", "left", "right"] = "down", amount: int = 3) -> Any:
    """Rola um elemento rolavel."""
    return unwrap_bridge(await run_blocking(bridge.scroll_ref, ref_id, direction, amount))


async def _wait_window(target: str, seconds: float) -> Optional[Dict[str, Any]]:
    """Espera uma janela do app aparecer (por nome do processo ou titulo). Devolve titulo, app e id, ou None."""
    import asyncio
    import time

    # Nome limpo: ignora caminho e extensao ("C:\x\calc.exe" -> "calc").
    query = target.replace("/", "\\").split("\\")[-1].strip()
    deadline = time.monotonic() + seconds
    while True:
        try:
            listed = unwrap_bridge(await run_blocking(bridge.list_windows, None))
        except Exception:  # noqa: BLE001
            listed = None
        wid = _match_window(listed, query) if listed else None
        if wid:
            for w in listed:
                if w.get("id") == wid:
                    return {k: w[k] for k in ("title", "app_name", "id") if k in w}
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(1.0)


def _can_shell_start(target: str) -> bool:
    """So tenta pelo shell o que existe (caminho ou executavel no PATH): senao o Windows abre uma caixa de erro."""
    import shutil
    from pathlib import Path

    return bool(shutil.which(target)) or Path(target).exists()


def _shell_start(target: str) -> None:
    import subprocess

    subprocess.Popen(["cmd", "/c", "start", "", target], creationflags=0x08000000)  # CREATE_NO_WINDOW


@mcp.tool()
async def launch_app(target: str, activate: bool = True) -> Any:
    """Abre um aplicativo pelo nome ou caminho e opcionalmente o traz para frente. So diz que abriu se a janela
    aparecer de fato; senao tenta outro caminho e, se ainda falhar, devolve erro (nunca um falso sucesso)."""
    try:
        result = unwrap_bridge(await run_blocking(bridge.launch_app, target, activate))
    except Exception as exc:  # noqa: BLE001
        result = {"launch_error": str(exc)}
    window = await _wait_window(target, 12.0)
    if window is None:
        # O launch do agent-desktop as vezes devolve sucesso sem abrir nada (ex.: calc no Windows 11). Tenta pelo shell.
        if await run_blocking(_can_shell_start, target):
            await run_blocking(_shell_start, target)
            window = await _wait_window(target, 15.0)
    if window is None:
        raise RuntimeError(
            f"Nao consegui abrir '{target}': nenhuma janela apareceu. Confira o nome do aplicativo ou abra pelo menu Iniciar."
        )
    out = dict(result) if isinstance(result, dict) else {"result": result}
    out.pop("launch_error", None)
    out["window"] = window
    return out


@mcp.tool()
async def close_app(app: str, force: bool = False) -> Any:
    """Fecha um aplicativo. Use force=true somente se o fechamento normal falhar."""
    return unwrap_bridge(await run_blocking(bridge.close_app, app, force))


@mcp.tool()
async def window_action(
    action: Literal["focus", "minimize", "maximize", "restore"],
    app: Optional[str] = None,
    window_id: Optional[str] = None,
) -> Any:
    """Foca, minimiza, maximiza ou restaura uma janela por aplicativo ou window_id."""
    fn = {
        "focus": lambda: bridge.focus_window(window_id=window_id, app=app),
        "minimize": lambda: bridge.minimize_window(app=app, window_id=window_id),
        "maximize": lambda: bridge.maximize_window(app=app, window_id=window_id),
        "restore": lambda: bridge.restore_window(app=app, window_id=window_id),
    }[action]
    return unwrap_bridge(await run_blocking(fn))


@mcp.tool()
async def notifications(action: Literal["list", "dismiss", "dismiss_all"] = "list", index: int = 0) -> Any:
    """Lista ou dispensa notificacoes do Windows."""
    if action == "dismiss":
        return unwrap_bridge(await run_blocking(bridge.dismiss_notification, index))
    if action == "dismiss_all":
        return unwrap_bridge(await run_blocking(bridge.dismiss_all_notifications))
    return unwrap_bridge(await run_blocking(bridge.list_notifications))


@mcp.tool()
async def clipboard(action: Literal["get", "set", "clear"] = "get", text: Optional[str] = None) -> Any:
    """Le, define ou limpa a area de transferencia."""
    if action == "set":
        if text is None:
            raise ValueError("A acao set exige 'text'.")
        return unwrap_bridge(await run_blocking(bridge.clipboard_set, text))
    if action == "clear":
        return unwrap_bridge(await run_blocking(bridge.clipboard_clear))
    return unwrap_bridge(await run_blocking(bridge.clipboard_get))


@mcp.tool()
async def wait_for(
    element: Optional[str] = None,
    text: Optional[str] = None,
    window: Optional[str] = None,
    ms: Optional[int] = None,
    timeout_ms: int = 10000,
) -> Any:
    """Espera um elemento, texto ou janela aparecer, ou apenas uma pausa em milissegundos."""
    return unwrap_bridge(
        await run_blocking(bridge.wait_for, ms=ms, element=element, text=text, window=window, timeout_ms=timeout_ms)
    )


@mcp.tool()
async def screen_context() -> str:
    """Estado geral da tela e da bandeja do sistema (janelas abertas e icones reais da area de notificacao) via UI Automation."""
    return await run_blocking(desktop_controller.get_ground_truth_screen_context)


@mcp.tool()
async def list_tray() -> List[Dict[str, Any]]:
    """Lista todos os icones e botoes presentes na bandeja do sistema (area de notificacao e overflow) via UI Automation."""
    return await run_blocking(desktop_controller.list_tray_elements)


if __name__ == "__main__":
    from . import _audit

    _audit.install_audit(mcp, "agent-desktop")
    mcp.run()
