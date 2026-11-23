"""Processo de uma transcricao: le um JSON do stdin, escreve um JSON no stdout e termina.

Roda a parte pesada (numpy, faster-whisper, modelo) fora do servidor MCP: importar essas DLLs dentro de um servidor stdio ja
em andamento trava no Windows, e assim o modelo nao fica ocupando memoria depois. Uso: python -m blind_mcp.audio_worker
Entrada: {"audio_base64": str|null, "file_path": str|null, "language": str|null}. Saida (ultima linha): o resultado do Whisper
ou {"error": "..."}.
"""

from __future__ import annotations

import json
import sys


def processar(payload: dict) -> dict:
    from .servers import stt

    return stt._transcribe(stt._decode(payload.get("audio_base64"), payload.get("file_path")), payload.get("language"), None)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        saida = processar(payload)
    except Exception as exc:  # noqa: BLE001
        saida = {"error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write("\n" + json.dumps(saida, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0 if "error" not in saida else 1


if __name__ == "__main__":
    raise SystemExit(main())
