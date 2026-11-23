# Conector remoto do Blind AI (só leitura)

Esta versão do Blind AI existe para a revisão do conector remoto. O Blind local, no computador, não mudou. O que mudou é o gateway que o Claude do celular e da web usa.

## O que o gateway faz

- Sobe só os servidores de `backend/mcp.remote.json`. O `mcp.json` do computador inteiro não é lido.
- Oferece e executa só as ferramentas de `backend/blind_mcp/remote_allowlist.py`. Todas são de leitura. Qualquer outro nome é recusado, mesmo que o servidor o tenha.
- PDF (`read_document`) e imagem (`describe_image`) entram por conteúdo em base64 ou por link público da web (`url`). O gateway mesmo baixa o link, recusa endereço interno (localhost, rede local, nuvem), confere cada redirecionamento e limita o tamanho. **IP fixo:** o nome é resolvido e conferido uma vez, dentro da própria conexão, e o socket abre nesse IP já conferido; um DNS que troca de resposta entre a conferência e a conexão (DNS rebinding) não tem como ser aproveitado, nem num redirecionamento. Proxy do ambiente é ignorado. O mesmo vale para `web_read`. Qualquer argumento de caminho, chave de API, provedor ou modelo é recusado e nem aparece no esquema da ferramenta.
- `blindaudio` transcreve áudio em texto (Whisper, no computador do Blind; o áudio não vai para serviço de IA). Entra por base64 (curto, até 30 MB) ou por link público (`url`); caminho de arquivo é recusado aqui. É do próprio gateway, como o `comecar`, e roda num processo que termina ao acabar. No Blind local a mesma ferramenta (`blindaudio`, do servidor `blind`) também aceita caminho de arquivo. O ditado ao vivo (`blind-stt`) continua só no app e escondido do modelo.
- `comecar` entrega as regras de fala, de descrição de imagens e de leitura de documentos do Blind para pessoa cega (as habilidades `jeito-de-falar`, `descrevendo-imagens` e `lendo-documentos`), sem as ferramentas que só existem no Blind local.
- Nenhuma chave de IA entra. `describe_image` entrega a imagem ao próprio Claude, que a descreve. `read_document` não faz OCR de PDF escaneado aqui, porque o OCR usaria a chave de IA do dono.
- Nenhuma ferramenta de sistema é oferecida.
- Não tem terminal, arquivos, controle do mouse e do teclado, WhatsApp, Telegram, e-mail, Drive nem cofre.
- Respeita as ferramentas escondidas do modelo ao chamar (`call_raw(..., from_model=True)`).
- Liga a proteção contra DNS rebinding. Só aceita o Host de `BLIND_REMOTE_HOSTS` (padrão `127.0.0.1` e `localhost`).

## Login

O gateway usa OAuth 2.1 com o GitHub, só para uma conta (`BLIND_REMOTE_GITHUB_USER`). O Claude faz o login uma vez e depois manda um token em cada chamada.

- `/mcp` sem token responde 401. O caminho com segredo na URL deixou de existir.
- O cadastro do Claude só aceita o retorno do próprio Claude (`claude.ai` e `claude.com`) ou um endereço local.
- Outra conta do GitHub vê 403 e não recebe código.
- O código de autorização vale uma vez e cinco minutos. O token de acesso vale uma hora, e o refresh troca a cada uso.
- Os tokens ficam em disco só como hash. O gateway não sobe sem as variáveis abaixo.

Se uma ferramenta que envia ou apaga entrar um dia na lista, a confirmação precisa vir da pessoa, por voz ou teclado, e não do modelo. Hoje nenhuma entra.

## Como ligar

1. **GitHub.** Em Settings, Developer settings, OAuth Apps, crie um app novo. Em "Authorization callback URL" ponha `<endereco publico>/oauth/github/callback`. Guarde o Client ID e gere um Client Secret.
2. **Túnel.** Exponha a porta 8770 (por exemplo `cloudflared tunnel` ou `ngrok http 8770`) e anote o endereço `https://...`. O endereço precisa ser fixo, porque o Claude guarda o conector com ele.
3. **Variáveis.** Ponha num arquivo local fora do repositório, nunca no git:

```powershell
$env:BLIND_REMOTE_PUBLIC_URL = "https://blind.exemplo.net"
$env:BLIND_REMOTE_GITHUB_CLIENT_ID = "..."
$env:BLIND_REMOTE_GITHUB_CLIENT_SECRET = "..."
$env:BLIND_REMOTE_GITHUB_USER = "Blindex09"
# opcional: a pasta de dados do Blind (memoria) e onde guardar o estado do login
$env:BLIND_DATA_DIR = "C:\caminho\do\blind\backend\data"
$env:BLIND_REMOTE_STATE_DIR = "C:\caminho\fora\do\repositorio"
epositorio"
```

4. **Subir.**

```powershell
cd backend
$env:PYTHONPATH = "."
python -m blind_mcp.remote_gateway
```

5. **Claude.** Em Configurações, Conectores, adicione um conector personalizado com a URL `https://blind.exemplo.net/mcp`. O Claude abre o login do GitHub. Entre com a conta liberada.

Para incluir uma ferramenta, ela passa nas três perguntas de `remote_allowlist.py` e entra na lista numa revisão. Os testes estão em `backend/blind_mcp/tests/test_remote_gateway.py`.
