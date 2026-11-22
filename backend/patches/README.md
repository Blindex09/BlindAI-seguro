# Patches locais do Windows-MCP

`C:\repos ia\Windows-MCP` é o projeto original (CursorTouch). Dois patches locais nele (o upstream não tem correção para nenhum dos dois, conferido em 2026-11-16).

## windows-mcp-vk-keys.patch

Problema: `Type` e `Shortcut` de uma tecla (`8`) não digitavam em apps UWP/XAML (Calculadora, Configurações). O
`windows_mcp.uia.SendUnicodeChar` mandava só eventos `KEYEVENTF_UNICODE` (vk=0), que esses apps ignoram.
Correção: para caracteres sem Shift/Ctrl/Alt no layout (dígitos, letras minúsculas, espaço) manda a tecla virtual real; o
resto segue pelo caminho Unicode. Desligue com `WINDOWS_MCP_VK_KEYS=0` (útil com IME de outro idioma).

Aplicar (de novo, depois de um `git pull` no Windows-MCP):

```bash
cd <pasta do Windows-MCP> && git apply <pasta do Blind AI>/backend/patches/windows-mcp-vk-keys.patch
```

Se o `git apply` recusar, o upstream mudou essa função: confira se o problema ainda existe antes de reaplicar.

## windows-mcp-registry-win11.patch

Problema: o Windows 11 ainda grava "Windows 10 Pro" em `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion` (`ProductName`).
Ler esse valor como está diz o sistema errado à pessoa.
Correção: em `registry/service.py`, `get_value` e `list_key` trocam "Windows 10" por "Windows 11" quando o build
(`CurrentBuildNumber`) é 22000 ou maior, e acrescentam um aviso `[corrected: ...]` dizendo o valor original. Só atua nessa chave
e nesse valor; qualquer falha na correção devolve o valor original sem erro.

Aplicar:

```bash
cd <pasta do Windows-MCP> && git apply <pasta do Blind AI>/backend/patches/windows-mcp-registry-win11.patch
```

## a11y-mcp (vendor/a11y-mcp, 17/11/2026)
`vendor/a11y-mcp/node_modules/@community-access/accessibility-agents-mcp/dist/stdio.mjs` (versao 7.1.0 fixa, MIT): logo depois de
`var execFileAsync = promisify(execFile);` um trecho chama o Java direto quando o servidor pede `verapdf` no Windows (o `execFile`
sem shell nao roda o `verapdf.bat`; passar por `cmd` abriria injecao de comando pelo caminho do arquivo). Refazer o patch se
atualizar o pacote. Procure por "PATCH BLIND AI".
