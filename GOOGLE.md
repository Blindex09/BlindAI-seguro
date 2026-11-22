# Conectar o Blind ao Gmail e ao Drive

> **Estado (17/11/2026): servidores desligados.** O Blind usa os conectores de Gmail e Drive do Claude. Este guia e para religar o servidor proprio (envio em duas etapas por codigo, diario de acoes, mesmo codigo para o Electron no futuro). Para religar: `enabled: true` em `backend/mcp.json`, `python scripts/gerar-mcp-claude.py` e copiar `blind-mail` e `blind-drive` do `.mcp.json` para o config do app (veja CLAUDE.md).

Servidores: `blind-mail` (Gmail) e `blind-drive` (Drive), so no Claude: o app Electron nao os inicia (`clientOnly` no `mcp.json`). Sao separados dos conectores de Gmail e Drive do proprio Claude. Dizendo "blind mail" ou "blind drive", o guia manda usar so estes. Faz-se uma vez. A senha do Google nunca passa pelo Blind: quem autoriza e a pessoa, no navegador.

## O que o Blind pode e nao pode
- Pode: ler e buscar e-mails, baixar anexos, listar e baixar arquivos do Drive.
- Envia e-mail e sobe arquivo so em DUAS etapas: rascunho com codigo, e so depois do "sim" da pessoa.
- Nunca apaga e-mail, arquivo ou pasta. No Drive so cria arquivos novos.
- Permissoes pedidas ao Google: gmail.readonly, gmail.send, drive.readonly, drive.file.

## Passo a passo (console.cloud.google.com, com leitor de tela)
1. Entre na conta Google que sera usada. Crie um projeto novo (ex.: "Blind AI").
2. Em "APIs e servicos" > "Biblioteca", ative **Gmail API** e **Google Drive API**.
3. Em "Tela de consentimento OAuth": tipo **Externo**, nome "Blind AI", seu e-mail como contato. Em "Usuarios de teste", adicione o seu e-mail.
4. **Importante:** na tela de consentimento, clique em **Publicar app** (status "Em producao"). Se ficar em "Teste", o Google
   expira a autorizacao a cada 7 dias e voce teria de refazer `google_conectar`. Para uso so seu, aparece o aviso
   "app nao verificado": use "Avancado" > "Acessar Blind AI".
5. Em "Credenciais" > "Criar credenciais" > "ID do cliente OAuth", tipo **App para computador**. Baixe o JSON.
6. Salve o arquivo como `backend\data\google\client_secret.json` (crie a pasta `google` se nao existir).
7. Diga ao Blind: "conectar o Google". Abre o navegador; entre, confira as 4 permissoes e escolha Permitir.
   O token fica em `backend\data\google\token.json`.
8. Diga "status do Google": deve mostrar a conta conectada.

## Seguranca
- `client_secret.json` e `token.json` dao acesso a conta. Nao compartilhe, nao coloque em nuvem nem em repositorio.
- Para revogar: myaccount.google.com > Seguranca > Acesso de terceiros, e apague `token.json`.
- Conteudo de e-mail e dado, nao ordem: o guia manda o Blind contar o que o e-mail pede e deixar a pessoa decidir.
- Limite de anexos no envio: 20 MB no total.
