"""Contratos de acessibilidade e de arquitetura do renderer Electron (src/renderer).

Compartilhado pelo oraculo `frontend` e pelo e2e_oracle. Verifica a fonte, sem abrir o Electron: as regras
que um leitor de tela e o modelo de seguranca do app exigem, e que uma regressao quebraria em silencio.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
RENDERER_DIR = BACKEND_DIR.parent / "src" / "renderer"

PRIMARY_BUTTONS = ["btn-ouvir", "btn-chat", "btn-tela", "btn-imagem", "btn-docs", "btn-escrita", "btn-canais"]
SCREEN_FILES = ["home", "chat", "models", "vision", "docs", "writer", "channels", "tools", "settings"]
EMOJI = re.compile(r"[\U00010000-\U0010ffff☀-➿]", flags=re.UNICODE)


def _read(path: Path) -> str:
    assert path.exists(), f"Arquivo do renderer não encontrado: {path}"
    return path.read_text(encoding="utf-8")


def _strip_comments(js: str) -> str:
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.DOTALL)
    return re.sub(r"(^|\s)//[^\n]*", r"\1", js)


def check_renderer_contracts(renderer_dir: Path = RENDERER_DIR) -> dict:
    index = _read(renderer_dir / "index.html")
    js_files = sorted((renderer_dir / "js").rglob("*.js"))
    css_files = sorted((renderer_dir / "styles").rglob("*.css"))
    assert js_files and css_files, "Renderer sem scripts ou estilos."
    sources = {p: _read(p) for p in [renderer_dir / "index.html", *js_files, *css_files]}
    # Regras de codigo valem para o codigo, nao para comentarios.
    all_js = "\n".join(_strip_comments(sources[p]) for p in js_files)

    # A interface HTML antiga (servida pelo backend) nao pode voltar.
    assert not (BACKEND_DIR / "ui" / "index.html").exists(), "backend/ui/index.html ainda existe: a interface é o Electron."

    # 1. Documento: idioma, estrutura de software desktop (sem skip-link de pagina web) e marcos
    assert 'lang="pt-BR"' in index, "index.html sem lang=pt-BR."
    assert 'skip-link' not in index, "Software desktop não deve ter link 'pular para o conteúdo' de página web."
    assert re.search(r"<nav[^>]*aria-label=", index), "A navegação precisa de aria-label."
    assert 'id="main"' in index and "<main" in index, "Falta o marco <main>."
    assert 'aria-live="polite"' in index and 'aria-live="assertive"' in index, "Faltam as regiões ao vivo."
    assert 'type="module"' in index, "Os scripts devem ser módulos."

    # 2. Seguranca: CSP restritiva, sem script inline, sem fetch (tudo por IPC)
    csp = re.search(r'Content-Security-Policy"\s+content="([^"]+)"', index)
    assert csp, "Falta a Content-Security-Policy."
    assert "connect-src 'none'" in csp.group(1) and "script-src 'self'" in csp.group(1), f"CSP frouxa: {csp.group(1)}"
    assert "'unsafe-inline'" not in csp.group(1) and "'unsafe-eval'" not in csp.group(1), "CSP não pode ter unsafe-*."
    assert not re.search(r"<script(?![^>]*\bsrc=)", index), "Script inline no index.html."
    assert not re.search(r"\son[a-z]+\s*=", index), "Manipulador de evento inline no HTML."
    assert not re.search(r"(?<![\w.])fetch\(", all_js), "O renderer não pode usar fetch: toda chamada passa pelo IPC (window.blind.api)."
    assert "innerHTML" not in all_js, "innerHTML proibido: use textContent/h()."
    assert not re.search(r"(?<![\w.])(prompt|alert|confirm)\(", all_js), "prompt/alert/confirm não existem no Electron: use lib/dialog.js."
    assert "webkitSpeechRecognition" not in all_js and "SpeechRecognition" not in all_js, "A API de fala do navegador não funciona no Electron."

    # 3. Botoes primarios e ausencia de secoes obsoletas
    home = sources[renderer_dir / "js" / "screens" / "home.js"]
    for btn_id in PRIMARY_BUTTONS:
        assert f"'{btn_id}'" in home, f"Botão primário '{btn_id}' ausente na tela inicial."
    assert "aria-expanded" not in home, "Os comandos da tela inicial não são expansíveis (sem aria-expanded)."
    assert "vision-panel" not in all_js and "vision-panel" not in index, "Região obsoleta vision-panel."

    # 4. Formatador semantico e higienizacao
    a11y = sources[renderer_dir / "js" / "lib" / "a11y.js"]
    assert "formatAccessibleMessageHtml" in a11y and "sanitizeScreenReaderText" in a11y, "Funções de leitor de tela ausentes."
    assert "createElement('ol')" in a11y and "createElement('li')" in a11y and "createElement('ul')" in a11y, "Listas semânticas ausentes."

    # 5. Cada tela: titulo h1 focavel e regiao identificada
    for name in SCREEN_FILES:
        src = sources[renderer_dir / "js" / "screens" / f"{name}.js"]
        assert re.search(r"h\(\s*'h1',\s*\{[^}]*tabindex:\s*'-1'", src), f"Tela '{name}' sem h1 focável (tabindex -1)."
        assert "aria-labelledby" in src, f"Tela '{name}' sem aria-labelledby na região."

    # 6. Voz no app: gravacao por getUserMedia e envio ao Whisper do backend
    assert "getUserMedia" in sources[renderer_dir / "js" / "lib" / "recorder.js"], "Falta a gravação por microfone."
    assert "/api/stt/transcribe" in sources[renderer_dir / "js" / "lib" / "voice.js"], "O ditado deve usar o Whisper do backend."

    # 7. Sem emojis em nenhum arquivo do renderer
    for path, text in sources.items():
        found = EMOJI.findall(text)
        assert not found, f"Emojis proibidos em {path.name}: {found}"

    return {"files": len(sources), "screens": len(SCREEN_FILES)}
