# Conector remoto do Blind AI (só leitura)

Esta versão do Blind AI existe para a revisão do conector remoto. O Blind local, no computador, não mudou. O que mudou é o gateway que o Claude do celular e da web usa.

## O que o gateway faz

- Sobe só os servidores de `backend/mcp.remote.json`. O `mcp.json` do computador inteiro não é lido.
- Oferece e executa só as ferramentas de `backend/blind_mcp/remote_allowlist.py`. Todas são de leitura. Qualquer outro nome é recusado, mesmo que o servidor o tenha.
- Não tem terminal, arquivos, controle do mouse e do teclado, WhatsApp, Telegram, e-mail, Drive nem cofre.
- Respeita as ferramentas escondidas do modelo ao chamar (`call_raw(..., from_model=True)`).
- Liga a proteção contra DNS rebinding. Só aceita o Host de `BLIND_REMOTE_HOSTS` (padrão `127.0.0.1` e `localhost`).

## O que ainda falta

- **Login de verdade.** O caminho da URL ainda tem um segredo, e isso não é login. Antes de abrir qualquer túnel, falta pôr OAuth ou um túnel com identidade na frente.
- Se uma ferramenta que envia ou apaga entrar um dia na lista, a confirmação precisa vir da pessoa, por voz ou teclado, e não do modelo. Hoje nenhuma entra.

## Como rodar

```powershell
cd backend
$env:PYTHONPATH = "."
python -m blind_mcp.remote_gateway
```

Para incluir uma ferramenta, ela passa nas três perguntas de `remote_allowlist.py` e entra na lista numa revisão. Os testes estão em `backend/blind_mcp/tests/test_remote_gateway.py`.
