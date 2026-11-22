"""blind-mail e blind-drive: Gmail e Drive com servico falso (sem rede, sem credencial real)."""

import asyncio
import base64
from pathlib import Path

import pytest

from blind_mcp.servers import _google_common as common
from blind_mcp.servers import drive, mail


def b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


MSG = {
    "id": "m1",
    "labelIds": ["INBOX", "UNREAD"],
    "snippet": "Sua fatura",
    "payload": {
        "mimeType": "multipart/mixed",
        "headers": [{"name": "From", "value": "Banco <b@x.com>"}, {"name": "Subject", "value": "Fatura"},
                    {"name": "Date", "value": "Mon, 16 Nov 2026"}, {"name": "To", "value": "eu@x.com"}],
        "parts": [
            {"mimeType": "multipart/alternative", "body": {}, "parts": [
                {"mimeType": "text/html", "body": {"data": b64("<p>Ola <b>mundo</b></p><script>x()</script>")}},
            ]},
            {"mimeType": "application/pdf", "filename": "fatura.pdf", "body": {"attachmentId": "att1", "size": 10}},
        ],
    },
}


class Exec:
    def __init__(self, v):
        self.v = v

    def execute(self):
        return self.v


class FakeGmail:
    def __init__(self):
        self.sent = []

    def users(self):
        return self

    def messages(self):
        return self

    def attachments(self):
        return self

    def list(self, **kw):
        return Exec({"messages": [{"id": "m1"}]})

    def get(self, **kw):
        if "attachmentId" in str(kw) or kw.get("id") == "att1":
            return Exec({"data": b64("conteudo-pdf")})
        return Exec(MSG)

    def send(self, userId, body):
        self.sent.append(body)
        return Exec({"id": "sent1"})


@pytest.fixture
def gmail(monkeypatch, tmp_path):
    fake = FakeGmail()
    monkeypatch.setattr(mail, "_service", lambda name, version: fake)
    monkeypatch.setattr(mail, "DOWNLOAD_DIR", tmp_path / "dl")
    mail._PENDING.clear()
    return fake


def test_busca_e_leitura_de_email_com_html_e_anexo(gmail):
    r = asyncio.run(mail.gmail_buscar("is:unread"))
    assert r["total"] == 1 and r["mensagens"][0]["assunto"] == "Fatura" and r["mensagens"][0]["nao_lido"]
    m = asyncio.run(mail.gmail_ler("m1"))
    assert "Ola mundo" in m["texto"] and "x()" not in m["texto"]
    assert m["anexos"] == [{"nome": "fatura.pdf", "tipo": "application/pdf", "tamanho_bytes": 10, "attachment_id": "att1"}]


def test_baixar_anexo_nao_sobrescreve(gmail, tmp_path):
    a = asyncio.run(mail.gmail_anexo_baixar("m1", "att1", "fatura.pdf"))
    b = asyncio.run(mail.gmail_anexo_baixar("m1", "att1", "fatura.pdf"))
    assert Path(a["arquivo"]).read_text() == "conteudo-pdf"
    assert a["arquivo"] != b["arquivo"] and Path(b["arquivo"]).exists()
    c = asyncio.run(mail.gmail_anexo_baixar("m1", "att1", "..\\..\\evil:name.pdf"))
    assert Path(c["arquivo"]).parent == tmp_path / "dl"  # nome limpo, fica na pasta


def test_envio_de_email_em_duas_etapas(gmail, tmp_path):
    anexo = tmp_path / "relatorio.txt"
    anexo.write_text("dados")
    args = dict(para="a@b.com", assunto="Oi", texto="corpo", anexos=[str(anexo)])
    rascunho = asyncio.run(mail.gmail_enviar(**args))
    assert rascunho["enviado"] is False and gmail.sent == []
    assert rascunho["anexos"][0]["nome"] == "relatorio.txt"
    code = rascunho["codigo_confirmacao"]

    with pytest.raises(ValueError):  # conteudo mudou
        asyncio.run(mail.gmail_enviar(**{**args, "texto": "outro"}, codigo_confirmacao=code))
    with pytest.raises(ValueError):  # outro anexo
        asyncio.run(mail.gmail_enviar(**{**args, "anexos": []}, codigo_confirmacao=code))
    assert gmail.sent == []

    ok = asyncio.run(mail.gmail_enviar(**args, codigo_confirmacao=code))
    assert ok["enviado"] is True and len(gmail.sent) == 1
    raw = base64.urlsafe_b64decode(gmail.sent[0]["raw"]).decode(errors="replace")
    assert "a@b.com" in raw and "relatorio.txt" in raw
    with pytest.raises(ValueError):  # uso unico
        asyncio.run(mail.gmail_enviar(**args, codigo_confirmacao=code))


def test_envio_valida_destinatario_e_anexos(gmail, tmp_path):
    with pytest.raises(ValueError):
        asyncio.run(mail.gmail_enviar("sem-arroba", "a", "b"))
    with pytest.raises(FileNotFoundError):
        asyncio.run(mail.gmail_enviar("a@b.com", "a", "b", anexos=[str(tmp_path / "nao-existe.txt")]))


def test_codigo_vence(gmail, monkeypatch):
    r = asyncio.run(mail.gmail_enviar("a@b.com", "x", "y"))
    mail._PENDING[r["codigo_confirmacao"]]["criado"] -= 3600
    with pytest.raises(ValueError):
        asyncio.run(mail.gmail_enviar("a@b.com", "x", "y", codigo_confirmacao=r["codigo_confirmacao"]))


class FakeDrive:
    def __init__(self):
        self.created = []
        self.q = None

    def files(self):
        return self

    def list(self, **kw):
        self.q = kw["q"]
        return Exec({"files": [{"id": "f1", "name": "Notas", "mimeType": "application/vnd.google-apps.document",
                                "modifiedTime": "2026-11-16", "owners": [{"displayName": "Eu"}]},
                               {"id": "d1", "name": "Pasta", "mimeType": drive._FOLDER}]})

    def create(self, body, media_body, fields):
        self.created.append(body)
        return Exec({"id": "new1", "name": body["name"], "webViewLink": "https://drive/x"})


def test_drive_listar_escapa_consulta_e_marca_pasta(monkeypatch):
    fake = FakeDrive()
    monkeypatch.setattr(drive, "_service", lambda n, v: fake)
    r = asyncio.run(drive.drive_listar("d'avila", "pasta9"))
    assert "d\\'avila" in fake.q and "'pasta9' in parents" in fake.q and "trashed = false" in fake.q
    assert r["arquivos"][1]["tipo"] == "pasta"


def test_drive_enviar_em_duas_etapas(monkeypatch, tmp_path):
    fake = FakeDrive()
    monkeypatch.setattr(drive, "_service", lambda n, v: fake)
    drive._PENDING.clear()
    f = tmp_path / "doc.txt"
    f.write_text("x")
    r = asyncio.run(drive.drive_enviar(str(f)))
    assert r["enviado"] is False and fake.created == [] and r["destino"] == "raiz do Meu Drive"
    with pytest.raises(ValueError):
        asyncio.run(drive.drive_enviar(str(f), nome="outro.txt", codigo_confirmacao=r["codigo_confirmacao"]))
    ok = asyncio.run(drive.drive_enviar(str(f), codigo_confirmacao=r["codigo_confirmacao"]))
    assert ok["enviado"] is True and fake.created == [{"name": "doc.txt"}]


def test_sem_credencial_explica_o_que_fazer(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "TOKEN_FILE", tmp_path / "token.json")
    monkeypatch.setattr(common, "CLIENT_FILE", tmp_path / "client_secret.json")
    s = asyncio.run(mail.google_status())
    assert asyncio.run(drive.drive_status())["autorizado"] is False
    assert s["autorizado"] is False and "client_secret.json" in s["proximo_passo"]
    with pytest.raises(Exception, match="google_conectar"):
        common._credentials()
