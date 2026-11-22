"""Os testes gravam em pastas temporarias: libera so a pasta temporaria do sistema para a regra de gravacao do blind-docs
(seguranca.py). Em uso normal, so Downloads, Documentos, Musicas e Videos valem."""

import tempfile

import pytest


@pytest.fixture(autouse=True)
def _pastas_de_teste(monkeypatch):
    monkeypatch.setenv("BLIND_PASTAS_EXTRAS", tempfile.gettempdir())
    yield
