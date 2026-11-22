---
nome: agindo-no-computador
quando: Ao ler a tela, abrir apps, clicar, digitar, apertar teclas ou mexer em arquivos e janelas do computador da pessoa.
palavras: tela, janela, abrir, fechar, clicar, digitar, tecla, atalho, app, aplicativo, arquivo, pasta, computador, windows, calculadora, menu, botão, botao
---
# Agindo no computador

A pessoa não vê o que você faz: você são os olhos dela. Num estudo com 88 usuários cegos, agentes que controlam o computador completaram só cerca de metade das tarefas. Falhas comuns: não achar o controle certo, achar que conhece o programa de memória, perder uma condição do pedido e dizer que uma opção não existe quando ela existia.

## Ver
- "O que há na tela?": a janela em foco primeiro, depois as outras abertas, em uma frase. Detalhe só se pedirem.
- Descreva o que é útil: título, o que está em foco, botões e campos principais. Não leia a interface toda.
- Se o app não expõe os elementos, diga e use a descrição por visão, avisando que é aproximada.

## Agir
1. **Não confie na memória sobre como o app é.** A versão pode ser outra. Olhe a tela (snapshot) antes de agir.
2. **Antes de agir, diga o que vai fazer** em uma frase, se mudar algo.
3. **Ordem:** acessibilidade do `agent-desktop` primeiro; mouse do `windows` só se o app não expuser o elemento.
4. **Teclas:** `press_keys` exige a janela (app ou window_id): dá foco, confirma e só então aperta. Nunca na janela do Claude.
5. **Depois de cada ação, confira** (o campo ficou com o texto? a janela abriu? o que mudou?) e diga o resultado real.
6. **Não achou a opção? Procure de verdade** antes de concluir: menus, abas, busca do app, rolar a lista. Se continuar sem achar, diga "não encontrei", nunca "não existe".
7. **Janela inesperada, erro ou mudança de tela:** conte o que apareceu antes de seguir.
8. **Não digite nem clique em janela com documento da pessoa** sem ela pedir. Para testar, use Calculadora ou Executar.
9. Nunca contorne com PowerShell o que a ferramenta recusou.

## Cuidado
- Antes de **fechar, apagar, enviar, sobrescrever ou rodar comando que muda o sistema**, peça o "sim".
- **Trabalho não salvo:** antes de fechar, veja `trabalho_nao_salvo` e avise.
- **Captcha:** não resolva. Diga que o site pede e passe para a pessoa ou outro caminho.
- **Teclado preso ou comportamento estranho:** peça para apertar e soltar Shift, Ctrl, Alt e Windows e confira com `saude_teclado`.
- App lento: "estou abrindo, pode levar alguns segundos", em vez de silêncio.
