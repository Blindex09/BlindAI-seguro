"""close_app em app UWP: fecha pela janela (botao Fechar), nunca ambiguo e nunca na janela errada."""
from core.desktop.agent_desktop_bridge import AgentDesktopBridge


def make(windows, focused_id=None, close_ref="@s:e1"):
    b = AgentDesktopBridge()
    calls = []
    b.list_windows = lambda app=None: {"ok": True, "data": [dict(w, is_focused=(w["id"] == focused_id)) for w in windows]}
    b.focus_window = lambda window_id=None, app=None: calls.append(("focus", window_id)) or {"ok": True}
    b.find = lambda **kw: {"ok": True, "data": {"matches": [{"ref_id": close_ref}] if close_ref and kw["name"] == "Fechar" else []}}
    b.click_ref = lambda ref, headed=False: calls.append(("click", ref)) or {"ok": True}
    return b, calls


CALC = {"id": "w-1", "title": "Calculadora", "app_name": "CalculatorApp.exe", "visible": True}
NOTE = {"id": "w-2", "title": "Bloco de notas", "app_name": "Notepad.exe", "visible": True}
ORIG = {"ok": False, "error": {"code": "APP_NOT_FOUND"}}


def test_fecha_pela_janela():
    b, calls = make([CALC, NOTE], focused_id="w-1")
    res = b._close_window_fallback("Calculadora", ORIG)
    assert res["ok"] and calls == [("focus", "w-1"), ("click", "@s:e1")]


def test_aceita_nome_do_exe():
    b, calls = make([CALC, NOTE], focused_id="w-1")
    assert b._close_window_fallback("CalculatorApp.exe", ORIG)["ok"]


def test_ambiguo_nao_fecha_nada():
    b, calls = make([CALC, dict(CALC, id="w-3"), NOTE])
    res = b._close_window_fallback("Calculadora", ORIG)
    assert res["error"]["code"] == "AMBIGUOUS_WINDOW" and calls == []


def test_foco_errado_nao_clica():
    b, calls = make([CALC, NOTE], focused_id="w-2")
    res = b._close_window_fallback("Calculadora", ORIG)
    assert res["error"]["code"] == "FOCUS_MISMATCH" and ("click", "@s:e1") not in calls


def test_sem_janela_devolve_erro_original():
    b, _ = make([NOTE])
    assert b._close_window_fallback("Calculadora", ORIG) is ORIG
