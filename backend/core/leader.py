"""Dono unico de tarefas de segundo plano (eleicao de lider por trava de arquivo do sistema).

Problema: o Claude e o app Electron (e ate duas copias do mesmo servidor dentro do Claude) podem abrir os mesmos servidores
ao mesmo tempo. Tarefas de segundo plano rodando em dobro causam lembretes falados duas vezes e dois leitores do Telegram
brigando pelas mesmas mensagens.

Solucao: cada tarefa de segundo plano tem um nome ("lembretes", "telegram-polling"). Quem consegue a trava do arquivo
`<dados>/locks/<nome>.lock` e o dono e faz o trabalho; os outros ficam de reserva e tentam de novo a cada volta do laco.
A trava e do sistema operacional (msvcrt.locking): some sozinha quando o processo termina ou e morto, entao outro assume.
Ferramentas comuns (ler/gravar memoria, listar) continuam funcionando em qualquer copia: so o trabalho de fundo e exclusivo.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def lock_dir() -> Path:
    return Path(os.environ.get("BLIND_DATA_DIR") or (_BACKEND_DIR / "data")) / "locks"


class Leader:
    def __init__(self, name: str, directory: Optional[Path] = None) -> None:
        self.name = name
        self.directory = directory
        self._fh: Any = None

    @property
    def path(self) -> Path:
        return (self.directory or lock_dir()) / f"{self.name}.lock"

    @property
    def is_leader(self) -> bool:
        return self._fh is not None

    def try_acquire(self) -> bool:
        """True se esta copia e (ou acabou de virar) a dona. Nunca levanta erro."""
        if self._fh is not None:
            return True
        try:
            import msvcrt

            self.path.parent.mkdir(parents=True, exist_ok=True)
            fh = open(self.path, "a+b")
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                fh.close()
                return False
            self._fh = fh
            self._write_info()
            return True
        except Exception:  # noqa: BLE001 - sem trava possivel (ex.: sem msvcrt): nao bloqueia o trabalho
            return True

    def release(self) -> None:
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:  # noqa: BLE001
            pass
        try:
            fh.close()
        except Exception:  # noqa: BLE001
            pass

    def _write_info(self) -> None:
        # Informacao so para diagnostico, em arquivo separado (o arquivo da trava fica bloqueado para leitura).
        try:
            info = {"pid": os.getpid(), "desde": time.strftime("%Y-%m-%dT%H:%M:%S")}
            self.path.with_suffix(".json").write_text(json.dumps(info), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    def owner_info(self) -> Dict[str, Any]:
        try:
            return json.loads(self.path.with_suffix(".json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}


_REGISTRY: Dict[str, Leader] = {}


def leader_for(name: str) -> Leader:
    """Um unico objeto por nome dentro do processo (duas tarefas do mesmo processo compartilham a mesma trava)."""
    if name not in _REGISTRY:
        _REGISTRY[name] = Leader(name)
    return _REGISTRY[name]
