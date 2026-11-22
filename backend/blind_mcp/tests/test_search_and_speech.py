"""Regressao: web_search (parser do Bing e erro explicito) e stop_speaking (nada de COM entre threads)."""
import base64
import threading

import pytest

pytest.importorskip("mcp")
from blind_mcp.servers import docs  # noqa: E402

BING_HTML = """
<ol><li class="b_algo"><h2><a target="_blank" href="https://www.bing.com/ck/a?!&amp;&amp;u=a1{token}&amp;ntb=1">Welcome to <strong>Python</strong>.org</a></h2>
<div class="b_caption"><p class="b_lineclamp2">Linguagem simples e poderosa.</p></div></li></ol>
"""


def test_parse_bing_decodifica_url_real():
    token = base64.urlsafe_b64encode(b"https://www.python.org/").decode().rstrip("=")
    res = docs._parse_bing(BING_HTML.format(token=token), 5)
    assert len(res) == 1
    assert res[0]["url"] == "https://www.python.org/"
    assert res[0]["snippet"] == "Linguagem simples e poderosa."
    assert "Python" in res[0]["title"]


def test_parse_pagina_de_desafio_nao_gera_resultados():
    assert docs._parse_bing("<html>challenge</html>", 5) == []
    assert docs._parse_duckduckgo("<html>anomaly</html>", 5) == []


def test_stop_speaking_sem_fala_e_idle():
    from blind_mcp.servers import speech
    import asyncio

    speech._current["stop"] = None
    assert asyncio.run(speech.stop_speaking())["status"] == "idle"


def test_stop_speaking_sinaliza_evento_sem_tocar_no_com():
    from blind_mcp.servers import speech
    import asyncio

    ev = threading.Event()
    speech._current["stop"] = ev
    assert asyncio.run(speech.stop_speaking())["status"] == "stopped"
    assert ev.is_set()
    speech._current["stop"] = None
