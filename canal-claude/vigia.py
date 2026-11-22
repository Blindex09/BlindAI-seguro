"""Vigia da sessao Claude dos canais (rode so por Monitor: `python vigia.py`).

Faz duas coisas a cada 2 segundos:
1. Grava o batimento em backend/data/canal_claude_vivo.json: e assim que o Blind sabe que a sessao esta viva
   (sem batimento, o modelo local responde no lugar).
2. Imprime `PEDIDO_NOVO` quando aparece pedido aberto na fila (backend/data/google_fila.json).
Nao le texto de mensagens: so os estados.
"""
import json
import time
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "backend" / "data"
FILA = DATA / "google_fila.json"
VIVO = DATA / "canal_claude_vivo.json"
anunciados = set()

while True:
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        VIVO.write_text(json.dumps({"ts": time.time()}), encoding="utf-8")
    except OSError:
        pass
    try:
        fila = json.loads(FILA.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        fila = []
    abertos = {i.get("id") for i in fila if i.get("estado") == "aberto"}
    if abertos - anunciados:
        print("PEDIDO_NOVO", flush=True)
    anunciados = abertos  # so lembra dos que ainda estao abertos
    time.sleep(2)
